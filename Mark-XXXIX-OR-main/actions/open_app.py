"""
open_app.py — JARVIS App Launcher (Windows)

Launch strategy (in order):
1. Windows Store / UWP apps via AppUserModelId  (WhatsApp, Telegram, etc.)
2. Known executable paths                        (Edge, Chrome, Office, etc.)
3. shutil.which — apps in system PATH            (notepad, calc, code, etc.)
4. HONEST FAILURE — no keyboard, no filesystem crawl, no side effects
"""

import json
import platform
import shutil
import subprocess
import time
from pathlib import Path

_OS = platform.system()


def _get_base_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


# ── Windows Store App IDs (AppUserModelId) ────────────────────────────────────
# Launch via: explorer.exe shell:AppsFolder\{AUMID}
_STORE_APPS: dict[str, str] = {
    "whatsapp":         "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsAppDesktop",
    "telegram":         "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram",
    "instagram":        "Facebook.Instagram_8xx8rvfyw5nnt!Instagram",
    "tiktok":           "BytedancePte.Ltd.TikTok_6yccndn6064se!TikTok",
    "netflix":          "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix",
    "spotify":          "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "discord":          "Discord.Discord",
    "teams":            "MSTeams_8wekyb3d8bbwe!MSTeams",
    "microsoft teams":  "MSTeams_8wekyb3d8bbwe!MSTeams",
    "xbox":             "Microsoft.XboxApp_8wekyb3d8bbwe!Microsoft.XboxApp",
    "minecraft":        "Microsoft.MinecraftUWP_8wekyb3d8bbwe!App",
    "skype":            "Microsoft.SkypeApp_kzf8qxf38zg5c!App",
    "onenote":          "Microsoft.Office.OneNote_8wekyb3d8bbwe!microsoft.onenoteim",
    "windows store":    "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    "store":            "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    "photos":           "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
    "camera":           "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    "maps":             "Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
    "calendar":         "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
    "mail":             "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
    "clock":            "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "alarms":           "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "solitaire":        "Microsoft.MicrosoftSolitaireCollection_8wekyb3d8bbwe!App",
    "sticky notes":     "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
    "snip":             "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "snipping tool":    "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "paint 3d":         "Microsoft.MSPaint_8wekyb3d8bbwe!Microsoft.MSPaint",
}

