"""
open_app.py — JARVIS App Launcher

Uses Windows Search (the same engine as the Start menu) to find
any installed app on the device, then launches it.

Search order:
1. PowerShell Get-StartApps  — searches ALL installed apps (Win32 + Store)
2. Start Menu .lnk shortcuts — covers Win32 apps with shortcuts
3. Store AppUserModelId table — WhatsApp, Telegram, etc.
4. Windows built-in commands  — notepad, calc, cmd, etc.
5. os.startfile fallback       — Windows registered apps
"""

import os
import subprocess
import time
from pathlib import Path

_OS = __import__('platform').system()


def _search_and_launch_powershell(app_name: str) -> bool:
    """
    Use PowerShell Get-StartApps to find any installed app by name,
    then launch it. This searches the same database as the Windows Start menu
    -- covers every Win32, Store, and UWP app installed on the device.
    """
    import re as _re
    # Sanitize app_name -- only allow alphanumeric, space, hyphen, dot to prevent injection
    safe_name = _re.sub(r"[^a-zA-Z0-9 \-_\.]", "", app_name).strip()
    if not safe_name:
        print(f"[open_app] app_name sanitized to empty, skipping PS search")
        return False

    try:
        # Query Get-StartApps using safe name
        ps_script = f"""
$apps = Get-StartApps | Where-Object {{ $_.Name -like '*{safe_name}*' }}
if ($apps) {{
    $app = $apps | Select-Object -First 1
    Write-Output $app.AppID
    Write-Output $app.Name
}}
"""
        result = subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, text=True, timeout=10
        )
        output = result.stdout.strip().splitlines()
        if len(output) >= 2:
            app_id   = output[0].strip()
            app_found = output[1].strip()
            print(f"[open_app] Found via Get-StartApps: '{app_found}' (ID: {app_id})")

            # Launch it
            launch_script = f'Start-Process "shell:AppsFolder\\{app_id}"'
            launch_result = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command", launch_script],
                capture_output=True, text=True, timeout=8
            )
            if launch_result.returncode == 0:
                time.sleep(2.0)
                print(f"[open_app] ✅ Launched: {app_found}")
                return True

            # If Start-Process fails (some apps), try Invoke-Item
            invoke_script = f'Invoke-Item "shell:AppsFolder\\{app_id}"'
            invoke_result = subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command", invoke_script],
                capture_output=True, text=True, timeout=8
            )
            if invoke_result.returncode == 0:
                time.sleep(2.0)
                print(f"[open_app] Launched via Invoke-Item: {app_found}")
                return True
            print(f"[open_app] Both launch methods failed for {app_found}")
            return False

    except subprocess.TimeoutExpired:
        print("[open_app] Get-StartApps timed out")
    except Exception as e:
        print(f"[open_app] Get-StartApps error: {e}")

    return False


def _find_in_start_menu(app_name: str) -> str | None:
    """Search Windows Start Menu .lnk files for a matching app."""
    search_dirs = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    app_lower = app_name.lower().replace(" ", "").replace("-", "")
    best_match = None
    best_score = 0.0

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        try:
            for lnk in search_dir.rglob("*.lnk"):
                lnk_name = lnk.stem.lower().replace(" ", "").replace("-", "")
                if lnk_name == app_lower:
                    return str(lnk)   # exact match
                if app_lower in lnk_name:
                    score = len(app_lower) / max(len(lnk_name), 1)
                    if score >= 0.5 and score > best_score:
                        best_score = score
                        best_match = str(lnk)
                if lnk_name.startswith(app_lower) and len(app_lower) >= 4:
                    score = 0.9
                    if score > best_score:
                        best_score = score
                        best_match = str(lnk)
        except (PermissionError, OSError):
            continue

    return best_match


# Windows Store App IDs
_STORE_APPS: dict[str, str] = {
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
    "sticky notes":  "Microsoft.MicrosoftStickyNotes_8wekyb3d8bbwe!App",
    "snipping tool": "Microsoft.ScreenSketch_8wekyb3d8bbwe!App",
}

# Windows built-in commands
_BUILTINS: dict[str, str] = {
    "notepad":           "notepad.exe",
    "calculator":        "calc.exe",
    "calc":              "calc.exe",
    "paint":             "mspaint.exe",
    "wordpad":           "wordpad.exe",
    "cmd":               "cmd.exe",
    "command prompt":    "cmd.exe",
    "powershell":        "powershell.exe",
    "terminal":          "wt.exe",
    "windows terminal":  "wt.exe",
    "task manager":      "taskmgr.exe",
    "file explorer":     "explorer.exe",
    "explorer":          "explorer.exe",
    "settings":          "ms-settings:",
    "magnifier":         "magnify.exe",
    "on screen keyboard":"osk.exe",
    "snip":              "snippingtool.exe",
    "character map":     "charmap.exe",
    "registry editor":   "regedit.exe",
    "control panel":     "control.exe",
}

