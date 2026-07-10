# actions/weather_report.py
# Real-time weather via wttr.in -- free, no API key needed.
# Returns structured spoken text for voice output.

import requests


def _fmt_weather(data: dict, city: str, use_imperial: bool = False) -> str:
    """Format wttr.in JSON into a natural spoken weather report."""
    try:
        cc  = data["current_condition"][0]
        w   = data["weather"][0]

        desc     = cc["weatherDesc"][0]["value"]
        humidity = cc["humidity"]
        wind_kmh = cc["windspeedKmph"]
        wind_mph = cc["windspeedMiles"]
        vis_km   = cc.get("visibility", "N/A")

        if use_imperial:
            temp     = f"{cc['temp_F']}°F"
            feels    = f"{cc['FeelsLikeF']}°F"
            high     = f"{w['maxtempF']}°F"
            low      = f"{w['mintempF']}°F"
            wind     = f"{wind_mph} mph"
        else:
            temp     = f"{cc['temp_C']}°C"
            feels    = f"{cc['FeelsLikeC']}°C"
            high     = f"{w['maxtempC']}°C"
            low      = f"{w['mintempC']}°C"
            wind     = f"{wind_kmh} km/h"

        return (
            f"Current weather in {city}: {desc}. "
            f"Temperature {temp}, feels like {feels}. "
            f"High {high}, low {low}. "
            f"Humidity {humidity}%, wind {wind}, visibility {vis_km} km."
        )
    except (KeyError, IndexError, TypeError) as e:
        return f"Weather data received but could not be parsed: {e}"


def _fmt_forecast(data: dict, city: str, days: int = 3, use_imperial: bool = False) -> str:
    """Format a multi-day forecast from wttr.in JSON."""
    try:
        lines = [f"{days}-day forecast for {city}:"]
        for w in data["weather"][:days]:
            date = w["date"]
            desc = w["hourly"][4]["weatherDesc"][0]["value"]   # midday description
            if use_imperial:
                high = f"{w['maxtempF']}°F"
                low  = f"{w['mintempF']}°F"
            else:
                high = f"{w['maxtempC']}°C"
                low  = f"{w['mintempC']}°C"
            lines.append(f"  {date}: {desc}, {low} -- {high}")
        return "\n".join(lines)
    except Exception as e:
        return f"Forecast data unavailable: {e}"


def weather_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Fetches real-time weather data from wttr.in.

    parameters:
        city     : city name (required)
        forecast : bool -- include 3-day forecast (default: False)
        units    : 'metric' | 'imperial' (default: metric)
                   imperial = Fahrenheit + mph
    """
    params       = parameters or {}
    city         = params.get("city", "").strip()
    forecast     = str(params.get("forecast", "false")).lower() in ("true", "1", "yes")
    units        = params.get("units", "metric").lower()
    use_imperial = units in ("imperial", "fahrenheit", "us", "f")

    if not city:
        return "Please tell me which city you want the weather for, boss."

    if player:
        player.write_log(f"[weather] Fetching weather for {city} ({units})...")

    try:
        # wttr.in returns both C and F in JSON regardless -- we pick at format time
        url  = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "JARVIS/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        return f"Weather service timed out for {city}, boss. Try again in a moment."
    except Exception as e:
        return f"Could not fetch weather for {city}, boss: {e}"

    report = _fmt_weather(data, city, use_imperial)

    if forecast:
        report += "\n\n" + _fmt_forecast(data, city, days=3, use_imperial=use_imperial)

    if player:
        player.write_log(f"JARVIS: {report[:120]}")

    return report
