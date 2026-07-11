import asyncio
import threading
import json
import re
import sys
import traceback
from pathlib import Path

# ── DPI awareness fix — must run before any Qt import ─────────────────────────
# Prevents the "SetProcessDpiAwarenessContext() failed: Access is denied" warning
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
except Exception:
    pass  # non-Windows or already set — ignore silently
# ──────────────────────────────────────────────────────────────────────────────

# Force UTF-8 output on Windows to prevent UnicodeEncodeError with emoji characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Suppress Qt DPI warning — must be set before QApplication is created
import os
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

from openai import OpenAI
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)
from tts import get_tts

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.video_search      import video_search
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"

# NVIDIA NIM — primary reasoning engine (OpenAI-compatible, free tier)
NVIDIA_BASE_URL  = "https://integrate.api.nvidia.com/v1"
# Fast + powerful: best balance of speed and quality on NIM
NVIDIA_MODEL     = "meta/llama-3.3-70b-instruct"
# Heavy reasoning for complex tasks only
NVIDIA_MODEL_PRO = "nvidia/llama-3.3-nemotron-super-49b-v1"

CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024


def _get_api_key() -> str:
    """Return the NVIDIA NIM key; fall back to Claude key if absent."""
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    key = cfg.get("nvidia_api_key", "").strip()
    if not key:
        key = cfg.get("claude_api_key", "").strip()
    return key


def _get_nvidia_model() -> str:
    """Read model from config so you can swap it without touching code."""
    try:
        with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("nvidia_model", "meta/llama-3.3-70b-instruct").strip()
    except Exception:
        return "meta/llama-3.3-70b-instruct"


def _make_client():
    """Return an OpenAI-compatible client pointed at NVIDIA NIM."""
    return OpenAI(base_url=NVIDIA_BASE_URL, api_key=_get_api_key())


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )
    
_last_memory_input = ""

def _update_memory_async(user_text: str, jarvis_text: str) -> None:
    global _last_memory_input

    user_text   = (user_text   or "").strip()
    jarvis_text = (jarvis_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return
    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, jarvis_text, api_key):
            return
        data = extract_memory(user_text, jarvis_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] ✅ {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ {e}")

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": "Opens any desktop application by name (e.g. Notepad, Spotify, VS Code, Calculator). Use this for launching installed programs, NOT for opening websites in a browser.",
        "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "description": "Exact app name e.g. 'Notepad', 'Spotify', 'Chrome'"}}, "required": ["app_name"]}
    },
    {
        "name": "web_search",
        "description": "Searches the live web for current information: news, prices, scores, events, facts. Use this when the answer requires up-to-date data.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "mode": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}, "aspect": {"type": "string"}}, "required": ["query"]}
    },
    {
        "name": "weather_report",
        "description": "Gets real-time weather for any city: temperature, humidity, wind, conditions. Optionally includes 3-day forecast.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}, "forecast": {"type": "boolean"}, "units": {"type": "string", "description": "metric or imperial"}}, "required": ["city"]}
    },
    {
        "name": "send_message",
        "description": "Sends a chat message via WhatsApp, Telegram, or similar messaging apps.",
        "parameters": {"type": "object", "properties": {"receiver": {"type": "string"}, "message_text": {"type": "string"}, "platform": {"type": "string"}}, "required": ["receiver", "message_text", "platform"]}
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler. User must specify a date, time, and message.",
        "parameters": {"type": "object", "properties": {"date": {"type": "string"}, "time": {"type": "string"}, "message": {"type": "string"}}, "required": ["date", "time", "message"]}
    },
    {
        "name": "video_search",
        "description": "Search and play videos from any platform. RULES: (1) Use action=play when the user names a specific platform (e.g. 'on TikTok', 'on YouTube', 'on Instagram') — pass that platform in the 'platform' field. (2) Use action=search_all ONLY when no specific platform is mentioned and the user wants results from multiple platforms. (3) NEVER use search_all when a platform is specified. Examples: 'play X on TikTok' → action=play, platform=tiktok. 'search for X videos' → action=search_all. 'find X on YouTube' → action=play, platform=youtube.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "play | search_all | summarize | trending | open_channel"}, "query": {"type": "string"}, "platform": {"type": "string", "description": "REQUIRED for play action when user specifies a platform: youtube | tiktok | instagram | twitter | reddit | facebook | twitch | vimeo | dailymotion | rumble"}, "platforms": {"type": "array", "items": {"type": "string"}}, "url": {"type": "string"}, "region": {"type": "string"}, "channel": {"type": "string"}, "save": {"type": "boolean"}}, "required": []}
    },
    {
        "name": "screen_process",
        "description": "Captures and analyzes what is currently on screen or from the webcam using AI vision. Use when user asks 'what's on my screen', 'what do you see', or wants visual analysis.",
        "parameters": {"type": "object", "properties": {"angle": {"type": "string", "description": "screen or camera"}, "text": {"type": "string", "description": "Question about the image"}}, "required": ["text"]}
    },
    {
        "name": "computer_settings",
        "description": "Controls PC system settings: volume up/down/set/mute, brightness up/down/set, WiFi on/off, take screenshot, dark mode, shutdown, restart, sleep, lock screen, open file explorer, open task manager, get device info, get system info.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "e.g. volume_up, volume_down, volume_set, brightness_set, screenshot, dark_mode, shutdown, restart, wifi_on, device_info, system_info"}, "value": {"type": "string", "description": "Numeric value for set actions"}}, "required": []}
    },
    {
        "name": "browser_control",
        "description": "Controls the web browser: open a URL, search the web, navigate, click, scroll, type, bookmark, zoom, get page text, screenshot. Use when user says 'open website', 'go to', 'browse to', 'search in browser', 'open my browser', 'open browser'. For 'open browser' use action=open_browser. For incognito/private mode set incognito=true.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "open_browser, go_to, search, navigate_current, new_tab, close_tab, scroll, click, type, back, forward, refresh, press, zoom_in, zoom_out, find, bookmark, downloads, history, settings, get_text, screenshot"}, "url": {"type": "string"}, "query": {"type": "string"}, "selector": {"type": "string"}, "text": {"type": "string"}, "direction": {"type": "string"}, "key": {"type": "string"}, "engine": {"type": "string", "description": "google | bing | duckduckgo | youtube | amazon | reddit | twitter | wikipedia"}, "incognito": {"type": "boolean"}}, "required": ["action"]}
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders on disk: list, read, write, create, delete, move, copy, rename, find files, check disk usage.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "path": {"type": "string"}, "destination": {"type": "string"}, "new_name": {"type": "string"}, "content": {"type": "string"}, "name": {"type": "string"}, "extension": {"type": "string"}, "count": {"type": "integer"}}, "required": ["action"]}
    },
    {
        "name": "desktop_control",
        "description": "Controls the Windows desktop: set/get wallpaper, organize or clean desktop icons, list desktop items, create shortcuts, pin apps to taskbar, show desktop, open desktop folder.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "wallpaper | wallpaper_url | current_wallpaper | organize | clean | list | stats | create_shortcut | pin_to_taskbar | show_desktop | open_desktop_folder | task"}, "path": {"type": "string"}, "url": {"type": "string"}, "mode": {"type": "string", "description": "by_type or by_date"}, "name": {"type": "string"}, "task": {"type": "string"}}, "required": ["action"]}
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs or debugs code in any programming language.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "description": {"type": "string"}, "language": {"type": "string"}, "output_path": {"type": "string"}, "file_path": {"type": "string"}, "code": {"type": "string"}, "args": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["action"]}
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file software projects from scratch given a description.",
        "parameters": {"type": "object", "properties": {"description": {"type": "string"}, "language": {"type": "string"}, "project_name": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["description"]}
    },
    {
        "name": "agent_task",
        "description": "Executes a complex multi-step goal that requires planning and using several tools in sequence. Only use for tasks that clearly need multiple different tools.",
        "parameters": {"type": "object", "properties": {"goal": {"type": "string"}, "priority": {"type": "string"}}, "required": ["goal"]}
    },
    {
        "name": "computer_control",
        "description": "Mouse/keyboard automation AND app control. Mouse: click, move, drag. Keyboard: type, hotkey, press. App control: close_app (close an app by title), minimize_app, maximize_app, switch_app (bring to front), list_apps (see running apps), force_close (kill process), alt_tab (switch windows). Also: scroll, screenshot.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string", "description": "click, type, hotkey, scroll, screenshot, move, focus_window, close_app, minimize_app, maximize_app, switch_app, list_apps, force_close, alt_tab"}, "text": {"type": "string"}, "x": {"type": "integer"}, "y": {"type": "integer"}, "keys": {"type": "string"}, "key": {"type": "string"}, "direction": {"type": "string"}, "amount": {"type": "integer"}, "seconds": {"type": "number"}, "title": {"type": "string", "description": "Window or app name for app control actions"}, "app": {"type": "string"}, "path": {"type": "string"}}, "required": ["action"]}
    },
    {
        "name": "game_updater",
        "description": "THE ONLY tool for Steam or Epic Games tasks: update games, install games, list installed games, schedule updates.",
        "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "platform": {"type": "string"}, "game_name": {"type": "string"}, "app_id": {"type": "string"}, "hour": {"type": "integer"}, "minute": {"type": "integer"}, "shutdown_when_done": {"type": "boolean"}}, "required": []}
    },
    {
        "name": "flight_finder",
        "description": "Searches for flights on Google Flights and returns the best options.",
        "parameters": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}, "date": {"type": "string"}, "return_date": {"type": "string"}, "passengers": {"type": "integer"}, "cabin": {"type": "string"}, "save": {"type": "boolean"}}, "required": ["origin", "destination", "date"]}
    },
    {
        "name": "file_processor",
        "description": "Processes uploaded files: read/analyze images, PDFs, Word docs, Excel, CSV, JSON, audio, video, archives.",
        "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "action": {"type": "string"}, "instruction": {"type": "string"}, "format": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "quality": {"type": "integer"}, "save": {"type": "boolean"}}, "required": []}
    },
    {
        "name": "save_memory",
        "description": "Saves a personal fact about the user to long-term memory (name, preferences, job, plans). Call silently alongside a response.",
        "parameters": {"type": "object", "properties": {"category": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}}, "required": ["category", "key", "value"]}
    },
]



