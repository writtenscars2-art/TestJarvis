# J.A.R.V.I.S — MARK XXXIX

```
       _       _      _____  __   __ _____  _____
      | |     / \    |  __ \|  \ / /|_   _|/ ____|
      | |    / _ \   | |__) |   V /   | | | (___
  _   | |   / ___ \  |  _  /| |\ |   | |  \___ \
 | |__| |  / /   \ \ | | \ \| | \ \ _| |_ ____) |
  \____/  /_/     \_\|_|  \_\_|  \_\_____|_____/
```

**JARVIS** is a fully local AI assistant powered by **NVIDIA NIM** for reasoning, **ElevenLabs** for voice output, and **ElevenLabs Scribe** for voice input. She greets you on startup, briefs you on world news, controls your PC, searches the web in real time, and executes complex multi-step tasks — all through natural conversation.

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Installation](#installation)
- [API Keys Setup](#api-keys-setup)
- [Desktop Shortcut](#desktop-shortcut)
- [How to Use](#how-to-use)
- [Voice Commands](#voice-commands)
- [Available Tools](#available-tools)
- [Configuration](#configuration)
- [Project Structure](#project-structure)
- [License](#license)

---

## Features

| Capability | Details |
|---|---|
| **Voice Input** | ElevenLabs Scribe v2 STT — excellent accent/dialect recognition |
| **Voice Output** | ElevenLabs TTS — natural, low-latency streaming speech |
| **AI Reasoning** | NVIDIA NIM (`meta/llama-3.3-70b-instruct`) — fast, free tier |
| **Real-Time Web** | DuckDuckGo live search + DDG News — no API key needed |
| **Screen Vision** | NVIDIA NIM vision model analyzes your screen or webcam |
| **Memory** | Persistent long-term memory across sessions |
| **Startup Briefing** | Greets you, states date/time, delivers live world news |
| **PC Control** | Volume, brightness, apps, files, browser, keyboard, mouse |
| **Task Automation** | Multi-step agent planner for complex goals |
| **File Processing** | PDFs, images, video, audio, code, CSV, JSON, archives |
| **YouTube** | Play, summarize, trending, video info |
| **Flight Search** | Google Flights via browser automation |
| **Game Updates** | Steam & Epic Games — update, install, schedule |
| **Reminders** | Windows Task Scheduler integration |
| **Messaging** | WhatsApp, Telegram (via browser automation) |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    JARVIS UI (PyQt6)                 │
│  HUD canvas · Log panel · File drop · Voice button  │
└──────────────────────┬──────────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │     main.py (core)      │
          │  JarvisLive async loop  │
          └──┬──────────┬───────────┘
             │          │
   ┌──────────▼──┐  ┌───▼──────────────────┐
   │  ElevenLabs │  │   NVIDIA NIM          │
   │  Scribe STT │  │   llama-3.3-70b       │
   │  (mic input)│  │   (reasoning+tools)   │
   └──────────┬──┘  └───┬──────────────────┘
              │          │
          ┌───▼──────────▼───┐
          │   Tool Dispatcher │
          └─────────┬─────────┘
                    │
    ┌───────────────┼───────────────────┐
    ▼               ▼                   ▼
web_search    file_controller    computer_settings
browser_ctrl  screen_processor   agent_task
dev_agent     youtube_video      flight_finder
...and 15 more tools
```

---

## Requirements

- **OS**: Windows 10 / 11 (macOS and Linux partially supported)
- **Python**: 3.11 or later (3.12 recommended)
- **Microphone**: Required for voice input
- **Internet**: Required for NVIDIA NIM API and web search
- **API Keys**: NVIDIA NIM + ElevenLabs (both have free tiers)

---

## Installation

### 1. Clone or download the project

```bash
git clone https://github.com/writtenscars2-art/Mark-XXXIX-OR-main--1-.git
cd Mark-XXXIX-OR-main--1-

cd Mark-XXXIX-OR-main
```

Or download and extract the ZIP, then open a terminal in the project folder.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browsers (required for browser control)

```bash
python -m playwright install chromium
```

### 4. Add your API keys

Edit `config/api_keys.json`:

```json
{
    "nvidia_api_key":       "nvapi-...",
    "elevenlabs_api_key":   "sk_...",
    "elevenlabs_voice_id":  "YOUR_VOICE_ID",
    "os_system":            "windows",
    "camera_index":         0
}
```

### 5. Run JARVIS

```bash
python main.py
```

---

## API Keys Setup

### NVIDIA NIM (Free)
1. Go to [https://build.nvidia.com](https://build.nvidia.com)
2. Sign up / log in
3. Click your profile → **API Keys** → **Generate API Key**
4. Copy the key starting with `nvapi-`
5. Paste into `config/api_keys.json` as `nvidia_api_key`

### ElevenLabs (Free tier available)
1. Go to [https://elevenlabs.io](https://elevenlabs.io)
2. Sign up / log in
3. Go to **Profile** → **API Keys** → copy your key
4. Go to **Voices** → pick a voice → copy the **Voice ID**
5. Paste both into `config/api_keys.json`

> The setup overlay in the JARVIS UI will also let you enter keys on first launch. Both `nvapi-` and `sk-ant-` (Anthropic) key formats are accepted.

---

## Desktop Shortcut

### Automatic (recommended)

Run this command once in PowerShell from the project folder:

```powershell
$desktop  = [System.Environment]::GetFolderPath("Desktop")
$py       = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\pythonw.exe"
$mainPy   = "$PWD\main.py"
$work     = "$PWD"
$icon     = "$PWD\icon.ico"

$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$desktop\JARVIS.lnk")
$sc.TargetPath       = $py
$sc.Arguments        = "`"$mainPy`""
$sc.WorkingDirectory = $work
$sc.IconLocation     = "$icon,0"
$sc.Description      = "J.A.R.V.I.S - NVIDIA NIM + ElevenLabs"
$sc.WindowStyle      = 7
$sc.Save()
Write-Host "Shortcut created on Desktop."
```

> **Note:** Replace `Python312` with your actual Python version folder if different (e.g. `Python311`).  
> `pythonw.exe` is used instead of `python.exe` so no console window appears when launching.

### Manual

1. Right-click Desktop → **New → Shortcut**
2. Target: `C:\Users\YOUR_NAME\AppData\Local\Programs\Python\Python312\pythonw.exe`
3. Arguments: `"C:\path\to\Mark-XXXIX\main.py"`
4. Start in: `C:\path\to\Mark-XXXIX`
5. Change Icon: browse to `icon.ico` in the project folder

---

## How to Use

### Startup
Double-click the JARVIS shortcut (or run `python main.py`). JARVIS will:
1. Say **"Greetings boss, welcome back"** and state the current date and time
2. Deliver a **live 2-story world news briefing** from the web
3. Ask if you want to open the world monitor — **say "yes"** to open it + the dashboard, or just continue talking

### Interacting
- **Type** in the command input box at the bottom right and press Enter or click `▸`
- **Speak** naturally — JARVIS listens continuously (mute with **F4**)
- JARVIS replies via **ElevenLabs voice** and logs everything in the activity panel

### Keyboard Shortcuts
| Key | Action |
|-----|--------|
| F4 | Toggle microphone mute |
| F11 | Toggle fullscreen |
| Enter | Send typed command |

---

## Voice Commands

JARVIS understands natural language. Examples:

```
"Open Spotify"
"What's the weather in London?"
"Search the latest news about AI"
"Take a screenshot and describe what you see"
"Set a reminder for tomorrow at 9 AM — team meeting"
"Summarize this PDF" (after dropping a file)
"Update all my Steam games"
"Play lofi hip hop on YouTube"
"Find flights from Istanbul to London next Friday"
"Write a Python script that sorts a CSV by date"
"Send a WhatsApp message to John saying I'll be late"
"What's Bitcoin's price right now?"
"Shut down JARVIS" / "Goodbye"
```

---

## Available Tools

| Tool | What it does |
|------|-------------|
| `web_search` | Live DuckDuckGo web + news search |
| `browser_control` | Open URLs, click elements, fill forms, scrape text |
| `open_app` | Launch any installed app |
| `computer_settings` | Volume, brightness, WiFi, shutdown, screenshots |
| `computer_control` | Mouse, keyboard, hotkeys, screen element detection |
| `file_controller` | List, read, write, move, delete, find files |
| `file_processor` | Process images, PDFs, video, audio, code, data files |
| `screen_process` | Capture + analyze screen or webcam with AI vision |
| `code_helper` | Write, edit, explain, run, or debug code |
| `dev_agent` | Build complete multi-file projects from a description |
| `agent_task` | Plan and execute complex multi-step tasks |
| `weather_report` | Current weather for any city |
| `youtube_video` | Play, summarize, get info, trending videos |
| `send_message` | Send WhatsApp/Telegram messages |
| `reminder` | Set Windows Task Scheduler reminders |
| `flight_finder` | Search Google Flights via browser automation |
| `game_updater` | Steam & Epic: update, install, list, schedule |
| `desktop_control` | Wallpaper, organize, list, stats |
| `save_memory` | Silently save personal facts to long-term memory |
| `shutdown_jarvis` | Cleanly shut down the assistant |

---

## Configuration

All configuration lives in `config/api_keys.json`:

```json
{
    "nvidia_api_key":       "nvapi-...",
    "claude_api_key":       "sk-ant-... (optional fallback)",
    "elevenlabs_api_key":   "sk_...",
    "elevenlabs_voice_id":  "YOUR_VOICE_ID",
    "os_system":            "windows",
    "camera_index":         0
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `nvidia_api_key` | Yes | NVIDIA NIM key — primary AI engine |
| `claude_api_key` | No | Anthropic Claude — fallback if NIM unavailable |
| `elevenlabs_api_key` | Yes | ElevenLabs — voice output + Scribe STT |
| `elevenlabs_voice_id` | Yes | ElevenLabs voice ID for TTS |
| `os_system` | Yes | `windows` / `mac` / `linux` |
| `camera_index` | No | Webcam index (default: 0) |

---

## Project Structure

```
Mark-XXXIX/
├── main.py                 # Core async event loop, Claude tool dispatch
├── ui.py                   # PyQt6 HUD interface
├── tts.py                  # ElevenLabs TTS engine
├── claude_client.py        # NVIDIA NIM / Anthropic wrapper
├── or_client.py            # OpenRouter client (optional)
├── gemini_client.py        # Compatibility shim → claude_client
├── requirements.txt        # Python dependencies
├── icon.ico                # Application icon
├── launch_jarvis.vbs       # Silent launcher (no console)
├── qt.conf                 # Qt DPI settings
│
├── config/
│   └── api_keys.json       # API keys and settings
│
├── core/
│   └── prompt.txt          # JARVIS system prompt
│
├── memory/
│   ├── memory_manager.py   # Long-term memory read/write
│   ├── config_manager.py   # Config helpers
│   └── long_term.json      # Persistent memory store
│
├── agent/
│   ├── planner.py          # Multi-step task planner
│   ├── executor.py         # Step-by-step task executor
│   ├── error_handler.py    # Error recovery and retry logic
│   └── task_queue.py       # Priority task queue
│
└── actions/
    ├── web_search.py        # DuckDuckGo live search
    ├── browser_control.py   # Playwright browser automation
    ├── open_app.py          # App launcher
    ├── computer_settings.py # System controls
    ├── computer_control.py  # Mouse/keyboard control
    ├── screen_processor.py  # Vision (NVIDIA NIM)
    ├── file_controller.py   # File management
    ├── file_processor.py    # File analysis/conversion
    ├── code_helper.py       # Code assistant
    ├── dev_agent.py         # Project builder
    ├── weather_report.py    # Weather lookup
    ├── youtube_video.py     # YouTube control
    ├── send_message.py      # WhatsApp/Telegram
    ├── reminder.py          # Task Scheduler reminders
    ├── flight_finder.py     # Flight search
    ├── game_updater.py      # Steam/Epic updater
    ├── desktop.py           # Desktop management
    └── ...
```

---

## Troubleshooting

**JARVIS opens but doesn't respond to voice**
- Check your microphone is not muted (press F4)
- Make sure `elevenlabs_api_key` is set in `config/api_keys.json`
- Check Windows microphone permissions: Settings → Privacy → Microphone

**"Module not found" error**
```bash
pip install -r requirements.txt
```

**JARVIS says she can't access real-time data**
- This is fixed in the current version. JARVIS always uses live DuckDuckGo search.
- If it persists, check your internet connection.

**Desktop shortcut doesn't work**
- Re-run the PowerShell shortcut command from the [Desktop Shortcut](#desktop-shortcut) section above.
- Make sure the Python path matches your installed version.
- Verify `pythonw.exe` exists at the path shown.

**Playwright/browser tools don't work**
```bash
python -m playwright install chromium
```

---

## License

Personal and non-commercial use only.  
Licensed under **Creative Commons BY-NC 4.0**.

---

*MARK XXXIX — CLASSIFIED*
