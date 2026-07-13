"""
transport_finder.py — All-modes transport search for JARVIS.

Supports:
  flight      — Google Flights
  train       — Google Maps transit / Trainline / Rome2rio
  bus         — Google Maps / FlixBus / Rome2rio
  taxi / ride — Uber / Bolt / Google Maps
  car_rental  — Google car rentals / Kayak
  ferry       — Rome2rio ferry
  any         — Rome2rio (auto-selects best mode)

All searches open in the user's real browser — no API keys needed.
"""

import json
import re
import subprocess
import sys
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_browser_exe() -> str:
    cfg     = _load_config()
    browser = cfg.get("default_browser", "msedge").strip().lower()
    exe_map = {"msedge": "msedge", "edge": "msedge", "chrome": "chrome",
               "firefox": "firefox", "brave": "brave"}
    exe     = exe_map.get(browser, "msedge")
    if shutil.which(exe):
        return exe
    candidates = {
        "msedge": [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                   r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"],
        "chrome": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
        "firefox":[r"C:\Program Files\Mozilla Firefox\firefox.exe"],
    }
    for path in candidates.get(exe, []):
        if Path(path).exists():
            return path
    return ""


def _open_url(url: str) -> None:
    """Open URL in the user's default browser — always works."""
    import os as _os
    print(f"[Transport] Opening: {url[:100]}")
    exe = _get_browser_exe()
    try:
        if exe:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            _os.startfile(url) if url.startswith("file://") else subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False)
        time.sleep(0.5)
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            print(f"[Transport] Could not open browser: {e}")


# ── Date parsing ──────────────────────────────────────────────────────────────

_MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,
    "sep":9,"oct":10,"nov":11,"dec":12,
}

def _parse_date(raw: str) -> str:
    """Convert any date expression to YYYY-MM-DD."""
    if not raw:
        return datetime.now().strftime("%Y-%m-%d")
    raw   = raw.strip()
    lower = raw.lower()
    today = datetime.now()

    # Already formatted
    if re.match(r"\d{4}-\d{2}-\d{2}$", raw):
        return raw

    # Common formats
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y",
                "%d/%m/%y", "%m/%d/%y", "%B %d %Y", "%b %d %Y",
                "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Relative
    if "today" in lower:
        return today.strftime("%Y-%m-%d")
    if "tomorrow" in lower:
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    if "day after tomorrow" in lower:
        return (today + timedelta(days=2)).strftime("%Y-%m-%d")

    m = re.search(r"in\s+(\d+)\s+days?", lower)
    if m:
        return (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")

    # "15 March", "March 15", "15th March"
    day_m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", raw)
    for month_name, month_num in _MONTH_MAP.items():
        if month_name in lower and day_m:
            day  = int(day_m.group(1))
            year = today.year if month_num > today.month or (
                month_num == today.month and day >= today.day) else today.year + 1
            return f"{year}-{month_num:02d}-{day:02d}"

    # Use Groq/NVIDIA as fallback date parser
    try:
        from openai import OpenAI
        cfg      = _load_config()
        groq_key = cfg.get("groq_api_key",  "").strip()
        nim_key  = cfg.get("nvidia_api_key", "").strip()
        if groq_key and groq_key not in ("", "YOUR_GROQ_KEY_HERE"):
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
            model  = cfg.get("groq_model", "llama-3.3-70b-versatile")
        elif nim_key:
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nim_key)
            model  = cfg.get("nvidia_model", "meta/llama-3.3-70b-instruct")
        else:
            return today.strftime("%Y-%m-%d")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Convert the date to YYYY-MM-DD. Return ONLY the date string."},
                {"role": "user",   "content": f"Today is {today.strftime('%Y-%m-%d')}. Convert: '{raw}'"},
            ],
            max_tokens=20, temperature=0,
        )
        result = (resp.choices[0].message.content or "").strip()
        if re.match(r"\d{4}-\d{2}-\d{2}$", result):
            return result
    except Exception:
        pass

    print(f"[Transport] Could not parse date '{raw}' — using today")
    return today.strftime("%Y-%m-%d")


# ── URL builders ──────────────────────────────────────────────────────────────

def _flight_url(origin, destination, date, return_date=None, passengers=1, cabin="economy") -> str:
    cabin_codes = {"economy":"1","premium":"2","business":"3","first":"4"}
    cc  = cabin_codes.get(cabin.lower(), "1")
    q   = f"Flights from {origin} to {destination} on {date}"
    if return_date:
        q += f" returning {return_date}"
    return (f"https://www.google.com/travel/flights?q={quote_plus(q)}"
            f"&curr=USD&cabin={cc}&adults={passengers}")


def _train_url(origin, destination, date) -> str:
    # Rome2rio is the most universal train search
    q = f"{origin} to {destination}"
    return f"https://www.rome2rio.com/s/{quote_plus(origin)}/{quote_plus(destination)}"


def _bus_url(origin, destination, date) -> str:
    return f"https://www.rome2rio.com/s/{quote_plus(origin)}/{quote_plus(destination)}"


def _taxi_url(origin, destination) -> str:
    # Google Maps driving directions
    return (f"https://www.google.com/maps/dir/{quote_plus(origin)}/{quote_plus(destination)}"
            f"/?travelmode=driving")


def _ride_url(origin, destination) -> str:
    # Uber ride estimate
    return (f"https://m.uber.com/go/product-select"
            f"?pickup={quote_plus(origin)}&destination={quote_plus(destination)}")


def _car_rental_url(location, date, return_date=None) -> str:
    q = f"car rental {location} {date}"
    return f"https://www.google.com/travel/search?q={quote_plus(q)}"


def _ferry_url(origin, destination, date) -> str:
    return f"https://www.rome2rio.com/s/{quote_plus(origin)}/{quote_plus(destination)}"


