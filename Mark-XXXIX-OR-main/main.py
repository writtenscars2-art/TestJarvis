import asyncio
import threading
import json
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
from actions.youtube_video     import youtube_video
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
    {"name": "open_app",          "description": "Opens any app, program or website on Windows.", "parameters": {"type": "OBJECT", "properties": {"app_name": {"type": "STRING", "description": "App name e.g. Chrome, Spotify"}}, "required": ["app_name"]}},
    {"name": "web_search",        "description": "Searches the live web. Use for any current event, news, price, or fact.", "parameters": {"type": "OBJECT", "properties": {"query": {"type": "STRING"}, "mode": {"type": "STRING"}, "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "aspect": {"type": "STRING"}}, "required": ["query"]}},
    {"name": "weather_report",    "description": "Gets real-time weather for any city — current conditions, temperature, humidity, wind, and optional 3-day forecast.", "parameters": {"type": "OBJECT", "properties": {"city": {"type": "STRING"}, "forecast": {"type": "boolean", "description": "true to include 3-day forecast"}, "units": {"type": "STRING", "description": "metric or imperial"}}, "required": ["city"]}},
    {"name": "send_message",      "description": "Sends a message via WhatsApp, Telegram, etc.", "parameters": {"type": "OBJECT", "properties": {"receiver": {"type": "STRING"}, "message_text": {"type": "STRING"}, "platform": {"type": "STRING"}}, "required": ["receiver", "message_text", "platform"]}},
    {"name": "reminder",          "description": "Sets a Windows Task Scheduler reminder.", "parameters": {"type": "OBJECT", "properties": {"date": {"type": "STRING"}, "time": {"type": "STRING"}, "message": {"type": "STRING"}}, "required": ["date", "time", "message"]}},
    {"name": "youtube_video",     "description": "Plays, summarizes, or shows trending YouTube videos.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "query": {"type": "STRING"}, "save": {"type": "BOOLEAN"}, "region": {"type": "STRING"}, "url": {"type": "STRING"}}, "required": []}},
    {"name": "screen_process",    "description": "Captures screen or webcam and analyzes with AI vision. Returns a spoken description. Call when user asks what's on screen, describes what they see, or wants camera analysis.", "parameters": {"type": "OBJECT", "properties": {"angle": {"type": "STRING", "description": "'screen' for display, 'camera' for webcam. Default: screen"}, "text": {"type": "STRING", "description": "Question or instruction about the image"}}, "required": ["text"]}},
    {"name": "computer_settings", "description": "Controls PC: volume, brightness, WiFi, screenshots, window management, dark mode, shutdown, restart, scroll, zoom, lock screen, file explorer, task manager. Use action field with values like volume_up, volume_down, mute, volume_set, get_volume, brightness_up, brightness_down, brightness_set, get_brightness, screenshot, lock_screen, shutdown, restart, dark_mode, toggle_wifi, fullscreen, minimize, maximize, close_app, scroll_up, scroll_down, new_tab, close_tab, refresh_page, copy, paste, save.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "description": {"type": "STRING"}, "value": {"type": "STRING", "description": "For set actions: the value (e.g. 75 for volume/brightness). For type: text to type."}}, "required": []}},
    {"name": "browser_control",   "description": "Controls browser: open URLs, search, click, scroll, fill forms, get page text.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "url": {"type": "STRING"}, "query": {"type": "STRING"}, "selector": {"type": "STRING"}, "text": {"type": "STRING"}, "description": {"type": "STRING"}, "direction": {"type": "STRING"}, "key": {"type": "STRING"}, "incognito": {"type": "BOOLEAN"}}, "required": ["action"]}},
    {"name": "file_controller",   "description": "Manages files/folders: list, read, write, create, delete, move, copy, rename, find, disk usage.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "path": {"type": "STRING"}, "destination": {"type": "STRING"}, "new_name": {"type": "STRING"}, "content": {"type": "STRING"}, "name": {"type": "STRING"}, "extension": {"type": "STRING"}, "count": {"type": "INTEGER"}}, "required": ["action"]}},
    {"name": "desktop_control",   "description": "Controls desktop: wallpaper, organize, clean, list, stats.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "path": {"type": "STRING"}, "url": {"type": "STRING"}, "mode": {"type": "STRING"}, "task": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "code_helper",       "description": "Writes, edits, explains, runs or builds code.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "description": {"type": "STRING"}, "language": {"type": "STRING"}, "output_path": {"type": "STRING"}, "file_path": {"type": "STRING"}, "code": {"type": "STRING"}, "args": {"type": "STRING"}, "timeout": {"type": "INTEGER"}}, "required": ["action"]}},
    {"name": "dev_agent",         "description": "Builds complete multi-file projects from scratch.", "parameters": {"type": "OBJECT", "properties": {"description": {"type": "STRING"}, "language": {"type": "STRING"}, "project_name": {"type": "STRING"}, "timeout": {"type": "INTEGER"}}, "required": ["description"]}},
    {"name": "agent_task",        "description": "Executes complex multi-step tasks needing multiple tools. Not for single actions.", "parameters": {"type": "OBJECT", "properties": {"goal": {"type": "STRING"}, "priority": {"type": "STRING"}}, "required": ["goal"]}},
    {"name": "computer_control",  "description": "Direct mouse/keyboard control: type, click, hotkeys, scroll, screenshot, find screen elements.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "text": {"type": "STRING"}, "x": {"type": "INTEGER"}, "y": {"type": "INTEGER"}, "keys": {"type": "STRING"}, "key": {"type": "STRING"}, "direction": {"type": "STRING"}, "amount": {"type": "INTEGER"}, "seconds": {"type": "NUMBER"}, "title": {"type": "STRING"}, "description": {"type": "STRING"}, "path": {"type": "STRING"}}, "required": ["action"]}},
    {"name": "game_updater",      "description": "THE ONLY tool for Steam or Epic Games: update, install, list, schedule. Never use web_search for games.", "parameters": {"type": "OBJECT", "properties": {"action": {"type": "STRING"}, "platform": {"type": "STRING"}, "game_name": {"type": "STRING"}, "app_id": {"type": "STRING"}, "hour": {"type": "INTEGER"}, "minute": {"type": "INTEGER"}, "shutdown_when_done": {"type": "BOOLEAN"}}, "required": []}},
    {"name": "flight_finder",     "description": "Searches Google Flights and speaks best options.", "parameters": {"type": "OBJECT", "properties": {"origin": {"type": "STRING"}, "destination": {"type": "STRING"}, "date": {"type": "STRING"}, "return_date": {"type": "STRING"}, "passengers": {"type": "INTEGER"}, "cabin": {"type": "STRING"}, "save": {"type": "BOOLEAN"}}, "required": ["origin", "destination", "date"]}},
    {"name": "file_processor",    "description": "Processes uploaded files: images, PDFs, Word, Excel, CSV, JSON, code, audio, video, archives, presentations.", "parameters": {"type": "OBJECT", "properties": {"file_path": {"type": "STRING"}, "action": {"type": "STRING"}, "instruction": {"type": "STRING"}, "format": {"type": "STRING"}, "width": {"type": "INTEGER"}, "height": {"type": "INTEGER"}, "quality": {"type": "INTEGER"}, "save": {"type": "BOOLEAN"}}, "required": []}},
    {"name": "shutdown_jarvis",   "description": "Shuts down JARVIS completely. Call when user says goodbye or wants to exit.", "parameters": {"type": "OBJECT", "properties": {}}},
    {"name": "save_memory",       "description": "Silently saves personal facts about the user to long-term memory. Call when user reveals name, job, preferences, plans.", "parameters": {"type": "OBJECT", "properties": {"category": {"type": "STRING"}, "key": {"type": "STRING"}, "value": {"type": "STRING"}}, "required": ["category", "key", "value"]}},
]



def _split_sentences(text: str) -> tuple[list[str], str]:
    """
    Split text into complete sentences and a remaining incomplete fragment.
    Returns (complete_sentences, remainder).
    """
    import re
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
            title = re.sub(r"—\s*\S+$", "", title).strip()        # strip source
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
        """Speak text via ElevenLabs TTS (non-blocking)."""
        if not text:
            return
        self.ui.write_log(f"Jarvis: {text[:120]}")
        self._tts.speak(text)

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self._tts.speak(f"Sir, {tool_name} encountered an error. {short}")

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

            elif tool_name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
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
                self._tts.speak("Goodbye, sir.")

                def _shutdown():
                    import time, sys, os
                    time.sleep(2)
                    os._exit(0)

                threading.Thread(target=_shutdown, daemon=True).start()
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
        - Uses meta/llama-3.3-70b-instruct by default (fast, ~1-2s TTFT)
        - Switches to Nemotron+thinking only when boss explicitly requests deep analysis
        - Boss can cancel deep analysis mode at any time
        - System prompt cached and refreshed every 30 turns (not rebuilt every call)
        """
        import re as _re
        import json as _json
        from datetime import datetime as _dt

        client = _make_client()
        loop   = asyncio.get_event_loop()

        conversation      = []
        full_out_log      = []
        deep_mode         = False   # True = use Nemotron+thinking for this turn
        _deep_persistent  = False   # True = stay in deep mode until cancelled
        _sys_cache        = None    # cached (system_str, turn_count)
        _sys_refresh      = 30      # rebuild system prompt every N turns
        _turn_count       = 0

        # Keywords that trigger deep analysis mode
        _DEEP_ON = {
            "deep analysis", "analyze deeply", "think carefully", "think step by step",
            "detailed reasoning", "analyze this thoroughly", "use deep thinking",
            "enable deep analysis", "turn on deep analysis", "deep mode on",
        }
        # Keywords that cancel deep analysis
        _DEEP_OFF = {
            "cancel deep analysis", "stop deep analysis", "disable deep analysis",
            "turn off deep analysis", "deep mode off", "normal mode", "fast mode",
            "stop thinking deeply", "cancel deep mode",
        }

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
            clean = _re.sub(
                r"STARTUP BRIEFING.*?(?=REAL-TIME DATA|RULES:|$)",
                "", base_prompt, flags=_re.DOTALL
            ).strip()
            parts = [time_ctx]
            if mem_str:
                parts.append(mem_str)
            parts.append(clean)
            return "\n".join(parts)

        # Build system prompt once at startup
        _sys_cache = _build_sys()

        # Build OpenAI-format tool list once — never changes at runtime
        tools_oai = []
        for td in TOOL_DECLARATIONS:
            props       = td.get("parameters", {}).get("properties", {})
            clean_props = {}
            for k, v in props.items():
                ptype = v.get("type", "string").lower()
                if ptype not in ("object", "array", "integer", "number", "boolean"):
                    ptype = "string"
                prop = {**v, "type": ptype}
                # Fix nested items type for array properties (Groq strict validation)
                if ptype == "array" and "items" in prop:
                    nested = prop["items"]
                    if isinstance(nested, dict) and "type" in nested:
                        itype = nested["type"].lower()
                        if itype not in ("object", "array", "integer", "number", "boolean", "null"):
                            itype = "string"
                        prop["items"] = {**nested, "type": itype}
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
            Primary: Groq (sub-1s latency, free, OpenAI-compatible).
            Fallback: NVIDIA NIM (if Groq key missing or rate-limited).
            Deep mode: NVIDIA Nemotron with thinking (only when use_deep=True).
            """
            cfg_data = _json.load(open(API_CONFIG_PATH, encoding="utf-8"))

            groq_key   = cfg_data.get("groq_api_key",    "").strip()
            groq_model = cfg_data.get("groq_model",       "llama-3.3-70b-versatile")
            fast_model = cfg_data.get("nvidia_model",     "meta/llama-3.3-70b-instruct")
            deep_model = cfg_data.get("nvidia_model_deep", fast_model)

            # Decide which client + model to use
            use_groq = (
                groq_key
                and groq_key != "YOUR_GROQ_KEY_HERE"
                and not use_deep   # deep mode always uses NVIDIA Nemotron
            )

            if use_groq:
                api_client = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=groq_key,
                )
                model = groq_model
                extra = {}
                temperature = 0.4
                top_p       = 1.0
            else:
                api_client  = client   # existing NVIDIA client
                model       = deep_model if use_deep else fast_model
                is_nemotron = "nemotron" in model.lower()
                extra = {}
                if is_nemotron:
                    extra = {
                        "extra_body": {
                            "chat_template_kwargs": {"enable_thinking": True},
                            "reasoning_budget": 4096,
                        }
                    }
                temperature = 1.0 if is_nemotron else 0.4
                top_p       = 0.95 if is_nemotron else 1.0

            # Use a state dict so inner functions can mutate without nonlocal
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
                    state["buf"]  += delta.content
                    state["text"] += delta.content
                    sentences = _re.split(r"(?<=[.!?])\s+", state["buf"])
                    if len(sentences) > 1:
                        to_speak = " ".join(sentences[:-1]).strip()
                        if to_speak:
                            self.speak(to_speak)
                        state["buf"] = sentences[-1]

            # Create the stream — this was missing after the patch
            try:
                stream = api_client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools_oai,
                    tool_choice="auto",
                    max_tokens=400,
                    temperature=temperature,
                    top_p=top_p,
                    stream=True,
                    **extra,
                )
            except Exception as e:
                if use_groq and ("429" in str(e) or "rate" in str(e).lower()):
                    print("[JARVIS] Groq rate limit — falling back to NVIDIA")
                    api_client = client
                    model      = fast_model
                    stream = api_client.chat.completions.create(
                        model=model, messages=messages, tools=tools_oai,
                        tool_choice="auto", max_tokens=400,
                        temperature=0.4, stream=True,
                    )
                else:
                    raise

            try:
                for chunk in stream:
                    if chunk.choices:
                        _process_chunk(chunk.choices[0].delta)
            except Exception as _se:
                _se_s = str(_se).lower()
                if "failed_generation" in _se_s or "failed to call a function" in _se_s:
                    print("[JARVIS] Tool generation failed — retrying without tools")
                    state["buf"] = ""; state["text"] = ""; state["tc"] = {}
                    plain = api_client.chat.completions.create(
                        model=model, messages=messages,
                        max_tokens=300, temperature=temperature, stream=True,
                    )
                    for chunk in plain:
                        if chunk.choices:
                            _process_chunk(chunk.choices[0].delta)
                else:
                    raise

            buf       = state["buf"]
            full_text = state["text"]
            tc_raw    = state["tc"]
            if buf.strip():
                self.speak(buf.strip())

            tc_list = [tc_raw[i] for i in sorted(tc_raw) if tc_raw[i]["name"]]
            return full_text.strip(), tc_list

        try:
            while True:
                await asyncio.sleep(0.02)

                if not self.ui.text_input_ready:
                    continue

                user_text = self.ui.get_text_input()
                if not user_text or len(user_text.strip()) <= 1:
                    continue

                user_text = user_text.strip()
                ut_lower  = user_text.lower()
                print(f"[JARVIS] User: {user_text}")
                self.ui.write_log(f"You: {user_text}")

                # ── Deep analysis mode control ─────────────────────────────
                if any(kw in ut_lower for kw in _DEEP_OFF):
                    _deep_persistent = False
                    self.speak("Deep analysis mode disabled, boss. Back to fast mode.")
                    self.ui.write_log("Jarvis: Deep analysis mode OFF")
                    continue

                if any(kw in ut_lower for kw in _DEEP_ON):
                    _deep_persistent = True
                    self.speak("Deep analysis mode enabled, boss. I will think carefully.")
                    self.ui.write_log("Jarvis: Deep analysis mode ON")
                    # Don't continue — also process the message if there's more to it
                    if len(user_text.split()) <= 5:
                        # Pure mode-switch command, nothing else to process
                        continue

                use_deep = _deep_persistent
                # ──────────────────────────────────────────────────────────

                self.ui.set_state("THINKING")
                conversation.append({"role": "user", "content": user_text})

                # Refresh system prompt cache periodically
                _turn_count += 1
                if _turn_count % _sys_refresh == 0:
                    _sys_cache = _build_sys()

                try:
                    while True:
                        messages_snap = [
                            {"role": "system", "content": _sys_cache}
                        ] + list(conversation)

                        final_text, tool_calls = await loop.run_in_executor(
                            None,
                            lambda: _call_api(messages_snap, use_deep)
                        )

                        if not tool_calls:
                            if final_text:
                                full_out_log.append(final_text)
                                conversation.append({"role": "assistant", "content": final_text})
                            break

                        if final_text:
                            full_out_log.append(final_text)

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

                    if len(conversation) > 24:
                        conversation = conversation[-24:]

                except Exception as e:
                    err_str = str(e)
                    print(f"[JARVIS] API error: {err_str}")
                    traceback.print_exc()
                    if "401" in err_str or "authentication" in err_str.lower():
                        msg = "Invalid NVIDIA API key, boss. Please update config/api_keys.json."
                    elif "429" in err_str or "rate" in err_str.lower():
                        msg = "Rate limit hit, boss. Give me a moment."
                    else:
                        msg = f"I hit an error, boss: {err_str[:100]}"
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

        # Fetch news from multiple RSS feeds — diverse, real-time, no DDG needed
        def _fast_news():
            import xml.etree.ElementTree as _ET
            import requests as _req
            import concurrent.futures as _cf

            _HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            _FEEDS = [
                ("BBC",      "https://feeds.bbci.co.uk/news/world/rss.xml"),
                ("AJazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
                ("Guardian", "https://www.theguardian.com/world/rss"),
                ("Euronews", "https://feeds.feedburner.com/euronews/en/news/"),
                ("NPR",      "https://feeds.npr.org/1001/rss.xml"),
            ]

            def _fetch_one(name_url):
                name, url = name_url
                try:
                    resp  = _req.get(url, timeout=4, headers=_HDR)
                    root  = _ET.fromstring(resp.content)
                    items = root.findall("./channel/item/title") or root.findall(".//item/title")
                    for item in items:
                        t = (item.text or "").strip()
                        if len(t) > 20:
                            return t   # return first good headline from this feed
                except Exception:
                    pass
                return None

            # Fetch all feeds in parallel — takes only as long as the slowest successful one
            headlines = []
            with _cf.ThreadPoolExecutor(max_workers=5) as ex:
                futures = {ex.submit(_fetch_one, f): f[0] for f in _FEEDS}
                for fut in _cf.as_completed(futures, timeout=6):
                    result = fut.result()
                    if result and result not in headlines:
                        headlines.append(result)
                    if len(headlines) >= 3:
                        break

            return headlines[:3]

        # Start fetch immediately — runs while greeting is being spoken by ElevenLabs
        news_future = asyncio.ensure_future(
            loop.run_in_executor(None, _fast_news)
        )

        # Collect result — should be ready by the time greeting finishes
        try:
            headlines = await asyncio.wait_for(news_future, timeout=7.0)
        except Exception:
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
            {"role": "user",      "content": "[STARTUP] Startup briefing complete."},
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
        Continuous microphone listener using ElevenLabs Scribe v2 STT.
        Far better accent/dialect recognition than Google STT.
        Records a phrase via pyaudio + SpeechRecognition's AudioData,
        sends raw WAV bytes to ElevenLabs, gets text back.
        """
        import json as _json
        import io
        import wave
        # pyrefly: ignore [missing-import]
        import speech_recognition as sr
        # pyrefly: ignore [missing-import]
        from elevenlabs import ElevenLabs as _EL

        loop = asyncio.get_event_loop()

        # Load ElevenLabs key
        try:
            with open(API_CONFIG_PATH, "r", encoding="utf-8") as _f:
                _cfg = _json.load(_f)
            el_key = _cfg.get("elevenlabs_api_key", "").strip()
        except Exception:
            el_key = ""

        if not el_key:
            print("[JARVIS] ⚠️ No ElevenLabs key — falling back to Google STT")
            await self._listen_audio_google()
            return

        el_client = _EL(api_key=el_key)
        rec       = sr.Recognizer()
        rec.energy_threshold         = 300    # start low; calibration will raise it
        rec.dynamic_energy_threshold = True   # adapt to environment continuously
        rec.pause_threshold          = 0.8
        rec.non_speaking_duration    = 0.5

        # Short filler words that are pure mic noise — ignore these
        # Note: "yes", "no", "ok" are intentionally NOT here — they're valid responses
        _NOISE_PHRASES = {
            "", "uh", "um", "hmm", "hm", "ah", "mm", "mmm", "mhm",
            "uh huh", "the", "a",
        }

        print("[JARVIS] ElevenLabs Scribe STT started")
        self.ui.write_log("SYS: Microphone active (ElevenLabs Scribe) — speak to JARVIS.")

        # Boost mic volume to max in Windows so it picks up voice clearly
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            mic_dev = AudioUtilities.GetMicrophone()
            if mic_dev:
                iface = mic_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                mic_vol = cast(iface, POINTER(IAudioEndpointVolume))
                mic_vol.SetMasterVolumeLevelScalar(1.0, None)
                print(f"[JARVIS] Mic volume boosted to 100%")
        except Exception:
            pass  # non-critical

        def _transcribe_loop():
            """
            Keep microphone stream open continuously.
            Re-opening every phrase causes device-busy errors and degrades accuracy.
            """
            import time as _time
            try:
                # List available mics at startup for diagnostics
                mic_names = sr.Microphone.list_microphone_names()
                print(f"[JARVIS] Available microphones ({len(mic_names)}):")
                for i, name in enumerate(mic_names):
                    print(f"  [{i}] {name}")

                # Allow config to override mic index (add "mic_index": N to api_keys.json)
                try:
                    import json as _json2
                    _cfg2 = _json2.load(open(API_CONFIG_PATH, encoding="utf-8"))
                    _mic_idx = _cfg2.get("mic_index", None)
                    if _mic_idx is not None:
                        print(f"[JARVIS] Using mic index {_mic_idx}: {mic_names[_mic_idx] if _mic_idx < len(mic_names) else 'unknown'}")
                except Exception:
                    _mic_idx = None

                mic = sr.Microphone(device_index=_mic_idx)

                # Open once, keep open for entire session
                with mic as source:
                    rec.adjust_for_ambient_noise(source, duration=1.5)
                    # Use calibrated threshold + small buffer — don't multiply by 2 for quiet mics
                    rec.energy_threshold = max(50, rec.energy_threshold + 30)
                    print(f"[JARVIS] Mic calibrated — threshold: {rec.energy_threshold:.0f}")

                    while True:
                        # Pause while muted or speaking (avoids echo)
                        if self.ui.muted or self._is_speaking:
                            _time.sleep(0.15)
                            continue

                        try:
                            audio_data = rec.listen(source, timeout=5, phrase_time_limit=15)

                            # Convert to WAV for ElevenLabs Scribe
                            wav_buf = io.BytesIO()
                            with wave.open(wav_buf, "wb") as wf:
                                wf.setnchannels(1)
                                wf.setsampwidth(audio_data.sample_width)
                                wf.setframerate(audio_data.sample_rate)
                                wf.writeframes(audio_data.frame_data)

                            wav_buf.seek(0)
                            wav_buf.name = "speech.wav"
                            result = el_client.speech_to_text.convert(
                                file=wav_buf,
                                model_id="scribe_v2",
                                language_code="eng",
                            )
                            text = (result.text or "").strip()

                            # Reject only pure mic noise mishears
                            text_lower = text.lower().rstrip(".,!? ")
                            if text and len(text) > 1 and text_lower not in _NOISE_PHRASES:
                                print(f"[JARVIS] Heard: {text}")
                                self.ui._text_queue.put(text)
                            elif text:
                                print(f"[JARVIS] Noise filtered: {text!r}")

                        except sr.WaitTimeoutError:
                            pass  # silence — normal, keep listening
                        except sr.UnknownValueError:
                            pass  # unintelligible audio — keep listening
                        except Exception as e:
                            err_s = str(e).lower()
                            if "quota_exceeded" in err_s or "0 credits" in err_s or "quota exceeded" in err_s:
                                print("[JARVIS] ElevenLabs Scribe quota exhausted — falling back to Google STT")
                                self.ui.write_log("SYS: Scribe quota used up — switching to Google STT")
                                # Exit this loop so Google STT takes over
                                return
                            print(f"[JARVIS] Scribe error: {str(e)[:80]}")
                            _time.sleep(0.5)

            except Exception as e:
                print(f"[JARVIS] Mic init failed: {e}")
                self.ui.write_log(f"SYS: Mic error — {e}")

        await loop.run_in_executor(None, _transcribe_loop)
        # If we get here, Scribe failed/quota exceeded — use Google STT
        print("[JARVIS] Falling back to Google STT")
        await self._listen_audio_google()

    async def _listen_audio_google(self):
        """Fallback: Google STT when ElevenLabs key is absent."""
        # pyrefly: ignore [missing-import]
        import speech_recognition as sr
        import time as _time

        loop = asyncio.get_event_loop()
        rec  = sr.Recognizer()
        rec.energy_threshold         = 300    # start low; calibration raises it
        rec.dynamic_energy_threshold = True   # adapt continuously
        rec.pause_threshold          = 0.8
        rec.non_speaking_duration    = 0.5

        _NOISE = {
            "", "uh", "um", "hmm", "hm", "ah", "mm", "mmm", "mhm", "uh huh", "the", "a",
        }

        print("[JARVIS] Google STT fallback started")

        def _loop():
            try:
                # Show available mics
                mic_names = sr.Microphone.list_microphone_names()
                print(f"[JARVIS] Google STT — {len(mic_names)} mic(s) found. Using default.")
                mic = sr.Microphone()
                with mic as source:
                    rec.adjust_for_ambient_noise(source, duration=1.5)
                    rec.energy_threshold = max(50, rec.energy_threshold + 30)
                    print(f"[JARVIS] Google STT calibrated — threshold: {rec.energy_threshold:.0f}")

                    while True:
                        if self.ui.muted or self._is_speaking:
                            _time.sleep(0.2)
                            continue
                        try:
                            audio = rec.listen(source, timeout=5, phrase_time_limit=15)
                            text  = rec.recognize_google(audio).strip()
                            tl    = text.lower().rstrip(".,!? ")
                            if text and len(text) > 1 and tl not in _NOISE:
                                self.ui._text_queue.put(text)
                            elif text:
                                print(f"[JARVIS] Noise filtered: {text!r}")
                        except (sr.WaitTimeoutError, sr.UnknownValueError):
                            pass
                        except Exception:
                            _time.sleep(1)
            except Exception as e:
                print(f"[JARVIS] Google STT init failed: {e}")

        await loop.run_in_executor(None, _loop)


def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()


if __name__ == "__main__":
    main()
