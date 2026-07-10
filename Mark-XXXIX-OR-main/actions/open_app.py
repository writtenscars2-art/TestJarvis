# actions/open_app.py
# MARK XXV — Cross-Platform App Launcher

import time
import subprocess
import platform
import shutil

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

_APP_ALIASES = {
    "whatsapp":           {"Windows": "WhatsApp",               "Darwin": "WhatsApp",            "Linux": "whatsapp"},
    "chrome":             {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "google chrome":      {"Windows": "chrome",                 "Darwin": "Google Chrome",       "Linux": "google-chrome"},
    "firefox":            {"Windows": "firefox",                "Darwin": "Firefox",             "Linux": "firefox"},
    "spotify":            {"Windows": "Spotify",                "Darwin": "Spotify",             "Linux": "spotify"},
    "vscode":             {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "visual studio code": {"Windows": "code",                   "Darwin": "Visual Studio Code",  "Linux": "code"},
    "discord":            {"Windows": "Discord",                "Darwin": "Discord",             "Linux": "discord"},
    "telegram":           {"Windows": "Telegram",               "Darwin": "Telegram",            "Linux": "telegram"},
    "instagram":          {"Windows": "Instagram",              "Darwin": "Instagram",           "Linux": "instagram"},
    "tiktok":             {"Windows": "TikTok",                 "Darwin": "TikTok",              "Linux": "tiktok"},
    "notepad":            {"Windows": "notepad.exe",            "Darwin": "TextEdit",            "Linux": "gedit"},
    "calculator":         {"Windows": "calc.exe",               "Darwin": "Calculator",          "Linux": "gnome-calculator"},
    "terminal":           {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "gnome-terminal"},
    "cmd":                {"Windows": "cmd.exe",                "Darwin": "Terminal",            "Linux": "bash"},
    "explorer":           {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "file explorer":      {"Windows": "explorer.exe",           "Darwin": "Finder",              "Linux": "nautilus"},
    "paint":              {"Windows": "mspaint.exe",            "Darwin": "Preview",             "Linux": "gimp"},
    "word":               {"Windows": "winword",                "Darwin": "Microsoft Word",      "Linux": "libreoffice --writer"},
    "excel":              {"Windows": "excel",                  "Darwin": "Microsoft Excel",     "Linux": "libreoffice --calc"},
    "powerpoint":         {"Windows": "powerpnt",               "Darwin": "Microsoft PowerPoint","Linux": "libreoffice --impress"},
    "vlc":                {"Windows": "vlc",                    "Darwin": "VLC",                 "Linux": "vlc"},
    "zoom":               {"Windows": "Zoom",                   "Darwin": "zoom.us",             "Linux": "zoom"},
    "slack":              {"Windows": "Slack",                  "Darwin": "Slack",               "Linux": "slack"},
    "steam":              {"Windows": "steam",                  "Darwin": "Steam",               "Linux": "steam"},
    "task manager":       {"Windows": "taskmgr.exe",            "Darwin": "Activity Monitor",    "Linux": "gnome-system-monitor"},
    "settings":           {"Windows": "ms-settings:",           "Darwin": "System Preferences",  "Linux": "gnome-control-center"},
    "powershell":         {"Windows": "powershell.exe",         "Darwin": "Terminal",            "Linux": "bash"},
    "edge":               {"Windows": "msedge",                 "Darwin": "Microsoft Edge",      "Linux": "microsoft-edge"},
    "brave":              {"Windows": "brave",                  "Darwin": "Brave Browser",       "Linux": "brave-browser"},
    "obsidian":           {"Windows": "Obsidian",               "Darwin": "Obsidian",            "Linux": "obsidian"},
    "notion":             {"Windows": "Notion",                 "Darwin": "Notion",              "Linux": "notion"},
    "blender":            {"Windows": "blender",                "Darwin": "Blender",             "Linux": "blender"},
    "capcut":             {"Windows": "CapCut",                 "Darwin": "CapCut",              "Linux": "capcut"},
    "postman":            {"Windows": "Postman",                "Darwin": "Postman",             "Linux": "postman"},
    "figma":              {"Windows": "Figma",                  "Darwin": "Figma",               "Linux": "figma"},
}


def _normalize(raw: str) -> str:
    system = platform.system()
    key    = raw.lower().strip()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key].get(system, raw)
    for alias_key, os_map in _APP_ALIASES.items():
        if alias_key in key or key in alias_key:
            return os_map.get(system, raw)
    return raw


def _is_running(app_name: str) -> bool:
    if not _PSUTIL:
        return True
    app_lower = app_name.lower().replace(" ", "").replace(".exe", "")
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                proc_name = proc.info["name"].lower().replace(" ", "").replace(".exe", "")
                if app_lower in proc_name or proc_name in app_lower:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def _launch_windows(app_name: str) -> bool:
    """
    Launch on Windows with correct priority:
    1. Windows Store apps (most modern apps: WhatsApp, Spotify, etc.)
    2. Direct binary in PATH (classic apps: notepad, chrome, code, etc.)
    3. Common executable paths (edge, office apps)
    4. URI schemes (ms-settings:, etc.)
    5. Start menu search (last resort)
    """
    import subprocess as _sp

    _STORE_IDS = {
        "whatsapp":    "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsAppDesktop",
        "spotify":     "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
        "calculator":  "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        "calendar":    "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
        "mail":        "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
        "windows store": "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
        "store":       "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
        "photos":      "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
        "camera":      "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
        "maps":        "Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
        "xbox":        "Microsoft.XboxApp_8wekyb3d8bbwe!Microsoft.XboxApp",
        "teams":       "MSTeams_8wekyb3d8bbwe!MSTeams",
        "telegram":    "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram",
        "instagram":   "Facebook.Instagram_8xx8rvfyw5nnt!Instagram",
        "tiktok":      "BytedancePte.Ltd.TikTok_6yccndn6064se!TikTok",
        "netflix":     "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix",
        "discord":     "Discord.Discord",
        "minecraft":   "Microsoft.MinecraftUWP_8wekyb3d8bbwe!App",
        "skype":       "Microsoft.SkypeApp_kzf8qxf38zg5c!App",
        "onenote":     "Microsoft.Office.OneNote_8wekyb3d8bbwe!microsoft.onenoteim",
    }

    # Hard-coded exe paths for apps not in PATH
    _EXE_PATHS = {
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "microsoftedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ],
    }

    app_key = app_name.lower().strip().replace(".exe", "").replace(" ", "")

    # ── Step 1: Windows Store apps ─────────────────────────────────────────
    # Check both the raw key and the app_name.lower() for Store IDs
    store_key = app_name.lower().strip()
    aumid = _STORE_IDS.get(store_key) or _STORE_IDS.get(app_key)
    if aumid:
        try:
            _sp.Popen(
                ["explorer", f"shell:AppsFolder\\{aumid}"],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL
            )
            time.sleep(2.0)
            print(f"[open_app] ✅ Launched Store app: {aumid}")
            return True
        except Exception as e:
            print(f"[open_app] Store launch failed: {e}")

    # ── Step 2: Direct binary in PATH ─────────────────────────────────────
    binary = shutil.which(app_name) or shutil.which(app_name.lower())
    if binary:
        try:
            _sp.Popen([binary], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            time.sleep(1.5)
            print(f"[open_app] ✅ Launched from PATH: {binary}")
            return True
        except Exception as e:
            print(f"[open_app] PATH launch failed: {e}")

    # ── Step 3: Hard-coded exe paths ──────────────────────────────────────
    from pathlib import Path as _P
    for path_key, paths in _EXE_PATHS.items():
        if path_key in app_key or app_key in path_key:
            for exe_path in paths:
                if _P(exe_path).exists():
                    try:
                        _sp.Popen([exe_path], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                        time.sleep(1.5)
                        print(f"[open_app] ✅ Launched from hard-coded path: {exe_path}")
                        return True
                    except Exception:
                        pass

    # ── Step 4: URI schemes (ms-settings:, shell:, etc.) ──────────────────
    if ":" in app_name and not _P(app_name).exists():
        try:
            _sp.Popen(["cmd", "/c", "start", "", app_name],
                      stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            time.sleep(1.0)
            print(f"[open_app] ✅ Launched URI: {app_name}")
            return True
        except Exception as e:
            print(f"[open_app] URI launch failed: {e}")

    # ── Step 5: Search common install locations ───────────────────────────
    # Try common program directories before touching the keyboard
    from pathlib import Path as _P
    search_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        str(_P.home() / "AppData" / "Local"),
        str(_P.home() / "AppData" / "Local" / "Programs"),
        str(_P.home() / "AppData" / "Roaming"),
    ]
    app_lower = app_name.lower().replace(" ", "")
    for search_dir in search_dirs:
        search_path = _P(search_dir)
        if not search_path.exists():
            continue
        try:
            for exe in search_path.rglob(f"{app_name}.exe"):
                try:
                    _sp.Popen([str(exe)], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                    time.sleep(1.5)
                    print(f"[open_app] ✅ Found and launched: {exe}")
                    return True
                except Exception:
                    pass
            # Also try lowercase/no-space variant
            for exe in search_path.rglob(f"*{app_lower}*.exe"):
                if exe.name.lower().startswith(app_lower[:4]):
                    try:
                        _sp.Popen([str(exe)], stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
                        time.sleep(1.5)
                        print(f"[open_app] ✅ Found and launched: {exe}")
                        return True
                    except Exception:
                        pass
        except Exception:
            pass

    # ── NO keyboard fallback — it causes random side effects ──────────────
    print(f"[open_app] ❌ Could not find {app_name} — not launching via keyboard")
    return False

def _launch_macos(app_name: str) -> bool:
    try:
        result = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        result = subprocess.run(["open", "-a", f"{app_name}.app"], capture_output=True, timeout=8)
        if result.returncode == 0:
            time.sleep(1.0)
            return True
    except Exception:
        pass

    try:
        import pyautogui
        pyautogui.hotkey("command", "space")
        time.sleep(0.6)
        pyautogui.write(app_name, interval=0.05)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.5)
        return True
    except Exception as e:
        print(f"[open_app] ⚠️ macOS Spotlight failed: {e}")
        return False



def _launch_linux(app_name: str) -> bool:
    binary = (
        shutil.which(app_name) or
        shutil.which(app_name.lower()) or
        shutil.which(app_name.lower().replace(" ", "-"))
    )
    if binary:
        try:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            return True
        except Exception:
            pass

    try:
        subprocess.run(["xdg-open", app_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    try:
        desktop_name = app_name.lower().replace(" ", "-")
        subprocess.run(["gtk-launch", desktop_name], capture_output=True, timeout=5)
        return True
    except Exception:
        pass

    return False


_OS_LAUNCHERS = {
    "Windows": _launch_windows,
    "Darwin":  _launch_macos,
    "Linux":   _launch_linux,
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    app_name = (parameters or {}).get("app_name", "").strip()

    if not app_name:
        return "Please specify which application to open, sir."

    system   = platform.system()
    launcher = _OS_LAUNCHERS.get(system)

    if launcher is None:
        return f"Unsupported OS: {system}"

    normalized = _normalize(app_name)
    print(f"[open_app] 🚀 Launching: {app_name} → {normalized} ({system})")

    if player:
        player.write_log(f"[open_app] {app_name}")

    try:
        success = launcher(normalized)

        if success is True:
            return f"Opened {app_name}, boss."

        if success is None:
            return f"I launched {app_name}, boss. It should be open shortly."

        # False — try original name if different from normalized
        if normalized.lower() != app_name.lower():
            success2 = launcher(app_name)
            if success2 is True:
                return f"Opened {app_name}, boss."
            if success2 is None:
                return f"I launched {app_name}, boss. It should be open shortly."

        return (
            f"I could not find {app_name} on your device, boss. "
            f"Make sure it is installed, or try saying the exact app name."
        )

    except Exception as e:
        print(f"[open_app] ❌ {e}")
        return f"Failed to open {app_name}, boss: {e}"