# ── Known Windows executable paths ───────────────────────────────────────────
# For apps that are installed but not in PATH
_KNOWN_PATHS: dict[str, list[str]] = {
    "edge":         [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "msedge":       [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "microsoft edge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
    "chrome":       [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "google chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
    "firefox":      [r"C:\Program Files\Mozilla Firefox\firefox.exe",
                     r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"],
    "brave":        [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "opera":        [str(Path.home() / "AppData/Local/Programs/Opera/launcher.exe")],
    "opera gx":     [str(Path.home() / "AppData/Local/Programs/Opera GX/launcher.exe")],
    "vlc":          [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                     r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
    "zoom":         [str(Path.home() / "AppData/Roaming/Zoom/bin/Zoom.exe")],
    "slack":        [str(Path.home() / "AppData/Local/slack/slack.exe")],
    "vscode":       [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
    "visual studio code": [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
    "vs code":      [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
    "obsidian":     [str(Path.home() / "AppData/Local/Obsidian/Obsidian.exe")],
    "notion":       [str(Path.home() / "AppData/Local/Programs/Notion/Notion.exe")],
    "postman":      [str(Path.home() / "AppData/Local/Postman/Postman.exe")],
    "figma":        [str(Path.home() / "AppData/Local/Figma/Figma.exe")],
    "steam":        [r"C:\Program Files (x86)\Steam\steam.exe",
                     r"C:\Program Files\Steam\steam.exe"],
    "spotify desktop": [str(Path.home() / "AppData/Roaming/Spotify/Spotify.exe")],
    "discord app":  [str(Path.home() / "AppData/Local/Discord/app-latest/Discord.exe"),
                     str(Path.home() / "AppData/Roaming/Discord/Discord.exe")],
    "word":         [r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE"],
    "excel":        [r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"],
    "powerpoint":   [r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE"],
    "outlook":      [r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE"],
    "capcut":       [str(Path.home() / "AppData/Local/Programs/CapCut/CapCut.exe")],
    "blender":      [r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
                     r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe"],
}

# ── Apps directly in PATH (Windows built-ins + common installs) ──────────────
_PATH_COMMANDS: dict[str, str] = {
    "notepad":        "notepad.exe",
    "calculator":     "calc.exe",
    "calc":           "calc.exe",
    "paint":          "mspaint.exe",
    "mspaint":        "mspaint.exe",
    "wordpad":        "wordpad.exe",
    "cmd":            "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell":     "powershell.exe",
    "terminal":       "wt.exe",          # Windows Terminal
    "windows terminal": "wt.exe",
    "task manager":   "taskmgr.exe",
    "taskmgr":        "taskmgr.exe",
    "file explorer":  "explorer.exe",
    "explorer":       "explorer.exe",
    "control panel":  "control.exe",
    "registry":       "regedit.exe",
    "device manager": "devmgmt.msc",
    "settings":       "ms-settings:",    # URI scheme
    "magnifier":      "magnify.exe",
    "on screen keyboard": "osk.exe",
    "narrator":       "narrator.exe",
    "character map":  "charmap.exe",
}


def _launch_store(app_key: str) -> bool:
    """Launch a Windows Store app via AppUserModelId."""
    aumid = _STORE_APPS.get(app_key)
    if not aumid:
        return False
    try:
        subprocess.Popen(
            ["explorer.exe", f"shell:AppsFolder\\{aumid}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        time.sleep(1.5)
        print(f"[open_app] ✅ Store: {aumid}")
        return True
    except Exception as e:
        print(f"[open_app] Store launch failed: {e}")
        return False


def _launch_path(exe: str) -> bool:
    """Launch an exe by full path."""
    p = Path(exe)
    if not p.exists():
        return False
    try:
        subprocess.Popen(
            [str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        time.sleep(1.5)
        print(f"[open_app] ✅ Path: {p}")
        return True
    except Exception as e:
        print(f"[open_app] Path launch failed ({p}): {e}")
        return False


def _launch_uri(uri: str) -> bool:
    """Launch a URI scheme (ms-settings:, etc.)."""
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", uri],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        time.sleep(1.0)
        print(f"[open_app] ✅ URI: {uri}")
        return True
    except Exception as e:
        print(f"[open_app] URI launch failed: {e}")
        return False


def _launch_which(cmd: str) -> bool:
    """Launch a command that's in the system PATH."""
    binary = shutil.which(cmd)
    if not binary:
        return False
    # Special case: URI schemes handled differently
    if ":" in cmd and not Path(cmd).exists():
        return _launch_uri(cmd)
    try:
        subprocess.Popen(
            [binary],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        time.sleep(1.2)
        print(f"[open_app] ✅ PATH: {binary}")
        return True
    except Exception as e:
        print(f"[open_app] PATH launch failed ({binary}): {e}")
        return False


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Open any application on Windows.
    Tries Store apps → known paths → PATH → honest failure.
    NO keyboard shortcuts. NO filesystem crawling. NO side effects.
    """
    app_name = (parameters or {}).get("app_name", "").strip()
    if not app_name:
        return "Please tell me which app to open, boss."

    if _OS != "Windows":
        # macOS / Linux fallback
        try:
            if _OS == "Darwin":
                r = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
                if r.returncode == 0:
                    return f"Opened {app_name}, boss."
            else:
                binary = shutil.which(app_name.lower()) or shutil.which(app_name.lower().replace(" ", "-"))
                if binary:
                    subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Opened {app_name}, boss."
        except Exception as e:
            return f"Could not open {app_name}, boss: {e}"
        return f"Could not find {app_name}, boss."

    key = app_name.lower().strip()
    print(f"[open_app] Requested: {app_name!r} (key={key!r})")
    if player:
        player.write_log(f"[open_app] {app_name}")

    # ── 1. Windows Store apps ─────────────────────────────────────────────
    if _launch_store(key):
        return f"Opened {app_name}, boss."

    # ── 2. Known executable paths ─────────────────────────────────────────
    # Check exact key match first
    for path_key, paths in _KNOWN_PATHS.items():
        if path_key == key or key in path_key or path_key in key:
            for exe in paths:
                if _launch_path(exe):
                    return f"Opened {app_name}, boss."

    # ── 3. PATH commands (built-ins and well-known apps) ──────────────────
    # Check exact key match
    if key in _PATH_COMMANDS:
        cmd = _PATH_COMMANDS[key]
        if ":" in cmd:   # URI scheme
            if _launch_uri(cmd):
                return f"Opened {app_name}, boss."
        else:
            if _launch_which(cmd):
                return f"Opened {app_name}, boss."

    # Try the app_name directly as a command
    if _launch_which(app_name):
        return f"Opened {app_name}, boss."
    if _launch_which(app_name + ".exe"):
        return f"Opened {app_name}, boss."

    # ── 4. Honest failure — no side effects ───────────────────────────────
    print(f"[open_app] ❌ Could not find: {app_name}")
    return (
        f"I could not find {app_name} on your device, boss. "
        f"It may not be installed, or try a different name."
    )