def _split_sentences(text: str) -> tuple[list[str], str]:
    """
    Split text into complete sentences and a remaining incomplete fragment.
    Returns (complete_sentences, remainder).
    """
    # Split on sentence-ending punctuation followed by space or end
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    if not parts:
        return [], ""
    # Last part may be incomplete (no terminal punctuation yet)
    if parts[-1] and not re.search(r'[.!?]$', parts[-1]):
        return [s for s in parts[:-1] if s.strip()], parts[-1]
    return [s for s in parts if s.strip()], ""



def _format_news_for_speech(raw: str) -> str:
    """
    Convert raw DDG news output into a concise 2-sentence spoken briefing.
    No LLM call — instant.
    """
    if not raw or "unavailable" in raw.lower():
        return (
            "I could not fetch live news right now, boss. "
            "Would you like me to pull up the full world monitor for a deeper look, boss?"
        )

    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    stories = []
    for line in lines:
        # Skip header lines and URLs
        if line.startswith("Live") or line.startswith("Search") or line.startswith("http"):
            continue
        # Numbered story titles: "1. Title [date] — source"
        m = re.match(r"^\d+\.\s+(.+)", line)
        if m:
            title = re.sub(r"\[\d{4}-.*?\]", "", m.group(1))   # strip date tag
            title = re.sub(r"—\s*\S+$", "", title).strip()       # strip source
            if len(title) > 15:
                stories.append(title)
        if len(stories) >= 2:
            break

    if not stories:
        # Fallback: grab first two non-empty meaningful lines
        for line in lines[2:]:
            if len(line) > 20 and not line.startswith("http"):
                stories.append(line[:120])
            if len(stories) >= 2:
                break

    if not stories:
        return (
            "No major headlines found at the moment, boss. "
            "Would you like me to pull up the full world monitor for a deeper look, boss?"
        )

    brief = "  ".join(f"{s}." if not s.endswith(".") else s for s in stories[:2])
    return f"{brief}  Would you like me to pull up the full world monitor for a deeper look, boss?"


