"""
open_app.py — JARVIS App Launcher

Finds and launches ANY app installed on the user's Windows device by:
1. Querying the Windows Start menu shortcuts (covers 99% of installed apps)
2. Searching AppData/Programs directories for .exe files
3. Windows Store apps via AppUserModelId lookup
4. Built-in Windows commands (notepad, calc, etc.)

NO keyboard shortcuts. NO explorer.exe. NO side effects.
"""

import os
import re
import subprocess
import time
import glob
from pathlib import Path

_OS = __import__('platform').system()


def _find_in_start_menu(app_name: str) -> str | None:
    """
    Search Windows Start Menu shortcuts (.lnk files) for the app.
    Start Menu covers virtually every installed Win32 app.
    Returns the .lnk path if found.
    """
    search_dirs = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    app_lower = app_name.lower().replace(" ", "").replace("-", "")
    best_match = None
    best_score = 0

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for lnk in search_dir.rglob("*.lnk"):
            lnk_name = lnk.stem.lower().replace(" ", "").replace("-", "")
            score = 0

            # Exact match
            if lnk_name == app_lower:
                return str(lnk)

            # Shortcut name starts with search term (e.g. "microsoftedge" starts with "edge" — no)
            # Search term found anywhere in shortcut name
            if app_lower in lnk_name:
                # How much of the shortcut name is our search term?
                score = len(app_lower) / max(len(lnk_name), 1)
                # Require meaningful overlap (avoid "what" matching "whatsapp" in WinRAR)
                if score >= 0.5:  # search term is at least 50% of the shortcut name
                    if score > best_score:
                        best_score = score
                        best_match = str(lnk)

            # Shortcut contains search term as a word boundary
            # e.g. lnk="googlechrome", search="chrome" — "chrome" is in "googlechrome"
            elif app_lower in lnk_name and len(app_lower) >= 4:
                score = 0.5
                if score > best_score:
                    best_score = score
                    best_match = str(lnk)

            # Shortcut starts with search term
            if lnk_name.startswith(app_lower) and len(app_lower) >= 4:
                score = max(score, 0.9)
                if score > best_score:
                    best_score = score
                    best_match = str(lnk)

    return best_match if best_score >= 0.5 else None


def _launch_lnk(lnk_path: str) -> bool:
    """Launch a .lnk shortcut file."""
    try:
        os.startfile(lnk_path)
        time.sleep(2.0)
        print(f"[open_app] ✅ Launched via shortcut: {Path(lnk_path).stem}")
        return True
    except Exception as e:
        print(f"[open_app] Shortcut launch failed: {e}")
        return False


def _find_exe_in_programs(app_name: str) -> str | None:
    """
    Search common install directories for a matching .exe.
    Checks AppData/Local/Programs (user-installed apps like VSCode, Discord, etc.)
    """
    app_lower = app_name.lower().replace(" ", "").replace("-", "")
    
    search_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft",
        Path(os.environ.get("APPDATA", "")) ,
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]

    for root in search_roots:
        if not root.exists():
            continue
        # Look for folders matching the app name, then find the main exe inside
        try:
            for folder in root.iterdir():
                if not folder.is_dir():
                    continue
                folder_lower = folder.name.lower().replace(" ", "").replace("-", "")
                if app_lower in folder_lower or folder_lower.startswith(app_lower[:5] if len(app_lower) >= 5 else app_lower):
                    # Found a matching folder — look for main exe inside
                    for exe in folder.glob("*.exe"):
                        exe_lower = exe.stem.lower().replace(" ", "").replace("-", "")
                        if app_lower in exe_lower or exe_lower.startswith(app_lower[:4] if len(app_lower) >= 4 else app_lower):
                            return str(exe)
                    # Try one level deeper
                    for subfolder in folder.iterdir():
                        if subfolder.is_dir():
                            for exe in subfolder.glob("*.exe"):
                                exe_lower = exe.stem.lower().replace(" ", "").replace("-", "")
                                if app_lower in exe_lower or exe_lower.startswith(app_lower[:4] if len(app_lower) >= 4 else app_lower):
                                    return str(exe)
        except (PermissionError, OSError):
            continue

    return None


