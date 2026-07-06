# actions/weather_report.py
# Real-time weather via wttr.in — free, no API key needed.
# Returns structured spoken text + raw JSON for tool results.

import json
import requests
from pathlib import Path


def _fmt_weather(data: dict, city: str) -> str:
    """Format wttr.in JSON into a natural spoken weather report."""
    try:
        cc  = data["current_condition"][0]
        w   = data["weather"][0]

        desc     = cc["weatherDesc"][0]["value"]
        temp_c   = cc["temp_C"]
        temp_f   = cc["temp_F"]
        feels_c  = cc["FeelsLikeC"]
        humidity = cc["humidity"]
        wind_kmh = cc["windspeedKmph"]
        vis_km   = cc.get("visibility", "N/A")

        max_c = w["maxtempC"]
        min_c = w["mintempC"]
        max_f = w["maxtempF"]
        min_f = w["mintempF"]

        return (
            f"Current weather in {city}: {desc}. "
            f"Temperature {temp_c}°C ({temp_f}°F), feels like {feels_c}°C. "
            f"High of {max_c}°C ({max_f}°F), low of {min_c}°C ({min_f}°F). "
            f"Humidity {humidity}%, wind {wind_kmh} km/h, visibility {vis_km} km."
        )
    except (KeyError, IndexError, TypeError) as e:
        return f"Weather data received but could not be parsed: {e}"


def _fmt_forecast(data: dict, city: str, days: int = 3) -> str:
    """Format a multi-day forecast from wttr.in JSON."""
    try:
        lines = [f"{days}-day forecast for {city}:"]
        for w in data["weather"][:days]:
            date    = w["date"]
            desc    = w["hourly"][4]["weatherDesc"][0]["value"]  # midday
            max_c   = w["maxtempC"]
            min_c   = w["mintempC"]
            lines.append(f"  {date}: {desc}, {min_c}°C – {max_c}°C")
        return "\n".join(lines)
    except Exception as e:
        return f"Forecast data unavailable: {e}"


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    """
    Fetches real weather data from wttr.in.
    parameters:
        city     : city name (required)
        forecast : bool — include 3-day forecast (default: False)
        units    : 'metric' | 'imperial' (default: metric)
    """
    params   = parameters or {}
    city     = params.get("city", "").strip()
    forecast = str(params.get("forecast", "false")).lower() in ("true", "1", "yes")
    units    = params.get("units", "metric").lower()

    if not city:
        msg = "Please tell me which city you want the weather for, boss."
        if player:
            player.write_log(f"JARVIS: {msg}")
        return msg

    if player:
        player.write_log(f"[weather] Fetching weather for {city}...")

    try:
        url  = f"https://wttr.in/{requests.utils.quote(city)}?format=j1"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "JARVIS/1.0"})
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        msg = f"Weather service timed out for {city}, boss. Try again in a moment."
        if player: player.write_log(f"JARVIS: {msg}")
        return msg
    except Exception as e:
        msg = f"Could not fetch weather for {city}, boss: {e}"
        if player: player.write_log(f"JARVIS: {msg}")
        return msg

    report = _fmt_weather(data, city)

    if forecast:
        report += "\n\n" + _fmt_forecast(data, city, days=3)

    if player:
        player.write_log(f"JARVIS: {report}")

    return report