class JarvisLive:

    def __init__(self, ui: JarvisUI):
        self.ui               = ui
        self.session          = None
        self.audio_in_queue   = None
        self.out_queue        = None
        self._loop            = None
        self._is_speaking     = False
        self._speaking_lock   = threading.Lock()
        self._startup_context = []          # filled by _startup_briefing()
        self.ui.on_text_command = self._on_text_command

        # ElevenLabs TTS — speaking state updates UI
        self._tts = get_tts(on_speaking_change=self._on_tts_speaking_change)

    def _on_tts_speaking_change(self, value: bool):
        self.set_speaking(value)

    def _on_text_command(self, text: str):
        """Route text from the UI input box into the queue that _receive_audio polls."""
        if text:
            self.ui._text_queue.put(text)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        """Speak text via ElevenLabs TTS (non-blocking). All responses use ElevenLabs voice."""
        if not text:
            return
        self.ui.write_log(f"Jarvis: {text[:120]}")
        self._tts.speak(text)

    def speak_error(self, tool_name: str, error: str):
        """Speak errors via SAPI only — never waste ElevenLabs quota on error messages."""
        short = str(error)[:80]
        self.ui.write_log(f"ERR: {tool_name} -- {short}")
        try:
            from tts import _sapi_speak
            _sapi_speak(f"Error in {tool_name}, boss.")
        except Exception:
            self._tts.speak(f"Error in {tool_name}, boss.")

    def _build_config(self) -> dict:
        """Build system prompt and tool definitions for Claude."""
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return {
            "system": "\n".join(parts),
            "tools": TOOL_DECLARATIONS,
        }

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Execute a tool and return result."""
        print(f"[JARVIS] 🔧 {tool_name}  {tool_input}")
        self.ui.set_state("THINKING")
        
        if tool_name == "save_memory":
            category = tool_input.get("category", "notes")
            key      = tool_input.get("key", "")
            value    = tool_input.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return {"result": "ok", "silent": True}

        loop   = asyncio.get_event_loop()
        result = "Done."
        args   = tool_input

        try:
            if tool_name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif tool_name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."

            elif tool_name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif tool_name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif tool_name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif tool_name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."

            elif tool_name == "video_search":
                r = await loop.run_in_executor(None, lambda: video_search(parameters=args, response=None, player=self.ui, speak=self.speak))
                result = r or "Done."
            elif tool_name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif tool_name == "screen_process":
                r = await loop.run_in_executor(
                    None,
                    lambda: screen_process(
                        parameters=args, response=None,
                        player=self.ui, session_memory=None,
                    )
                )
                result = r if isinstance(r, str) and r else "Vision analysis complete."

            elif tool_name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif tool_name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif tool_name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif tool_name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif tool_name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif tool_name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."

            elif tool_name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif tool_name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif tool_name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."
            elif tool_name == "shutdown_jarvis":
                self.ui.write_log("SYS: Shutdown requested.")
                # Use ElevenLabs for the goodbye — boss wants the real voice
                self._tts.speak("Goodbye, boss.")

                def _shutdown():
                    import time as _t, os as _os
                    _t.sleep(3.5)   # wait for ElevenLabs to finish speaking
                    _os._exit(0)    # hard exit — guaranteed

                threading.Thread(target=_shutdown, daemon=False).start()
            else:
                result = f"Unknown tool: {tool_name}"

        except Exception as e:
            result = f"Tool '{tool_name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(tool_name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {tool_name} → {str(result)[:80]}")
        return {"result": result}

    async def _send_realtime(self):
        """No-op for compatibility with old architecture."""
        while True:
            await asyncio.sleep(3600)

    async def _play_audio(self):
        """No-op: audio output is handled by ElevenLabs TTS in tts.py."""
        while True:
            await asyncio.sleep(3600)

    async def _receive_audio(self):
        """
        Main conversation loop.
        - Uses Groq llama-3.3-70b-versatile by default (fast, ~0.3-0.8s TTFT)
        - Switches to Nemotron+thinking only when boss explicitly requests deep analysis
        - Boss can cancel deep analysis mode at any time
        - System prompt cached and refreshed every 30 turns (not rebuilt every call)
        """
        import json as _json
        from datetime import datetime as _dt

        client = _make_client()
        loop   = asyncio.get_event_loop()

        conversation      = []
        full_out_log      = []
        deep_mode         = False   # True = use Nemotron+thinking for this turn
        _deep_persistent  = False   # True = stay in deep mode until cancelled
        _sys_cache        = None    # cached system prompt string
        _sys_refresh      = 30      # rebuild system prompt every N turns
        _turn_count       = 0
        _startup_injected = False   # inject startup context once on first user message
        _world_monitor_asked = True  # True = briefing has asked about World Monitor

        # ── Deep analysis mode — flexible regex triggers ──────────────────────
        # Matches natural speech: "activate deep mode", "turn on deep thinking",
        # "use deep analysis", "enable deep", "deep mode please", etc.
        import re as _re_deep
        _DEEP_ON_RE = _re_deep.compile(
            r"\b("
            r"(activate|enable|turn on|switch to|use|start|engage|begin)\s+(deep|nemotron|thinking|detailed)\b"
            r"|deep\s+(analysis|mode|thinking|reasoning)\s*(on|please|now|mode)?"
            r"|think\s+(carefully|deeply|step by step|thoroughly)"
            r"|analyze\s+(deeply|thoroughly|carefully)"
            r"|detailed\s+reasoning"
            r"|deep\s+mode\s+on"
            r")",
            _re_deep.IGNORECASE,
        )
        _DEEP_OFF_RE = _re_deep.compile(
            r"\b("
            r"(cancel|disable|turn off|switch off|deactivate|stop|exit|end)\s+(deep|nemotron|thinking)\b"
            r"|deep\s+(mode\s+off|analysis\s+off|mode\s+disabled)"
            r"|normal\s+mode|fast\s+mode|quick\s+mode"
            r"|stop\s+(thinking\s+deeply|deep\s+thinking|deep\s+analysis)"
            r")",
            _re_deep.IGNORECASE,
        )

        def _build_sys() -> str:
            """Build clean system prompt — called at startup and every _sys_refresh turns."""
            mem_str     = format_memory_for_prompt(load_memory())
            base_prompt = _load_system_prompt()
            now         = _dt.now()
            time_ctx    = (
                f"[CURRENT DATE & TIME]\n"
                f"Right now it is: {now.strftime('%A, %B %d, %Y — %I:%M %p')}\n\n"
            )
            # Strip startup briefing block — only runs at launch, not in conversation
            clean = re.sub(
                r"STARTUP BRIEFING.*?(?=REAL-TIME DATA|RULES:|$)",
                "", base_prompt, flags=re.DOTALL
            ).strip()
            parts = [time_ctx]
            if mem_str:
                parts.append(mem_str)
            parts.append(clean)
            return "\n".join(parts)

        # Build system prompt once at startup
        _sys_cache = _build_sys()

        # Build OpenAI-format tool list once — schemas are already lowercase, just reformat
        tools_oai = []
        for td in TOOL_DECLARATIONS:
            props       = td.get("parameters", {}).get("properties", {})
            clean_props = {}
            for k, v in props.items():
                ptype = v.get("type", "string").lower()
                # Only allow JSON Schema primitive types
                if ptype not in ("object", "array", "integer", "number", "boolean", "string"):
                    ptype = "string"
                prop = dict(v)      # preserve description and other fields
                prop["type"] = ptype
                # Fix nested array items type
                if ptype == "array" and "items" in prop:
                    nested = prop["items"]
                    if isinstance(nested, dict) and "type" in nested:
                        itype = nested["type"].lower()
                        if itype not in ("object", "array", "integer", "number", "boolean", "string"):
                            itype = "string"
                        prop["items"] = dict(nested)
                        prop["items"]["type"] = itype
                clean_props[k] = prop
            tools_oai.append({
                "type": "function",
                "function": {
                    "name":        td["name"],
                    "description": td["description"],
                    "parameters": {
                        "type":       "object",
                        "properties": clean_props,
                        "required":   td.get("parameters", {}).get("required", []),
                    },
                },
            })

        def _call_api(messages: list, use_deep: bool) -> tuple[str, list]:
            """
            Primary: Groq llama-3.3-70b-versatile (sub-1s, best tool calling on Groq).
            Fallback: NVIDIA NIM (if Groq key missing or rate-limited).
            Deep mode: NVIDIA Nemotron with thinking (only when use_deep=True).
            """
            with open(API_CONFIG_PATH, encoding="utf-8") as _f:
                cfg_data = _json.load(_f)
            groq_key   = cfg_data.get("groq_api_key",    "").strip()
            groq_model = cfg_data.get("groq_model",       "llama-3.3-70b-versatile")
            fast_model = cfg_data.get("nvidia_model",     "meta/llama-3.3-70b-instruct")
            deep_model = cfg_data.get("nvidia_model_deep", fast_model)

            use_groq = (
                bool(groq_key)
                and groq_key != "YOUR_GROQ_KEY_HERE"
                and not use_deep
            )

            if use_groq:
                api_client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=groq_key,
                )
                model       = groq_model
                temperature = 0.0    # zero = fully deterministic, best intent understanding
                top_p       = 1.0
                extra       = {}
            else:
                api_client  = client
                model       = deep_model if use_deep else fast_model
                is_nemotron = "nemotron" in model.lower()
                temperature = 1.0 if is_nemotron else 0.3
                top_p       = 0.95 if is_nemotron else 1.0
                extra       = {}
                if is_nemotron:
                    extra = {
                        "extra_body": {
                            "chat_template_kwargs": {"enable_thinking": True},
                            "reasoning_budget": 4096,
                        }
                    }

            state = {"buf": "", "text": "", "tc": {}}

            def _process_chunk(delta):
                if getattr(delta, "reasoning_content", None):
                    return
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in state["tc"]:
                            state["tc"][idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.function:
                            if tc.function.name:
                                state["tc"][idx]["name"] += tc.function.name
                            if tc.function.arguments:
                                state["tc"][idx]["arguments"] += tc.function.arguments
                        if tc.id and not state["tc"][idx]["id"]:
                            state["tc"][idx]["id"] = tc.id
                if delta.content:
                    # Just accumulate — speak full response at end for minimum latency
                    state["buf"]  += delta.content
                    state["text"] += delta.content

            # Groq extra kwargs for better tool calling reliability
            groq_extra = {}
            if use_groq:
                groq_extra["parallel_tool_calls"] = False   # one tool at a time = fewer errors

            # For Groq: use non-streaming (more reliable tool calling, still fast ~0.5s)
            # For NVIDIA: use streaming (better for long responses)

            if use_groq:
                # Non-streaming Groq call — most reliable for tool selection
                try:
                    response = api_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools_oai,
                        tool_choice="auto",
                        max_tokens=600,
                        temperature=temperature,
                        top_p=top_p,
                        stream=False,
                        **groq_extra,
                    )
                    choice = response.choices[0] if response.choices else None
                    if choice:
                        msg = choice.message
                        if msg.content:
                            state["text"] = msg.content
                            # Don't speak here — caller handles TTS to avoid double-speak
                        if msg.tool_calls:
                            for i, tc in enumerate(msg.tool_calls):
                                state["tc"][i] = {
                                    "id":        tc.id or f"call_{i}",
                                    "name":      tc.function.name or "",
                                    "arguments": tc.function.arguments or "{}",
                                }
                except Exception as e:
                    err_s = str(e).lower()
                    if "429" in str(e) or "rate" in err_s:
                        print("[JARVIS] Groq rate limit — falling back to NVIDIA")
                        use_groq    = False
                        api_client  = client
                        model       = fast_model
                        temperature = 0.3
                        top_p       = 1.0
                        extra       = {}
                    elif "tool_use_failed" in err_s or "failed to call a function" in err_s or "tool call validation" in err_s:
                        # llama-3.3-70b-versatile known bug: generates <function=name{args}> XML
                        # instead of JSON tool calls. Retry as plain text — no tools.
                        print(f"[JARVIS] Groq bad tool format — retrying as plain text")
                        try:
                            plain = api_client.chat.completions.create(
                                model=model,
                                messages=messages,
                                max_tokens=300,
                                temperature=0.1,
                                stream=False,
                            )
                            pc = plain.choices[0] if plain.choices else None
                            if pc and pc.message.content:
                                state["text"] = pc.message.content
                                # Do NOT call self.speak() here — caller handles TTS
                        except Exception as _pe:
                            print(f"[JARVIS] Plain retry also failed: {_pe}")
                    else:
                        raise

            if not use_groq:
                # Streaming NVIDIA call
                nvidia_temp = temperature   # already set correctly for NVIDIA (0.3 or 1.0 for Nemotron)
                try:
                    stream = api_client.chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=tools_oai,
                        tool_choice="auto",
                        max_tokens=600,
                        temperature=nvidia_temp,
                        top_p=top_p,
                        stream=True,
                        **extra,
                    )
                    for chunk in stream:
                        if chunk.choices:
                            _process_chunk(chunk.choices[0].delta)
                except Exception as _se:
                    _se_s = str(_se).lower()
                    if "failed_generation" in _se_s or "failed to call a function" in _se_s:
                        print("[JARVIS] NVIDIA tool generation failed — retrying non-stream")
                        state["buf"] = ""; state["text"] = ""; state["tc"] = {}
                        try:
                            retry_resp = api_client.chat.completions.create(
                                model=model, messages=messages, tools=tools_oai,
                                tool_choice="auto", max_tokens=400, temperature=0, stream=False,
                            )
                            choice = retry_resp.choices[0] if retry_resp.choices else None
                            if choice:
                                msg = choice.message
                                if msg.content:
                                    state["text"] = msg.content
                                    # Do NOT call self.speak() here — caller handles TTS
                                if msg.tool_calls:
                                    for i, tc in enumerate(msg.tool_calls):
                                        state["tc"][i] = {
                                            "id":        tc.id or f"call_{i}",
                                            "name":      tc.function.name or "",
                                            "arguments": tc.function.arguments or "{}",
                                        }
                        except Exception as _re:
                            print(f"[JARVIS] NVIDIA retry also failed: {_re}")
                    else:
                        raise

            # Return text without speaking — caller handles TTS
            tc_list = [state["tc"][i] for i in sorted(state["tc"]) if state["tc"][i]["name"]]
            return state["text"].strip(), tc_list

        try:
            while True:
                await asyncio.sleep(0.02)

                if not self.ui.text_input_ready:
                    continue

                user_text = self.ui.get_text_input()
                if not user_text or len(user_text.strip()) <= 1:
                    continue

                user_text = user_text.strip()
                ut_lower  = user_text.lower().rstrip(".,!?")
                print(f"\n[JARVIS] ═══ USER COMMAND: {user_text!r} ═══")
                self.ui.write_log(f"You: {user_text}")

                # ── Deep analysis mode toggle ──────────────────────────────
                # Check OFF first so "turn off deep analysis" doesn't also
                # trigger the ON pattern (which contains "deep analysis").
                _is_deep_off = bool(_DEEP_OFF_RE.search(ut_lower))
                _is_deep_on  = bool(_DEEP_ON_RE.search(ut_lower)) and not _is_deep_off

                if _is_deep_off and _deep_persistent:
                    _deep_persistent = False
                    self.speak("Deep analysis mode off, boss. Back to fast mode.")
                    continue
                elif _is_deep_off and not _deep_persistent:
                    self.speak("Deep analysis mode is already off, boss.")
                    continue

                if _is_deep_on and not _deep_persistent:
                    _deep_persistent = True
                    self.speak("Deep analysis mode on, boss. I'll use Nemotron for thorough reasoning.")
                    # If the command was ONLY the activation phrase (≤5 words), wait for the
                    # actual question on the next turn. Otherwise proceed with the same command.
                    if len(user_text.split()) <= 5:
                        continue
                elif _is_deep_on and _deep_persistent:
                    self.speak("Deep analysis mode is already active, boss.")
                    if len(user_text.split()) <= 5:
                        continue

                use_deep = _deep_persistent

                # ── LOCAL INTENT OVERRIDE ──────────────────────────────────
                # Handle crystal-clear commands without sending to LLM.
                # This prevents the LLM from confusing simple commands.
                _handled = False

                # Volume
                if re.search(r"\bvolume up\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "volume_up"})
                    self.speak("Volume up, boss."); _handled = True
                elif re.search(r"\bvolume down\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "volume_down"})
                    self.speak("Volume down, boss."); _handled = True
                elif m := re.search(r"\bset volume (?:to )?(\d+)\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "volume_set", "value": m.group(1)})
                    self.speak(f"Volume set to {m.group(1)} percent, boss."); _handled = True
                elif (re.search(r"\b(mute|unmute)\b", ut_lower) and "volume" in ut_lower) or ut_lower in ("mute", "unmute"):
                    await self._execute_tool("computer_settings", {"action": "mute"})
                    self.speak("Done, boss."); _handled = True

                # Brightness
                elif re.search(r"\bbrightness up\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "brightness_up"})
                    self.speak("Brightness up, boss."); _handled = True
                elif re.search(r"\bbrightness down\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "brightness_down"})
                    self.speak("Brightness down, boss."); _handled = True
                elif m := re.search(r"\bset brightness (?:to )?(\d+)\b", ut_lower):
                    await self._execute_tool("computer_settings", {"action": "brightness_set", "value": m.group(1)})
                    self.speak(f"Brightness set to {m.group(1)}, boss."); _handled = True

                # Screenshot
                elif re.search(r"\b(take a screenshot|screenshot)\b", ut_lower):
                    r = await self._execute_tool("computer_settings", {"action": "screenshot"})
                    self.speak("Screenshot taken, boss."); _handled = True

                # Write/type something IN an app — "list capabilities in notepad", "type hello in chrome"
                elif m := re.search(r"\b(?:write|type|list|put|show|note|add|insert)\s+(.+?)\s+(?:in|into|on|inside)\s+(.+)", ut_lower):
                    content_part = m.group(1).strip()
                    app_part     = m.group(2).strip()
                    # Only handle if app_part looks like an app name (1-3 words, no URL)
                    if len(app_part.split()) <= 3 and "http" not in app_part:
                        import asyncio as _asyncio
                        # Build content based on what was requested
                        if "capabilities" in content_part or "capabilit" in content_part:
                            write_content = (
                                "JARVIS CAPABILITIES\n"
                                "===================\n"
                                "• Open any installed app on your device\n"
                                "• Control apps (close, minimize, maximize, switch)\n"
                                "• Search the web for current news, prices, events\n"
                                "• Get real-time weather for any city\n"
                                "• Play YouTube videos\n"
                                "• Take screenshots and analyze your screen/webcam\n"
                                "• Send WhatsApp, Telegram, Instagram messages\n"
                                "• Set reminders via Windows Task Scheduler\n"
                                "• Control volume, brightness, WiFi, dark mode\n"
                                "• Read/write/manage files and folders\n"
                                "• Write, run, and explain code\n"
                                "• Find flights on Google Flights\n"
                                "• Control Steam and Epic Games\n"
                                "• Deep analysis mode with NVIDIA Nemotron\n"
                                "• Remember your preferences and facts\n"
                            )
                        else:
                            write_content = content_part

                        # Open the app first
                        open_r = await self._execute_tool("open_app", {"app_name": app_part})
                        import time as _t; _t.sleep(1.5)   # wait for app to open
                        # Then type the content
                        type_r = await self._execute_tool("computer_control", {"action": "type", "text": write_content})
                        self.speak(f"Done, boss. I've written that in {app_part}.")
                        _handled = True

                # Open app — "open X" or "launch X"
                elif m := re.search(r"\b(?:open|launch|start)\s+(.+)", ut_lower):
                    app = m.group(1).strip()
                    # "open browser" / "open my browser" → open the default browser directly
                    if app in ("browser", "my browser", "the browser", "a browser", "web browser", "internet"):
                        try:
                            import subprocess as _sp, json as _j
                            _cfg = _j.load(open(API_CONFIG_PATH, encoding="utf-8"))
                            _browser = _cfg.get("default_browser", "msedge").strip().lower()
                            _exe_map = {"msedge": "msedge", "edge": "msedge", "chrome": "chrome", "firefox": "firefox"}
                            _exe = _exe_map.get(_browser, "msedge")
                            _opened = False
                            try:
                                _sp.Popen([_exe], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                                _opened = True
                            except FileNotFoundError:
                                for _ep in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]:
                                    if Path(_ep).exists():
                                        _sp.Popen([_ep], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                                        _opened = True; break
                            if not _opened:
                                import webbrowser; webbrowser.open("about:blank")
                            self.speak(f"Opening your browser, boss.")
                        except Exception as _e:
                            self.speak(f"Could not open browser, boss: {_e}")
                        _handled = True
                    # Only use local override for app names (avoid "open a website", "open a new project" etc.)
                    elif len(app.split()) <= 3 and not any(x in app for x in ["website", "http", "www", "page"]):
                        r = await self._execute_tool("open_app", {"app_name": app})
                        spoken = r.get("result", "") if isinstance(r, dict) else str(r or "")
                        self.speak(spoken if spoken else f"Opening {app}, boss.")
                        _handled = True

                # Search web
                elif m := re.search(r"\b(?:search for|search|look up|google)\s+(.+)", ut_lower):
                    query = m.group(1).strip()
                    if len(query) > 2:
                        r = await self._execute_tool("web_search", {"query": query})
                        result = r.get("result", "") if isinstance(r, dict) else str(r)
                        # Web search results are long — use SAPI to save ElevenLabs quota
                        # Only speak a short summary via ElevenLabs
                        if result:
                            lines = [l.strip() for l in result.splitlines() if l.strip()]
                            # Find first real headline line
                            headline = next((l for l in lines if len(l) > 20 and not l.startswith("http")), "")
                            if headline:
                                self.speak(f"Here's what I found, boss: {headline[:200]}")
                            else:
                                self.speak("Search complete, boss. Check the log for results.")
                            self.ui.write_log(f"[search] {result[:400]}")
                        else:
                            self.speak("No results found, boss.")
                        _handled = True

                # Weather
                elif m := re.search(r"\bweather\s+(?:in\s+)?(.+)", ut_lower):
                    city = m.group(1).strip()
                    if 1 < len(city.split()) <= 4 or re.match(r"^[a-z ]+$", city):
                        r = await self._execute_tool("weather_report", {"city": city})
                        result = r.get("result", "") if isinstance(r, dict) else str(r)
                        self.speak(result[:300] if result else f"Could not get weather for {city}, boss.")
                        _handled = True

                # JARVIS shutdown — "shutdown"/"shut down" alone = close JARVIS, NOT the PC
                # Must come BEFORE the computer shutdown block so bare "shutdown" hits here first
                elif any(phrase in ut_lower for phrase in (
                    "goodbye", "bye jarvis", "exit jarvis", "quit jarvis",
                    "shut down jarvis", "shutdown jarvis", "goodbye jarvis",
                    "turn off jarvis", "close jarvis", "stop jarvis",
                    "jarvis shutdown", "jarvis exit", "jarvis quit",
                    "shutdown", "shut down",
                )) and not any(x in ut_lower for x in ("computer", "pc", "windows", "system", "my laptop", "device")):
                    await self._execute_tool("shutdown_jarvis", {})
                    _handled = True

                # PC/computer shutdown — only when user explicitly mentions the computer/PC
                elif any(kw in ut_lower for kw in ("computer", "pc", "windows", "my laptop", "device")) and \
                     any(kw in ut_lower for kw in ("shutdown", "shut down", "restart", "reboot", "sleep")):
                    pc_action = ("restart" if any(k in ut_lower for k in ("restart", "reboot"))
                                 else "sleep" if "sleep" in ut_lower
                                 else "shutdown")
                    await self._execute_tool("computer_settings", {"action": pc_action})
                    _handled = True

                # World Monitor (yes to startup briefing) — open in default browser
                # Use substring matching — Scribe may add punctuation/extra words to "yes"
                elif _world_monitor_asked and (
                    ut_lower in ("yes", "yes please", "go ahead", "sure", "open it",
                                 "yes go ahead", "open world monitor", "yes open it",
                                 "yeah", "yep", "ok", "okay", "do it", "open that",
                                 "yes do it", "open the world monitor", "pull it up")
                    or ut_lower.startswith("yes")
                    or ut_lower.startswith("yeah")
                    or ut_lower.startswith("sure")
                    or ut_lower.startswith("go ahead")
                    or ut_lower.startswith("ok")
                    or "world monitor" in ut_lower
                    or "pull it up" in ut_lower
                    or "open it" in ut_lower
                ):
                    _wm_url = "https://www.worldmonitor.app/dashboard"
                    _opened = False
                    print(f"[JARVIS] World Monitor triggered by: {ut_lower!r}")
                    try:
                        import subprocess as _sp, json as _j
                        _cfg2 = _j.load(open(API_CONFIG_PATH, encoding="utf-8"))
                        _browser2 = _cfg2.get("default_browser", "msedge").strip().lower()
                        _exe2 = {"msedge": "msedge", "edge": "msedge",
                                 "chrome": "chrome", "firefox": "firefox"}.get(_browser2, "msedge")
                        try:
                            _sp.Popen([_exe2, _wm_url], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                            _opened = True
                            print(f"[JARVIS] World Monitor opened with {_exe2}")
                        except FileNotFoundError:
                            for _ep in [
                                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                            ]:
                                if Path(_ep).exists():
                                    _sp.Popen([_ep, _wm_url], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                                    _opened = True
                                    print(f"[JARVIS] World Monitor opened with {_ep}")
                                    break
                        if not _opened:
                            import webbrowser
                            webbrowser.open(_wm_url)
                            _opened = True
                            print("[JARVIS] World Monitor opened with webbrowser")
                    except Exception as _e:
                        print(f"[JARVIS] World Monitor open error: {_e}")

                    self.speak("Opening World Monitor now, boss." if _opened
                               else "I could not open World Monitor, boss.")
                    _world_monitor_asked = False
                    _handled = True

                if _handled:
                    _startup_injected = True
                    if not _world_monitor_asked:
                        pass  # already reset above
                    elif not (
                        ut_lower.startswith("yes") or ut_lower.startswith("yeah")
                        or ut_lower.startswith("sure") or ut_lower.startswith("ok")
                        or ut_lower.startswith("go ahead") or "world monitor" in ut_lower
                    ):
                        _world_monitor_asked = False
                    continue
                # ── END LOCAL INTENT OVERRIDE ──────────────────────────────

                self.ui.set_state("THINKING")

                # Inject startup context once — only into first LLM call
                # Remove after first turn so it doesn't bias future commands
                if not _startup_injected:
                    _startup_injected = True

                # Reset World Monitor flag when any non-yes command goes to LLM
                if _world_monitor_asked and not (
                    ut_lower.startswith("yes") or ut_lower.startswith("yeah")
                    or ut_lower.startswith("sure") or ut_lower.startswith("ok")
                    or ut_lower.startswith("go ahead") or "world monitor" in ut_lower
                    or "pull it up" in ut_lower or "open it" in ut_lower
                ):
                    _world_monitor_asked = False

                conversation.append({"role": "user", "content": user_text})

                # Refresh system prompt cache periodically
                _turn_count += 1
                if _turn_count % _sys_refresh == 0:
                    _sys_cache = _build_sys()

                def _clean_conversation(conv: list) -> list:
                    """
                    Keep the conversation clean for Groq's strict validation.
                    Only strips tool_calls/tool messages from PREVIOUS turns (not the current one).
                    The current turn's tool calls + results must stay so the model can summarize them.
                    """
                    # Find the last user message index — everything after it is the current turn
                    last_user_idx = -1
                    for i, msg in enumerate(conv):
                        if msg.get("role") == "user":
                            last_user_idx = i

                    clean = []
                    for i, msg in enumerate(conv):
                        if i > last_user_idx:
                            # Current turn — keep everything including tool_calls and tool results
                            clean.append(msg)
                        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                            # Previous turn tool calls — strip tool_calls, keep text only
                            text = msg.get("content", "") or ""
                            if text.strip():
                                clean.append({"role": "assistant", "content": text})
                            # Skip — corresponding tool results dropped below
                        elif msg.get("role") == "tool":
                            # Previous turn tool results — drop (they reference stripped tool_calls)
                            pass
                        else:
                            clean.append(msg)
                    return clean

                try:
                    full_out_log = []  # reset for this turn
                    while True:
                        # Build clean message snapshot — no stale tool_calls in history
                        clean_conv    = _clean_conversation(list(conversation))
                        messages_snap = [{"role": "system", "content": _sys_cache}] + clean_conv

                        final_text, tool_calls = await loop.run_in_executor(
                            None,
                            lambda: _call_api(messages_snap, use_deep)
                        )

                        if not tool_calls:
                            if final_text:
                                full_out_log.append(final_text)
                                conversation.append({"role": "assistant", "content": final_text})
                                print(f"[JARVIS] ─── RESPONSE (no tool): {final_text[:80]!r}")
                                # Speak the response here — single place, no double-speak
                                self.speak(final_text)
                            break

                        # Log every tool JARVIS decided to call
                        for tc in tool_calls:
                            try:
                                args_preview = json.loads(tc["arguments"] or "{}")
                            except Exception:
                                args_preview = tc["arguments"]
                            print(f"[JARVIS] ─── TOOL SELECTED: {tc['name']} | args: {str(args_preview)[:120]}")

                        # Do NOT append pre-tool text to full_out_log — it's just the model's
                        # internal lead-in before calling the tool. Only append final responses
                        # (the no-tool branch above). This prevents double-speak.

                        tc_objects = [
                            {
                                "id":       tc["id"] or f"call_{i}",
                                "type":     "function",
                                "function": {"name": tc["name"], "arguments": tc["arguments"]},
                            }
                            for i, tc in enumerate(tool_calls)
                        ]
                        conversation.append({
                            "role":       "assistant",
                            "content":    final_text or "",
                            "tool_calls": tc_objects,
                        })

                        self.ui.set_state("THINKING")

                        for tc_obj in tc_objects:
                            try:
                                tool_input = json.loads(tc_obj["function"]["arguments"] or "{}")
                            except Exception:
                                tool_input = {}
                            tool_result = await self._execute_tool(
                                tc_obj["function"]["name"], tool_input
                            )
                            conversation.append({
                                "role":         "tool",
                                "tool_call_id": tc_obj["id"],
                                "content":      json.dumps(tool_result),
                            })

                    full_out = " ".join(full_out_log).strip()
                    if full_out:
                        self.ui.write_log(f"Jarvis: {full_out[:200]}")
                    full_out_log = []

                    if len(user_text) > 5:
                        threading.Thread(
                            target=_update_memory_async,
                            args=(user_text, full_out),
                            daemon=True
                        ).start()

                    if len(conversation) > 12:
                        # Keep only the last 6 turns (12 messages)
                        # but always keep the startup context at the front
                        conversation = conversation[-12:]

                except Exception as e:
                    err_str = str(e)
                    print(f"[JARVIS] API error: {err_str}")
                    traceback.print_exc()
                    if "tool_use_failed" in err_str or "tool call validation" in err_str.lower() or "failed to call a function" in err_str.lower():
                        # Bad tool format from model — clear history, don't crash
                        print("[JARVIS] Clearing conversation history due to tool validation error")
                        conversation.clear()
                        msg = "Sorry boss, I had a formatting issue. Please say that again."
                    elif "401" in err_str or "authentication" in err_str.lower():
                        msg = "Invalid API key, boss. Please update config/api_keys.json."
                    elif "429" in err_str or "rate" in err_str.lower():
                        msg = "Rate limit hit, boss. Give me a moment."
                    else:
                        msg = f"I hit an error, boss: {err_str[:80]}"
                    self.ui.write_log(f"ERR: {msg}")
                    self.speak(msg)
                    full_out_log = []

                finally:
                    if not self.ui.muted:
                        self.ui.set_state("LISTENING")

        except Exception as e:
            print(f"[JARVIS] Recv loop crashed: {e}")
            traceback.print_exc()
            raise

    async def _startup_briefing(self):
        """
        Startup briefing — runs once on launch.
        Uses direct DDG news HTTP fetch (faster than full web_search).
        News fetch starts immediately while greeting audio plays.
        Zero LLM calls — instant formatting.
        """
        from datetime import datetime

        loop = asyncio.get_event_loop()
        await asyncio.sleep(0.8)

        self.ui.set_state("THINKING")
        self.ui.write_log("SYS: Running startup briefing...")

        now      = datetime.now()
        date_str = now.strftime("%A, %B %d %Y")
        time_str = now.strftime("%I:%M %p")

        greeting = f"Greetings boss, welcome back. Today is {date_str} and the time is {time_str}."
        self.speak(greeting)
        self.ui.write_log(f"Jarvis: {greeting}")

        # Fetch news from multiple RSS feeds in parallel
        def _fast_news():
            import xml.etree.ElementTree as _ET
            import requests as _req
            import concurrent.futures as _cf

            _HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            _FEEDS = [
                ("BBC",        "https://feeds.bbci.co.uk/news/world/rss.xml"),
                ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
                ("Guardian",   "https://www.theguardian.com/world/rss"),
                ("NPR",        "https://feeds.npr.org/1001/rss.xml"),
                ("CNN",        "http://rss.cnn.com/rss/edition_world.rss"),
            ]

            def _fetch_one(name_url):
                name, url = name_url
                try:
                    resp  = _req.get(url, timeout=4, headers=_HDR)
                    resp.raise_for_status()
                    root  = _ET.fromstring(resp.content)
                    items = root.findall("./channel/item/title") or root.findall(".//item/title")
                    for item in items:
                        t = (item.text or "").strip()
                        if len(t) > 20:
                            return t
                except Exception:
                    pass   # silently skip — network may be down
                return None

            headlines = []
            try:
                with _cf.ThreadPoolExecutor(max_workers=5) as ex:
                    futs = [ex.submit(_fetch_one, f) for f in _FEEDS]
                    for fut in _cf.as_completed(futs, timeout=6):
                        try:
                            result = fut.result()
                            if result and result not in headlines:
                                headlines.append(result)
                        except Exception:
                            pass
                        if len(headlines) >= 3:
                            break
            except Exception:
                pass

            if headlines:
                print(f"[News] Got {len(headlines)} headlines")
            else:
                print("[News] No headlines — network may be offline")
            return headlines[:3]

        # Fetch news in thread — doesn't block the async loop
        try:
            headlines = await asyncio.get_event_loop().run_in_executor(None, _fast_news)
        except Exception as e:
            print(f"[News] Fetch failed: {e}")
            headlines = []

        # Format into spoken briefing — instant, no LLM
        if headlines:
            # Build 2-3 sentence briefing from different sources
            stories = "  ".join(
                f"{h}." if not h.endswith(".") else h
                for h in headlines[:3]
            )
            briefing_text = (
                f"{stories}  "
                "Would you like me to pull up the full world monitor for a deeper look, boss?"
            )
        else:
            briefing_text = (
                "I could not fetch live news at the moment, boss. "
                "Would you like me to pull up the full world monitor for a deeper look, boss?"
            )

        self.speak(briefing_text)
        self.ui.write_log(f"Jarvis: {briefing_text}")

        self._startup_context = [
            {"role": "user",      "content": "[SYSTEM NOTE] Startup briefing was delivered automatically at launch. The boss has not asked any question yet."},
            {"role": "assistant", "content": f"{greeting} {briefing_text}"},
        ]
        self.ui.set_state("LISTENING")

    async def run(self):
        """Main loop using Claude for text-based AI."""
        _first_run = True
        while True:
            try:
                print("[JARVIS] 🔌 Connecting to Claude...")
                self.ui.set_state("THINKING")

                print("[JARVIS] ✅ Connected.")
                self.ui.set_state("LISTENING")
                self.ui.write_log("SYS: JARVIS online.")

                self._loop = asyncio.get_event_loop()
                self.audio_in_queue = asyncio.Queue()
                self.out_queue      = asyncio.Queue(maxsize=50)

                if _first_run:
                    _first_run = False
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._startup_briefing())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())
                else:
                    async with asyncio.TaskGroup() as tg:
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())

            except Exception as e:
                print(f"[JARVIS] ⚠️ {e}")
                traceback.print_exc()

            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[JARVIS] 🔄 Reconnecting in 3s...")
            await asyncio.sleep(3)

    async def _listen_audio(self):
        """
        Continuous microphone listener.
        Records via sounddevice (no pyaudio needed), sends WAV to ElevenLabs Scribe v2.
        If Scribe quota exhausted → falls back to Google STT via sounddevice.
        """
        import io
        import wave
        import time as _time
        import numpy as np
        import sounddevice as sd

        loop = asyncio.get_event_loop()

        # Load config
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as _f:
                _cfg = json.load(_f)
            el_key  = _cfg.get("elevenlabs_api_key", "").strip()
            mic_idx = _cfg.get("mic_index", None)
        except Exception:
            el_key  = ""
            mic_idx = None

        # ── VALID single-word commands — checked FIRST, bypass all filters ──
        # These words are allowed through regardless of noise/hallucination rules.
        _VALID_SINGLE_WORDS = {
            "yes", "no", "ok", "okay", "sure", "yeah", "yep", "nope",
            "stop", "cancel", "open", "close", "play", "pause", "next",
            "back", "quit", "exit", "shutdown", "mute", "unmute",
            "screenshot", "thanks", "hello", "hi", "jarvis",
        }

        # ── Noise phrases — background sounds with NO command meaning ────
        # DO NOT put valid commands here — use _VALID_SINGLE_WORDS above.
        _NOISE_PHRASES = {
            "", "uh", "um", "hmm", "hm", "ah", "mm", "mmm", "mhm",
            "uh huh", "the", "a", "oh", "eh",
        }

        # ── Hallucination blocklist ──────────────────────────────────────
        # Scribe commonly generates these from silence / background audio.
        # IMPORTANT: never put words from _VALID_SINGLE_WORDS here.
        _HALLUCINATION_EXACT = {
            "thank you", "thank you.",
            "you", "you.", "i", "i.",
            "right", "right.",
            "bye bye", "bye bye.",
            "i see", "i see.", "i see that", "i see that.",
            "of course", "of course.", "certainly", "certainly.",
            "all right", "all right.", "alright", "alright.",
            "i understand", "i understand.",
            "one moment", "one moment.", "just a moment", "just a moment.",
        }

        _NOISE_PATTERNS = [
            r"^\s*[\W\d]+\s*$",
            r"^.{1,2}$",
            r"^\[.*\]$",   # pure Scribe sound tags like [music] [applause]
        ]

        SAMPLE_RATE     = 44100
        CHANNELS        = 1
        CHUNK_FRAMES    = 1024
        # ── VAD thresholds (tuned for headset mic at normal talking volume) ─
        # SPEECH_RMS = onset trigger. Headset mics (Realtek) at 30–50cm read
        # normal speech as 400–900 RMS. 450 catches a calm voice without
        # triggering on keyboard clicks (~200 RMS) or chair noise (~150 RMS).
        SILENCE_RMS     = 200    # below this = silence
        SPEECH_RMS      = 450    # above this = speech onset (was 800 — too high, required shouting)
        MIN_SPEECH_SEC  = 0.4    # ignore clips under 0.4s (was 0.6 — cut short words like "play")
        MAX_SPEECH_SEC  = 22.0
        SILENCE_END_SEC = 1.1    # stop after 1.1s of silence

        # Minimum average RMS of the full recording.
        # Headset mic headset baseline noise floor is ~80-120 RMS, real speech ~350+.
        MIN_AVG_RMS     = 180    # was 300 — too high for quiet/calm speech

        def _chunk_rms(chunk: np.ndarray) -> float:
            """RMS of int16 chunk (range 0–32768)."""
            return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))

        def _make_wav(frames: list, boost: float = 2.5) -> bytes:
            """
            Concatenate int16 numpy chunks into a WAV file.
            Applies a gain boost so quiet/accented speech is louder for Scribe.
            boost=2.5 amplifies without hard clipping for typical headset levels.
            """
            audio = np.concatenate(frames, axis=0).flatten().astype(np.float64)
            # Amplify — clip to int16 range to avoid wrap-around distortion
            audio = np.clip(audio * boost, -32768, 32767).astype(np.int16)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            buf.seek(0)
            return buf.read()

        # Show available devices
        try:
            devs = sd.query_devices()
            print(f"[JARVIS] Audio devices:")
            for i, d in enumerate(devs):
                if d['max_input_channels'] > 0:
                    print(f"  [{i}] {d['name']}")
        except Exception:
            pass

        if mic_idx is not None:
            try:
                dev_info = sd.query_devices(mic_idx)
                print(f"[JARVIS] Using mic [{mic_idx}]: {dev_info['name']}")
            except Exception:
                print(f"[JARVIS] mic_index {mic_idx} invalid — using default")
                mic_idx = None

        # Boost mic volume (non-critical)
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            mic_dev = AudioUtilities.GetMicrophone()
            if mic_dev:
                iface   = mic_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                mic_vol = cast(iface, POINTER(IAudioEndpointVolume))
                mic_vol.SetMasterVolumeLevelScalar(1.0, None)
                print("[JARVIS] Mic volume boosted to 100%")
        except Exception:
            pass

        use_scribe = bool(el_key)
        if use_scribe:
            from elevenlabs import ElevenLabs as _EL
            el_client = _EL(api_key=el_key)
            print("[JARVIS] STT: ElevenLabs Scribe v2")
            self.ui.write_log("SYS: Mic active (Scribe STT) — speak to JARVIS.")
        else:
            print("[JARVIS] STT: Google")
            self.ui.write_log("SYS: Mic active (Google STT) — speak to JARVIS.")

        def _transcribe_loop():
            nonlocal use_scribe

            sd_kwargs = dict(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_FRAMES,
            )
            if mic_idx is not None:
                sd_kwargs["device"] = mic_idx

            print(f"[JARVIS] Opening mic stream (sr={SAMPLE_RATE}, device={mic_idx})")

            try:
                with sd.InputStream(**sd_kwargs) as stream:
                    print("[JARVIS] Mic open — listening...")

                    while True:
                        # ── MUTED OR JARVIS SPEAKING: drain buffer aggressively ──
                        if self.ui.muted or self._is_speaking:
                            # Keep draining until JARVIS stops speaking
                            while self.ui.muted or self._is_speaking:
                                try:
                                    stream.read(CHUNK_FRAMES * 8)
                                except Exception:
                                    pass
                                _time.sleep(0.05)
                            # After speaking stops: wait 1.2s + drain 60 chunks
                            # This prevents TTS audio echo from being transcribed as a command.
                            # 1.2s is enough for ElevenLabs PCM to fully flush from the speaker.
                            _time.sleep(1.2)
                            for _ in range(60):
                                try:
                                    stream.read(CHUNK_FRAMES)
                                except Exception:
                                    break
                            continue

                        # ── WAIT FOR SPEECH ONSET ──
                        try:
                            chunk, _ = stream.read(CHUNK_FRAMES)
                        except Exception:
                            _time.sleep(0.05)
                            continue

                        if _chunk_rms(chunk) < SPEECH_RMS:
                            continue  # silence — keep waiting

                        # ── RECORD UNTIL SILENCE ──
                        frames  = [chunk]
                        silence = 0.0
                        elapsed = CHUNK_FRAMES / SAMPLE_RATE

                        while elapsed < MAX_SPEECH_SEC:
                            # Stop if JARVIS starts speaking mid-recording
                            if self._is_speaking:
                                frames = []
                                break

                            try:
                                chunk, _ = stream.read(CHUNK_FRAMES)
                            except Exception:
                                break
                            frames.append(chunk)
                            elapsed += CHUNK_FRAMES / SAMPLE_RATE

                            rms = _chunk_rms(chunk)
                            if rms < SILENCE_RMS:
                                silence += CHUNK_FRAMES / SAMPLE_RATE
                                if silence >= SILENCE_END_SEC:
                                    break
                            else:
                                silence = 0.0

                        if not frames or elapsed < MIN_SPEECH_SEC:
                            if elapsed > 0:
                                print(f"[JARVIS] Clip too short ({elapsed:.2f}s) — skipped")
                            continue

                        # ── ENERGY GATE ──────────────────────────────────────
                        # Reject near-silent clips even if they passed the onset
                        # threshold — these cause Scribe to hallucinate words.
                        all_audio  = np.concatenate(frames, axis=0).flatten()
                        avg_rms    = float(np.sqrt(np.mean(all_audio.astype(np.float64) ** 2)))
                        if avg_rms < MIN_AVG_RMS:
                            print(f"[JARVIS] Low energy clip (avg RMS {avg_rms:.0f}) — skipped")
                            continue

                        # ── TRANSCRIBE ──
                        wav_bytes = _make_wav(frames)
                        text = ""

                        if use_scribe:
                            try:
                                # Resample 44100 → 16000 Hz using pure numpy (no audioop needed).
                                # Scribe is trained on 16kHz — resampling improves accuracy
                                # especially for accented speech.
                                try:
                                    src = np.frombuffer(wav_bytes[44:], dtype=np.int16).astype(np.float32)
                                    # Simple decimation: pick every Nth sample
                                    ratio   = SAMPLE_RATE / 16000          # 44100/16000 ≈ 2.756
                                    n_out   = int(len(src) / ratio)
                                    indices = (np.arange(n_out) * ratio).astype(np.int32)
                                    indices = np.clip(indices, 0, len(src) - 1)
                                    resampled = src[indices].astype(np.int16)
                                    buf_16k = io.BytesIO()
                                    with wave.open(buf_16k, "wb") as wf:
                                        wf.setnchannels(1)
                                        wf.setsampwidth(2)
                                        wf.setframerate(16000)
                                        wf.writeframes(resampled.tobytes())
                                    buf_16k.seek(0)
                                    scribe_buf = buf_16k
                                except Exception:
                                    scribe_buf = io.BytesIO(wav_bytes)

                                scribe_buf.name = "speech.wav"
                                result = el_client.speech_to_text.convert(
                                    file=scribe_buf,
                                    model_id="scribe_v2",
                                    language_code="en",
                                    tag_audio_events=False,
                                    diarize=False,
                                )
                                text = (result.text or "").strip()
                            except Exception as e:
                                err_s = str(e).lower()
                                if any(x in err_s for x in ("quota_exceeded", "0 credits", "quota exceeded")):
                                    print("[JARVIS] Scribe quota exhausted — switching to Google STT")
                                    self.ui.write_log("SYS: Scribe quota used — Google STT active.")
                                    use_scribe = False
                                elif any(x in err_s for x in ("getaddrinfo", "name resolution", "network", "connection", "timeout", "unreachable")):
                                    # Network error — silently fall through to Google STT this clip
                                    print("[JARVIS] Scribe unreachable (network) — trying Google STT")
                                    use_scribe = False
                                else:
                                    print(f"[JARVIS] Scribe error: {str(e)[:80]}")
                                    continue

                        if not use_scribe:
                            try:
                                import speech_recognition as _sr
                                _rec = _sr.Recognizer()
                                ad   = _sr.AudioData(wav_bytes, SAMPLE_RATE, 2)
                                # Use show_all=False with language hints for better accent coverage
                                # Prefer en-NG (Nigerian), en-GB (British), en-US as fallbacks
                                text = _rec.recognize_google(
                                    ad,
                                    language="en-NG",   # Nigerian English — best for your accent
                                    show_all=False,
                                ).strip()
                            except Exception as e:
                                if "UnknownValueError" not in type(e).__name__:
                                    print(f"[JARVIS] Google STT error: {str(e)[:80]}")
                                continue

                        if not text:
                            continue

                        # ── NOISE FILTER ──
                        # Strip Scribe sound-event tags like [outro jingle], [clattering], [music]
                        # These are NEVER voice commands — always background audio
                        clean_text = re.sub(r"\[.*?\]", "", text).strip()
                        # Also strip leading/trailing punctuation Scribe adds
                        clean_text = clean_text.strip(".,!?;: ")

                        if not clean_text:
                            print(f"[JARVIS] Scribe tag only — filtered: {text!r}")
                            continue

                        text_lower = clean_text.lower().rstrip(".,!? ")
                        word_count = len(clean_text.split())

                        # ── STEP 1: Valid single-word commands — pass through immediately ──
                        # Check this FIRST before any noise or hallucination filter.
                        if word_count == 1 and text_lower in _VALID_SINGLE_WORDS:
                            print(f"[JARVIS] >>> Heard (single-word command): {clean_text}")
                            self.ui._text_queue.put(clean_text)
                            continue

                        # ── STEP 2: Hallucination blocklist ──────────────────
                        # Drop known Scribe hallucinations (never contains valid commands)
                        if text_lower in _HALLUCINATION_EXACT or clean_text.lower() in _HALLUCINATION_EXACT:
                            print(f"[JARVIS] Hallucination blocked: {clean_text!r}")
                            continue

                        # ── STEP 3: General noise filter ─────────────────────
                        is_noise = (
                            word_count < 2
                            or text_lower in _NOISE_PHRASES
                            or any(re.match(p, text_lower) for p in _NOISE_PATTERNS)
                        )
                        if is_noise:
                            print(f"[JARVIS] Noise filtered ({word_count}w): {text!r}")
                        else:
                            print(f"[JARVIS] >>> Heard: {clean_text}")
                            self.ui._text_queue.put(clean_text)

            except Exception as e:
                print(f"[JARVIS] Mic stream error: {e}")
                self.ui.write_log(f"SYS: Mic error — {e}")
                _time.sleep(2)

        await loop.run_in_executor(None, _transcribe_loop)

    async def _listen_audio_google(self):
        """
        Google STT fallback — uses sounddevice (no pyaudio needed).
        Called only when _listen_audio exits (e.g. Scribe quota).
        """
        import io
        import wave
        import time as _time
        import numpy as np
        import sounddevice as sd

        loop = asyncio.get_event_loop()

        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as _f:
                _cfg_g = json.load(_f)
            _mic_idx_g = _cfg_g.get("mic_index", None)
        except Exception:
            _mic_idx_g = None

        _NOISE = {
            "", "uh", "um", "hmm", "hm", "ah", "mm", "mmm", "mhm", "uh huh", "the", "a",
        }

        SAMPLE_RATE     = 44100
        CHANNELS        = 1
        CHUNK_FRAMES    = 1024
        SILENCE_RMS     = 300    # match Scribe VAD thresholds
        SPEECH_RMS      = 500    # lower = picks up quieter/accented speech
        MIN_SPEECH_SEC  = 0.3
        MAX_SPEECH_SEC  = 20.0
        SILENCE_END_SEC = 0.8

        def _chunk_rms(chunk):
            return float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))

        def _make_wav(frames):
            audio = np.concatenate(frames, axis=0).flatten()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio.tobytes())
            buf.seek(0)
            return buf.read()

        print(f"[JARVIS] Google STT fallback (mic_index={_mic_idx_g})")
        self.ui.write_log("SYS: Google STT active — speak to JARVIS.")

        def _loop_fn():
            sd_kwargs = dict(samplerate=SAMPLE_RATE, channels=CHANNELS,
                             dtype="int16", blocksize=CHUNK_FRAMES)
            if _mic_idx_g is not None:
                sd_kwargs["device"] = _mic_idx_g

            try:
                with sd.InputStream(**sd_kwargs) as stream:
                    while True:
                        if self.ui.muted or self._is_speaking:
                            while self.ui.muted or self._is_speaking:
                                try: stream.read(CHUNK_FRAMES * 8)
                                except Exception: pass
                                _time.sleep(0.05)
                            _time.sleep(0.7)
                            for _ in range(30):
                                try: stream.read(CHUNK_FRAMES)
                                except Exception: break
                            continue

                        try:
                            chunk, _ = stream.read(CHUNK_FRAMES)
                        except Exception:
                            _time.sleep(0.05); continue

                        if _chunk_rms(chunk) < SPEECH_RMS:
                            continue

                        frames  = [chunk]
                        silence = 0.0
                        elapsed = CHUNK_FRAMES / SAMPLE_RATE

                        while elapsed < MAX_SPEECH_SEC:
                            if self._is_speaking:
                                frames = []; break
                            try:
                                chunk, _ = stream.read(CHUNK_FRAMES)
                            except Exception: break
                            frames.append(chunk)
                            elapsed += CHUNK_FRAMES / SAMPLE_RATE
                            if _chunk_rms(chunk) < SILENCE_RMS:
                                silence += CHUNK_FRAMES / SAMPLE_RATE
                                if silence >= SILENCE_END_SEC: break
                            else:
                                silence = 0.0

                        if not frames or elapsed < MIN_SPEECH_SEC:
                            continue

                        wav_bytes = _make_wav(frames)
                        try:
                            import speech_recognition as _sr
                            _rec = _sr.Recognizer()
                            ad   = _sr.AudioData(wav_bytes, SAMPLE_RATE, 2)
                            # Nigerian English language hint — better accent recognition
                            text = _rec.recognize_google(ad, language="en-NG").strip()
                            tl   = text.lower().rstrip(".,!? ")
                            wc   = len(text.split())
                            if text and wc >= 1 and tl not in _NOISE:
                                print(f"[JARVIS] >>> Heard (Google): {text}")
                                self.ui._text_queue.put(text)
                            elif text:
                                print(f"[JARVIS] Noise filtered: {text!r}")
                        except Exception as e:
                            if "UnknownValueError" not in type(e).__name__:
                                print(f"[JARVIS] Google STT error: {str(e)[:80]}")
            except Exception as e:
                print(f"[JARVIS] Google STT stream error: {e}")

        await loop.run_in_executor(None, _loop_fn)


def main():
    # ── Single-instance guard ──────────────────────────────────────────────
    # If JARVIS is already running, bring its window to front and exit.
    import tempfile, atexit
    _lock_file = Path(tempfile.gettempdir()) / "jarvis_instance.lock"

    try:
        import msvcrt
        _lf = open(_lock_file, "w")
        msvcrt.locking(_lf.fileno(), msvcrt.LK_NBLCK, 1)
        # Lock acquired — we are the only instance
        @atexit.register
        def _release():
            try:
                _lf.close()
                _lock_file.unlink(missing_ok=True)
            except Exception:
                pass
    except (OSError, IOError):
        # Another instance is already running — just exit silently
        print("[JARVIS] Already running — exiting duplicate.")
        import sys
        sys.exit(0)

    # ── Launch UI ─────────────────────────────────────────────────────────
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n[JARVIS] Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