# Well-known exe paths
_KNOWN_EXES: dict[str, list[str]] = {
    "edge":    [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
    "msedge":  [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
    "chrome":  [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe"],
    "brave":   [r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"],
    "vlc":     [r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"],
    "steam":   [r"C:\Program Files (x86)\Steam\steam.exe",
                r"C:\Program Files\Steam\steam.exe"],
    "word":    [r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
                r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE"],
    "excel":   [r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
                r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"],
    "powerpoint": [r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE"],
    "outlook": [r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE"],
    "zoom":    [str(Path.home() / "AppData/Roaming/Zoom/bin/Zoom.exe")],
    "slack":   [str(Path.home() / "AppData/Local/slack/slack.exe")],
    "vscode":  [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
    "vs code": [str(Path.home() / "AppData/Local/Programs/Microsoft VS Code/Code.exe")],
    "obsidian":[str(Path.home() / "AppData/Local/Obsidian/Obsidian.exe")],
    "notion":  [str(Path.home() / "AppData/Local/Programs/Notion/Notion.exe")],
    "postman": [str(Path.home() / "AppData/Local/Postman/Postman.exe")],
}


def open_app(
    parameters=None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Find and open any app installed on the user's device.
    Uses Windows Search (Get-StartApps) to find apps the same way Start menu does.
    """
    app_name = (parameters or {}).get("app_name", "").strip()
    if not app_name:
        return "Please tell me which app to open, boss."

    if _OS != "Windows":
        # macOS / Linux
        try:
            if _OS == "Darwin":
                r = subprocess.run(["open", "-a", app_name], capture_output=True, timeout=8)
                if r.returncode == 0:
                    return f"Opened {app_name}, boss."
            else:
                import shutil as _sh
                binary = _sh.which(app_name.lower())
                if binary:
                    subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return f"Opened {app_name}, boss."
        except Exception as e:
            return f"Could not open {app_name}, boss: {e}"
        return f"Could not find {app_name}, boss."

    key = app_name.lower().strip()
    print(f"[open_app] Searching for: {app_name!r}")
    if player:
        player.write_log(f"[open_app] {app_name}")

    # ── 1. Windows Search via Get-StartApps (catches EVERYTHING) ─────────
    if _search_and_launch_powershell(app_name):
        return f"Opened {app_name}, boss."

    # ── 2. Windows built-in commands ─────────────────────────────────────
    import shutil as _sh
    if key in _BUILTINS:
        cmd = _BUILTINS[key]
        if cmd.endswith(":"):
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", f'Invoke-Item "{cmd}"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return f"Opened {app_name}, boss."
        binary = _sh.which(cmd)
        if binary:
            subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return f"Opened {app_name}, boss."

    # ── 3. App in PATH ────────────────────────────────────────────────────
    binary = _sh.which(app_name) or _sh.which(key) or _sh.which(key.replace(" ", ""))
    if binary:
        subprocess.Popen([binary], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[open_app] ✅ PATH: {binary}")
        return f"Opened {app_name}, boss."

    # ── 4. Well-known exe paths ───────────────────────────────────────────
    for path_key, paths in _KNOWN_EXES.items():
        if path_key == key or key in path_key or path_key in key:
            for exe in paths:
                if Path(exe).exists():
                    subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL,
                                     cwd=str(Path(exe).parent))
                    time.sleep(1.0)
                    print(f"[open_app] ✅ Known path: {exe}")
                    return f"Opened {app_name}, boss."

    # ── 5. Windows Store apps ─────────────────────────────────────────────
    if key in _STORE_APPS:
        aumid = _STORE_APPS[key]
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command",
             f'Invoke-Item "shell:AppsFolder\\{aumid}"'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2.0)
        print(f"[open_app] ✅ Store: {aumid}")
        return f"Opened {app_name}, boss."

    # ── 6. Start Menu .lnk shortcuts ─────────────────────────────────────
    lnk = _find_in_start_menu(app_name)
    if lnk:
        try:
            os.startfile(lnk)
            time.sleep(2.0)
            print(f"[open_app] ✅ Start Menu: {Path(lnk).stem}")
            return f"Opened {app_name}, boss."
        except Exception as e:
            print(f"[open_app] LNK launch failed: {e}")

    # ── 7. os.startfile last resort ───────────────────────────────────────
    try:
        os.startfile(app_name)
        time.sleep(1.5)
        return f"Opened {app_name}, boss."
    except Exception:
        pass

    print(f"[open_app] ❌ Not found: {app_name}")
    return (
        f"I could not find {app_name} on your device, boss. "
        f"Make sure it is installed, or try the exact name."
    )
