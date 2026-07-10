# J.A.R.V.I.S — MARK XXXIX

```
       _       _      _____  __   __ _____  _____
      | |     / \    |  __ \|  \ / /|_   _|/ ____|
      | |    / _ \   | |__) |   V /   | | | (___
  _   | |   / ___ \  |  _  /| |\ |   | |  \___ \
 | |__| |  / /   \ \ | | \ \| | \ \ _| |_ ____) |
  \____/  /_/     \_\|_|  \_\_|  \_\_____|_____/
```

**JARVIS** is a fully local AI assistant for Windows.  
Powered by **Groq** (Llama 4 Scout, ultra-fast) for reasoning, **ElevenLabs** for voice, and **ElevenLabs Scribe** for speech input.  
She greets you at startup with live world news, controls your entire PC, searches the web in real time, opens any installed app, and executes complex tasks — all through natural conversation.

---

## Features

| Capability | Details |
|---|---|
| **Voice Input** | ElevenLabs Scribe v2 STT — excellent accent/dialect recognition, auto language detection |
| **Voice Output** | ElevenLabs TTS (ElevenFlash v2.5) — natural streaming speech, SAPI fallback |
| **AI Reasoning** | Groq `meta-llama/llama-4-scout-17b-16e-instruct` — 460+ tok/s, temperature=0 |
| **Deep Analysis** | NVIDIA NIM `nvidia/llama-3.3-nemotron-super-49b-v1` — activate with "deep analysis" |
| **App Launcher** | Opens ANY installed app: Win32, Windows Store (UWP), system built-ins |
| **App Control** | Close, minimize, maximize, switch, type, click, search inside any app |
| **Browser Control** | Open URLs, navigate, scroll, search — uses your real default browser (Edge) |
| **Screen Vision** | NVIDIA NIM vision model analyzes your screen or webcam in real time |
| **Real-Time Web** | DuckDuckGo + RSS feeds — live news, prices, events, weather |
| **PC Control** | Volume, brightness, WiFi, dark mode, screenshots, shutdown, restart |
| **File System** | Read, write, create, delete, move, search files and folders |
| **File Processing** | PDFs, images, video, audio, code, CSV, JSON, archives, PPTX |
| **Messaging** | WhatsApp, Telegram, Instagram via browser automation |
| **Reminders** | Windows Task Scheduler integration |
| **YouTube** | Play, summarize, trending, video info |
| **Flight Search** | Google Flights via browser automation |
| **Games** | Steam & Epic: update, install, schedule |
| **Code** | Write, run, explain, review, fix code in any language |
| **Memory** | Persistent long-term memory across sessions |
| **Startup Briefing** | Greets you, states date/time, delivers live world news headlines |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   JARVIS UI (PyQt6)                       │
│   HUD orb · Log panel · System metrics · File drop       │
│   Compact mode (orb only, top-center) ↔ Full mode        │
└───────────────────────────┬──────────────────────────────┘
                            │
             ┌──────────────▼──────────────┐
             │       main.py (core)         │
             │   JarvisLive async loop       │
             └──┬────────────┬──────────────┘
                │            │
     ┌──────────▼──┐  ┌──────▼──────────────────┐
     │ ElevenLabs  │  │  Groq (primary)           │
     │ Scribe STT  │  │  llama-4-scout-17b        │
     │ sounddevice │  │  460+ tok/s, temp=0       │
     └──────────┬──┘  └──────┬──────────────────┘
                │            │
            ┌───▼────────────▼───┐
            │   Tool Dispatcher   │
            └────────┬────────────┘
                     │
   ┌─────────────────┼──────────────────────┐
   ▼                 ▼                       ▼