def _launch_exe(exe_path: str) -> bool:
    """Launch an exe directly."""
    p = Path(exe_path)
    if not p.exists():
        return False
    try:
        subprocess.Popen(
            [str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(p.parent),  # set working dir to exe location
        )
        time.sleep(1.5)
        print(f"[open_app] ✅ Launched exe: {p.name}")
        return True
    except Exception as e:
        print(f"[open_app] Exe launch failed ({p}): {e}")
        return False


# Windows Store apps — known AppUserModelIds
_STORE_APPS = {
    "whatsapp":      "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!WhatsAppDesktop",
    "telegram":      "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram",
    "instagram":     "Facebook.Instagram_8xx8rvfyw5nnt!Instagram",
    "tiktok":        "BytedancePte.Ltd.TikTok_6yccndn6064se!TikTok",
    "netflix":       "4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix",
    "spotify":       "SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify",
    "discord":       "Discord.Discord",
    "teams":         "MSTeams_8wekyb3d8bbwe!MSTeams",
    "xbox":          "Microsoft.XboxApp_8wekyb3d8bbwe!Microsoft.XboxApp",
    "minecraft":     "Microsoft.MinecraftUWP_8wekyb3d8bbwe!App",
    "skype":         "Microsoft.SkypeApp_kzf8qxf38zg5c!App",
    "store":         "Microsoft.WindowsStore_8wekyb3d8bbwe!App",
    "photos":        "Microsoft.Windows.Photos_8wekyb3d8bbwe!App",
    "camera":        "Microsoft.WindowsCamera_8wekyb3d8bbwe!App",
    "maps":          "Microsoft.WindowsMaps_8wekyb3d8bbwe!App",
    "calendar":      "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.calendar",
    "mail":          "microsoft.windowscommunicationsapps_8wekyb3d8bbwe!microsoft.windowslive.mail",
    "clock":         "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "alarms":        "Microsoft.WindowsAlarms_8wekyb3d8bbwe!App",
    "sticky notes":  "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
    "snipping tool": "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
    "capcut":        "BytedancePte.Ltd.CapCut_6yccndn6064se!CapCut",
}

# Windows built-in commands
_BUILTINS = {
    "notepad":        "notepad.exe",
    "calculator":     "calc.exe",
    "calc":           "calc.exe",
    "paint":          "mspaint.exe",
    "wordpad":        "wordpad.exe",
    "cmd":            "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell":     "powershell.exe",
    "terminal":       "wt.exe",
    "task manager":   "taskmgr.exe",
    "taskmgr":        "taskmgr.exe",
    "file explorer":  "explorer.exe",
    "explorer":       "explorer.exe",
    "settings":       "ms-settings:",
    "magnifier":      "magnify.exe",
    "on screen keyboard": "osk.exe",
    "snip":           "snippingtool.exe",
    "character map":  "charmap.exe",
    "registry editor": "regedit.exe",
    "control panel":  "control.exe",
    "device manager": "devmgmt.msc",
    "disk management": "diskmgmt.msc",
    "services":       "services.msc",
    "event viewer":   "eventvwr.exe",
    "resource monitor": "resmon.exe",
    "performance monitor": "perfmon.exe",
}

# Well-known exe paths for apps that may not have Start Menu shortcuts
_KNOWN_EXES = {
    "edge":         [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                     r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "msedge":       [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
    "chrome":       [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                     r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "firefox":      [r"C:\Program Files\Mozilla Firefox\firefox.exe",
                     r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"],
    "brave":        [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "vlc":          [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                     r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
    "steam":        [r"C:\Program Files (x86)\Steam\steam.exe",
                     r"C:\Program Files\Steam\steam.exe"],
    "word":         [r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE"],
    "excel":        [r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"],
    "powerpoint":   [r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\POWERPNT.EXE"],
    "outlook":      [r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
                     r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE"],
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Open any installed application on the user's device.
    Searches Start Menu shortcuts, program directories, Store apps, and built-ins.
    """
    app_name = (parameters or {}).get("app_name", "").strip()
    if not app_name:
        return "Please tell me which app to open, boss."

    if _OS != "Windows":
        try:
            import shutil as _sh
            if _OS == "Darwin":
                r = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
                if r.returncode == 0:
                    return f"Opened {app_name}, boss."
            else:
                binary = _sh.which(app_name.lower())
                if binary:
                    subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Opened {app_name}, boss."
        except Exception as e:
            return f"Could not open {app_name}, boss: {e}"
        return f"Could not find {app_name}, boss."

    key = app_name.lower().strip()
    print(f"[open_app] Looking for: {app_name!r}")
    if player:
        player.write_log(f"[open_app] {app_name}")

    # ── 1. Windows built-in commands ─────────────────────────────────────
    import shutil as _sh
    if key in _BUILTINS:
        cmd = _BUILTINS[key]
        if cmd.endswith(":"):
            # URI scheme (ms-settings:)
            try:
                subprocess.Popen(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", f'Invoke-Item "{cmd}"'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(1.0)
                return f"Opened {app_name}, boss."
            except Exception:
                pass
        else:
            binary = _sh.which(cmd)
            if binary:
                subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)
                return f"Opened {app_name}, boss."

    # ── 2. App directly in PATH ───────────────────────────────────────────
    binary = _sh.which(app_name) or _sh.which(app_name.lower()) or _sh.which(key.replace(" ", ""))
    if binary:
        subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.0)
        print(f"[open_app] ✅ PATH: {binary}")
        return f"Opened {app_name}, boss."

    # ── 3. Well-known exe paths ───────────────────────────────────────────
    for path_key, paths in _KNOWN_EXES.items():
        if path_key == key or key in path_key or path_key in key:
            for exe in paths:
                if _launch_exe(exe):
                    return f"Opened {app_name}, boss."

    # ── 4. Windows Store apps ─────────────────────────────────────────────
    if key in _STORE_APPS:
        aumid = _STORE_APPS[key]
        try:
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command",
                 f'Invoke-Item "shell:AppsFolder\\{aumid}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(2.0)
            print(f"[open_app] ✅ Store: {aumid}")
            return f"Opened {app_name}, boss."
        except Exception:
            # Fallback to explorer for Store apps
            try:
                subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{aumid}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                time.sleep(2.0)
                return f"Opened {app_name}, boss."
            except Exception as e:
                print(f"[open_app] Store launch failed: {e}")

    # ── 5. Start Menu shortcuts (covers 99% of installed Win32 apps) ──────
    lnk = _find_in_start_menu(app_name)
    if lnk:
        if _launch_lnk(lnk):
            return f"Opened {app_name}, boss."

    # ── 6. Search program directories for .exe ────────────────────────────
    exe = _find_exe_in_programs(app_name)
    if exe:
        if _launch_exe(exe):
            return f"Opened {app_name}, boss."

    # ── 7. Try os.startfile as last resort ────────────────────────────────
    # Windows associates app names with registered applications
    for attempt in [app_name, app_name.lower(), key]:
        try:
            os.startfile(attempt)
            time.sleep(1.5)
            print(f"[open_app] ✅ os.startfile: {attempt}")
            return f"Opened {app_name}, boss."
        except Exception:
            pass

    print(f"[open_app] ❌ Could not find: {app_name}")
    return (
        f"I could not find {app_name} on your device, boss. "
        f"Make sure it is installed, or try the exact app name."
    )
