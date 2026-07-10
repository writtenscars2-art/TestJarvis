"""
browser_control.py — Controls the user's actual default browser.

NO Playwright. NO separate browser instance.
Uses subprocess to open/navigate URLs in the user's real browser,
and pyautogui for keyboard/mouse control of whatever window is open.

This means JARVIS controls YOUR browser, not a sandbox.
"""

import json
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _GUI = True
except ImportError:
    _GUI = False

try:
    import pyperclip
    _CLIP = True
except ImportError:
    _CLIP = False


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

_CONFIG_PATH = _get_base_dir() / "config" / "api_keys.json"

_OS = platform.system()


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_browser_exe() -> str:
    """Return the path or command for the user's default browser."""
    cfg     = _load_config()
    browser = cfg.get("default_browser", "msedge").strip().lower()

    # Map config name to executable
    exe_map = {
        "msedge":  "msedge",
        "edge":    "msedge",
        "chrome":  "chrome",
        "firefox": "firefox",
        "brave":   "brave",
        "opera":   "opera",
    }
    exe = exe_map.get(browser, "msedge")

    # If it's in PATH, use it directly
    if shutil.which(exe):
        return exe

    # Hard-coded paths for common Windows installs
    candidates = {
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ],
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ],
        "firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "brave": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
    }
    for path in candidates.get(exe, []):
        if Path(path).exists():
            return path

    # Last resort — use Windows default via cmd
    return ""


def _open_url(url: str) -> str:
    """Open a URL in the user's default browser."""
    if not url.startswith("http"):
        url = "https://" + url

    browser_exe = _get_browser_exe()
    print(f"[Browser] Opening {url} with {browser_exe or 'default'}")

    try:
        if browser_exe:
            subprocess.Popen(
                [browser_exe, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # Fallback: use Windows shell association
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
            )
        time.sleep(0.5)
        return f"Opened: {url}"
    except Exception as e:
        # Final fallback: webbrowser module
        try:
            import webbrowser
            webbrowser.open(url)
            return f"Opened: {url}"
        except Exception as e2:
            return f"Could not open browser: {e2}"


def _search_web(query: str, engine: str = "google") -> str:
    """Search the web in the default browser."""
    engines = {
        "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
        "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
        "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        "youtube":    f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}",
    }
    url = engines.get(engine.lower(), engines["google"])
    return _open_url(url)


def _navigate_current(url: str) -> str:
    """Navigate the currently focused browser to a URL using Ctrl+L."""
    if not _GUI:
        return _open_url(url)

    if not url.startswith("http"):
        url = "https://" + url

    try:
        # Ctrl+L focuses the address bar in all major browsers
        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.3)
        # Clear and type URL
        pyautogui.hotkey("ctrl", "a")
        if _CLIP:
            pyperclip.copy(url)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.write(url, interval=0.02)
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)
        return f"Navigated to: {url}"
    except Exception as e:
        return _open_url(url)  # fallback to opening new tab


def _click_element(text: str = None, selector: str = None) -> str:
    if not _GUI:
        return "pyautogui not available."
    try:
        if text:
            # Find text on screen and click it
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            if _CLIP:
                pyperclip.copy(text)
                pyautogui.hotkey("ctrl", "v")
            else:
                pyautogui.write(text, interval=0.03)
            time.sleep(0.3)
            pyautogui.press("escape")
            return f"Searched for: {text}"
    except Exception as e:
        return f"Click error: {e}"
    return "No target specified."


def _scroll_page(direction: str = "down", amount: int = 500) -> str:
    if not _GUI:
        return "pyautogui not available."
    try:
        scroll = -amount if direction == "down" else amount
        pyautogui.scroll(scroll)
        return f"Scrolled {direction}."
    except Exception as e:
        return f"Scroll error: {e}"


def _new_tab(url: str = "") -> str:
    if not _GUI:
        return _open_url(url) if url else "pyautogui not available."
    try:
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.4)
        if url:
            return _navigate_current(url)
        return "New tab opened."
    except Exception as e:
        return f"New tab error: {e}"


def _close_tab() -> str:
    if not _GUI:
        return "pyautogui not available."
    try:
        pyautogui.hotkey("ctrl", "w")
        return "Tab closed."
    except Exception as e:
        return f"Close tab error: {e}"


def _go_back() -> str:
    if not _GUI:
        return "pyautogui not available."
    pyautogui.hotkey("alt", "left")
    return "Went back."


def _go_forward() -> str:
    if not _GUI:
        return "pyautogui not available."
    pyautogui.hotkey("alt", "right")
    return "Went forward."


def _refresh() -> str:
    if not _GUI:
        return "pyautogui not available."
    pyautogui.press("f5")
    return "Page refreshed."


def _type_in_browser(text: str) -> str:
    if not _GUI:
        return "pyautogui not available."
    try:
        if _CLIP:
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        else:
            pyautogui.write(text, interval=0.03)
        return f"Typed: {text[:60]}"
    except Exception as e:
        return f"Type error: {e}"


def _press_key(key: str) -> str:
    if not _GUI:
        return "pyautogui not available."
    try:
        pyautogui.press(key)
        return f"Pressed: {key}"
    except Exception as e:
        return f"Key error: {e}"


# ── Public API ────────────────────────────────────────────────────────────────

def browser_control(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Controls the user's actual default browser directly.
    No Playwright — uses subprocess for URL opening, pyautogui for interaction.

    actions:
        go_to / open / navigate  : open a URL in default browser
        search                   : search Google (or other engine)
        navigate_current         : navigate current browser window to URL
        new_tab                  : open new tab (optionally with URL)
        close_tab                : close current tab
        scroll                   : scroll up/down
        click                    : find and click text on page
        type                     : type text into focused element
        back                     : go back
        forward                  : go forward
        refresh                  : refresh current page
        press                    : press a key (Enter, Escape, Tab, etc.)
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    url    = params.get("url", "").strip()
    query  = params.get("query", "").strip()

    result = "Unknown browser action."

    try:
        if action in ("go_to", "open", "navigate"):
            if url:
                result = _open_url(url)
            elif query:
                result = _search_web(query)
            else:
                # No URL or query — just open the browser
                exe = _get_browser_exe()
                if exe:
                    subprocess.Popen([exe], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                    result = "Browser opened."
                else:
                    import webbrowser
                    webbrowser.open("about:blank")
                    result = "Browser opened."

        elif action == "search":
            q      = query or params.get("text", "")
            engine = params.get("engine", "google")
            result = _search_web(q, engine) if q else "No search query provided."

        elif action == "navigate_current":
            result = _navigate_current(url or query)

        elif action == "new_tab":
            result = _new_tab(url)

        elif action == "close_tab":
            result = _close_tab()

        elif action == "scroll":
            result = _scroll_page(
                params.get("direction", "down"),
                int(params.get("amount", 500))
            )

        elif action == "click":
            result = _click_element(
                text=params.get("text"),
                selector=params.get("selector"),
            )

        elif action == "type":
            result = _type_in_browser(params.get("text", ""))

        elif action == "back":
            result = _go_back()

        elif action == "forward":
            result = _go_forward()

        elif action in ("refresh", "reload"):
            result = _refresh()

        elif action == "press":
            result = _press_key(params.get("key", "Enter"))

        else:
            # Try to open as URL if action looks like a URL
            if action.startswith("http") or "." in action:
                result = _open_url(action)
            else:
                result = f"Unknown browser action: '{action}'"

    except Exception as e:
        result = f"Browser error: {e}"

    print(f"[Browser] {result[:100]}")
    if player:
        player.write_log(f"[Browser] {result[:60]}")

    return result