open_app      computer_control         web_search
browser_ctrl  computer_settings        file_controller
screen_proc   send_message             youtube_video
dev_agent     code_helper              ... 19 tools total
```

---

## Requirements

- **OS**: Windows 10 / 11 (macOS/Linux partial support)
- **Python**: 3.11+ (3.12 recommended)
- **Microphone**: Required for voice input
- **Internet**: Required for Groq API, NVIDIA NIM, and web search
- **API Keys**: Groq (free) + NVIDIA NIM (free) + ElevenLabs (free tier)

---

## Installation

### 1. Clone or download

```bash
git clone https://github.com/writtenscars2-art/TestJarvis.git
cd TestJarvis/Mark-XXXIX-OR-main
```

### 2. Create virtual environment (recommended)

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your API keys

Edit `config/api_keys.json` (copy from `config/api_keys.example.json`):

```json
{
    "groq_api_key":         "gsk_...",
    "groq_model":           "meta-llama/llama-4-scout-17b-16e-instruct",
    "nvidia_api_key":       "nvapi-...",
    "nvidia_model":         "meta/llama-3.3-70b-instruct",
    "nvidia_model_deep":    "nvidia/llama-3.3-nemotron-super-49b-v1",
    "elevenlabs_api_key":   "sk_...",
    "elevenlabs_voice_id":  "YOUR_VOICE_ID",
    "mic_index":            1,
    "default_browser":      "msedge",
    "os_system":            "windows",
    "camera_index":         0
}
```

### 5. Run JARVIS

```bash
python main.py
```

Or double-click the **JARVIS** shortcut on your Desktop (run `setup_shortcut.py` once to create it).

---

## API Keys Setup

### Groq (Free — primary reasoning engine)
1. Go to [https://console.groq.com](https://console.groq.com)
2. Sign up → **API Keys** → **Create API Key**
3. Copy the key starting with `gsk_`
4. Paste as `groq_api_key` in `config/api_keys.json`

### NVIDIA NIM (Free — vision + deep analysis)
1. Go to [https://build.nvidia.com](https://build.nvidia.com)
2. Sign up → **API Keys** → **Generate Key**
3. Copy the key starting with `nvapi-`
4. Paste as `nvidia_api_key` in `config/api_keys.json`

### ElevenLabs (Free tier)
1. Go to [https://elevenlabs.io](https://elevenlabs.io)
2. Sign up → **Profile** → **API Keys** → copy your key
3. Go to **Voices** → pick a voice → copy the **Voice ID**
4. Paste both into `config/api_keys.json`

---

## Desktop Shortcut

Run once to create the Desktop shortcut:

```bash
python setup_shortcut.py
```

This creates `JARVIS.lnk` on your Desktop. Double-click it to launch.  
The shortcut uses `jarvis_launcher.py` which hides the console window automatically.

**Single-instance guard**: If JARVIS is already running, clicking the shortcut again does nothing (prevents duplicate instances talking to each other).

---

## How to Use

### Startup
Double-click **JARVIS** on your Desktop. JARVIS will:
1. Say **"Greetings boss, welcome back"** + current date and time
2. Deliver a **live 2-3 story world news briefing**
3. Ask if you want to open World Monitor → say **"yes"** to open `worldmonitor.app/dashboard`

### Interacting
- **Speak** naturally into your microphone — JARVIS listens continuously
- **Type** in the input box at the bottom and press Enter
- **Mute** the mic with **F4**
- **Compact mode**: Click the **📌 pin button** → JARVIS shrinks to orb-only at top-center
- **Expand**: Click the **red ✕** on the orb → full UI restores

### Deep Analysis Mode
- Say **"deep analysis"** → activates NVIDIA Nemotron (slower but more thorough)
- Say **"fast mode"** or **"cancel deep analysis"** → back to Groq

### Keyboard Shortcuts
| Key | Action |
|-----|--------|
| F4  | Toggle microphone mute |
| F11 | Toggle fullscreen |
| F12 | Toggle compact/full mode |

---

## Voice Commands

JARVIS understands natural language. Examples:

```
"Open Spotify"
"Open WhatsApp"
"What's the weather in Lagos?"
"Search the latest AI news"
"Take a screenshot and describe what you see"
"Set a reminder for tomorrow at 9 AM — team meeting"
"List my capabilities in Notepad"
"Write a Python script that reads a CSV" 
"Update all my Steam games"
"Play lofi hip hop on YouTube"
"Find flights from Lagos to London next Friday"
"Send a WhatsApp message to John saying I'll be late"
"What's Bitcoin's price right now?"
"Close Spotify"
"Minimize Chrome"
"What apps are open?"
"Turn up the volume"
"Take a screenshot"
"Shut down JARVIS" / "Goodbye"
```

---

## Available Tools

| Tool | What it does |
|------|-------------|
| `open_app` | Launch ANY installed app (Win32, Store, UWP, built-in) |
| `browser_control` | Open URLs, navigate, search, scroll in your default browser |
| `computer_settings` | Volume, brightness, WiFi, dark mode, screenshot, device info |
| `computer_control` | Mouse, keyboard, hotkeys, app control (close/min/max/list), in-app actions |
| `web_search` | Live DuckDuckGo + RSS news search |
| `weather_report` | Real-time weather via wttr.in |
| `screen_process` | AI vision — analyze screen or webcam (NVIDIA NIM) |
| `file_controller` | List, read, write, move, delete, find files |
| `file_processor` | Process images, PDFs, video, audio, code, data files |
| `youtube_video` | Play, summarize, trending, video info |
| `send_message` | WhatsApp, Telegram, Instagram messages |
| `reminder` | Windows Task Scheduler reminders |
| `code_helper` | Write, edit, explain, run, debug code |
| `dev_agent` | Build complete multi-file projects from description |
| `agent_task` | Multi-step complex task planner and executor |
| `flight_finder` | Search Google Flights via browser |
| `game_updater` | Steam & Epic: update, install, list, schedule |
| `desktop_control` | Wallpaper, organize, list desktop |
| `save_memory` | Save personal facts to long-term memory |

---

## Configuration (`config/api_keys.json`)

| Field | Required | Description |
|-------|----------|-------------|
| `groq_api_key` | Yes | Groq API key — primary fast reasoning |
| `groq_model` | Yes | Groq model ID (default: llama-4-scout) |
| `nvidia_api_key` | Yes | NVIDIA NIM key — vision + deep mode |
| `nvidia_model` | Yes | Fast NVIDIA model |
| `nvidia_model_deep` | Yes | Deep reasoning model (Nemotron) |
| `elevenlabs_api_key` | Yes | ElevenLabs voice key |
| `elevenlabs_voice_id` | Yes | ElevenLabs voice ID for TTS |
| `mic_index` | No | Microphone device index (default: system default) |
| `default_browser` | No | `msedge`, `chrome`, `firefox` (default: msedge) |
| `os_system` | No | `windows` / `mac` / `linux` |
| `camera_index` | No | Webcam device index (default: 0) |

---

## Project Structure

```
Mark-XXXIX-OR-main/
├── main.py                 # Core async loop, tool dispatch, STT/TTS integration
├── ui.py                   # PyQt6 HUD — orb, panels, compact/full mode
├── tts.py                  # ElevenLabs TTS + SAPI fallback
├── claude_client.py        # NVIDIA NIM / Claude API wrapper
├── gemini_client.py        # Compatibility shim
├── jarvis_launcher.py      # Console-hiding launcher for Desktop shortcut
├── setup_shortcut.py       # Creates JARVIS.lnk on Desktop
├── launch_jarvis.vbs       # Legacy VBS launcher
├── requirements.txt        # Python dependencies
├── icon.ico                # Application icon
│
├── config/
│   ├── api_keys.json       # API keys and settings (gitignored)
│   └── api_keys.example.json
│
├── core/
│   └── prompt.txt          # JARVIS system prompt
│
├── memory/
│   ├── memory_manager.py   # Long-term memory
│   └── config_manager.py
│
├── agent/
│   ├── planner.py          # Multi-step task planner
│   ├── executor.py         # Task executor
│   ├── error_handler.py
│   └── task_queue.py
│
└── actions/
    ├── open_app.py          # App launcher (Get-StartApps + Store IDs + PATH)
    ├── browser_control.py   # Real browser control via subprocess + pyautogui
    ├── computer_settings.py # System controls
    ├── computer_control.py  # Mouse/keyboard + app control + do_in_app
    ├── screen_processor.py  # NVIDIA NIM vision
    ├── web_search.py        # DuckDuckGo + RSS
    ├── weather_report.py    # wttr.in
    ├── file_controller.py
    ├── file_processor.py
    ├── code_helper.py
    ├── dev_agent.py
    ├── youtube_video.py
    ├── send_message.py
    ├── reminder.py
    ├── flight_finder.py
    ├── game_updater.py
    └── desktop.py
```

---

## Troubleshooting

**Voice not working**
- Check mic is not muted (F4)
- Verify `elevenlabs_api_key` and `elevenlabs_voice_id` in config
- Check Windows microphone permissions: Settings → Privacy → Microphone

**JARVIS can't open an app**
- Make sure the app is installed
- Try the exact app name as it appears in Start Menu
- Check console for `[open_app]` messages to see what was tried

**"Module not found" error**
```bash
pip install -r requirements.txt
```

**Double instances running / talking to each other**
- The single-instance guard should prevent this
- If it happens, kill all `python.exe` processes in Task Manager, then relaunch

**Groq model errors**
- Check your Groq API key at [console.groq.com](https://console.groq.com)
- The model `meta-llama/llama-4-scout-17b-16e-instruct` must be available on your account

---

## License

Personal and non-commercial use only.  
Licensed under **Creative Commons BY-NC 4.0**.

---

*MARK XXXIX — CLASSIFIED*