def _rome2rio_url(origin, destination) -> str:
    """Universal multi-modal transport — shows all options (flight/train/bus/ferry)."""
    return f"https://www.rome2rio.com/s/{quote_plus(origin)}/{quote_plus(destination)}"


def _google_maps_transit_url(origin, destination) -> str:
    return (f"https://www.google.com/maps/dir/{quote_plus(origin)}/{quote_plus(destination)}"
            f"/?travelmode=transit")


# ── Public entry point ────────────────────────────────────────────────────────

def transport_finder(
    parameters: dict,
    player=None,
    speak=None,
    response=None,
    session_memory=None,
) -> str:
    """
    Find any type of transport between two places and open results in the browser.

    parameters:
        mode        : flight | train | bus | taxi | ride | car_rental | ferry | any
                      (default: any — uses Rome2rio to show all options)
        origin      : departure city / address
        destination : arrival city / address
        date        : departure date (natural language or YYYY-MM-DD)
        return_date : return date for round trips (optional)
        passengers  : number of passengers (default: 1)
        cabin       : economy | premium | business | first (flights only)
        save        : save results to Desktop text file
    """
    params      = parameters or {}
    mode        = params.get("mode",        "any").lower().strip()
    origin      = params.get("origin",      "").strip()
    destination = params.get("destination", "").strip()
    date_raw    = params.get("date",        "").strip()
    return_raw  = params.get("return_date", "").strip()
    passengers  = max(1, int(params.get("passengers", 1)))
    cabin       = params.get("cabin",       "economy").strip().lower()
    save        = bool(params.get("save",   False))

    if not origin:
        return "Please provide an origin (departure location), boss."
    if not destination:
        return "Please provide a destination, boss."

    date        = _parse_date(date_raw) if date_raw else datetime.now().strftime("%Y-%m-%d")
    return_date = _parse_date(return_raw) if return_raw else None

    if player:
        player.write_log(f"[Transport] {mode}: {origin} → {destination} on {date}")

    print(f"[Transport] {mode}: {origin} → {destination} | {date} | {passengers} pax")

    # ── Build the right URL based on mode ────────────────────────────────────
    url      = ""
    mode_str = ""

    if mode in ("flight", "flights", "fly", "plane", "air"):
        url      = _flight_url(origin, destination, date, return_date, passengers, cabin)
        mode_str = "flight"

    elif mode in ("train", "rail", "railway"):
        url      = _train_url(origin, destination, date)
        mode_str = "train"
        # Also open Google Maps transit
        _open_url(_google_maps_transit_url(origin, destination))
        time.sleep(0.4)

    elif mode in ("bus", "coach"):
        url      = _bus_url(origin, destination, date)
        mode_str = "bus"

    elif mode in ("taxi", "cab", "car"):
        url      = _taxi_url(origin, destination)
        mode_str = "taxi / driving"

    elif mode in ("ride", "uber", "bolt", "rideshare", "ride-share"):
        url      = _ride_url(origin, destination)
        mode_str = "ride"
        # Also open Bolt as alternative
        bolt_url = f"https://bolt.eu/en/?pickup={quote_plus(origin)}&destination={quote_plus(destination)}"
        _open_url(bolt_url)
        time.sleep(0.4)

    elif mode in ("car_rental", "car rental", "rent", "rental"):
        url      = _car_rental_url(origin, date, return_date)
        mode_str = "car rental"

    elif mode in ("ferry", "boat", "ship"):
        url      = _ferry_url(origin, destination, date)
        mode_str = "ferry"

    else:
        # "any" or unknown — use Rome2rio (shows ALL modes: flight, train, bus, ferry, drive)
        url      = _rome2rio_url(origin, destination)
        mode_str = "all transport options"
        # Also open Google Maps transit
        _open_url(_google_maps_transit_url(origin, destination))
        time.sleep(0.4)

    # Open the main URL
    _open_url(url)

    # Build spoken response
    date_spoken = datetime.strptime(date, "%Y-%m-%d").strftime("%B %d") if date else "your date"
    ret_spoken  = f" returning {datetime.strptime(return_date, '%Y-%m-%d').strftime('%B %d')}" if return_date else ""
    pax_spoken  = f" for {passengers} passenger{'s' if passengers > 1 else ''}" if passengers > 1 else ""

    spoken = (
        f"I've opened {mode_str} options from {origin} to {destination} "
        f"on {date_spoken}{ret_spoken}{pax_spoken} in your browser, boss."
    )

    if speak:
        speak(spoken)

    # Optionally save a text note to Desktop
    if save:
        ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname   = f"transport_{origin}_{destination}_{ts}.txt".replace(" ", "_")
        fpath   = Path.home() / "Desktop" / fname
        content = (
            f"JARVIS — Transport Search\n{'─'*50}\n"
            f"Mode        : {mode_str}\n"
            f"From        : {origin}\n"
            f"To          : {destination}\n"
            f"Date        : {date}{(chr(10) + 'Return      : ' + return_date) if return_date else ''}\n"
            f"Passengers  : {passengers}\n"
            f"Searched at : {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"URL         : {url}\n"
        )
        fpath.write_text(content, encoding="utf-8")
        try:
            subprocess.Popen(["notepad.exe", str(fpath)])
        except Exception:
            pass
        spoken += f" Results saved to Desktop: {fpath.name}"

    return spoken


# ── Backwards-compatibility alias ─────────────────────────────────────────────
def flight_finder(parameters: dict, player=None, speak=None, response=None, session_memory=None) -> str:
    """Legacy alias — routes to transport_finder with mode=flight."""
    if "mode" not in (parameters or {}):
        parameters = dict(parameters or {})
        parameters["mode"] = "flight"
    return transport_finder(parameters, player=player, speak=speak)
