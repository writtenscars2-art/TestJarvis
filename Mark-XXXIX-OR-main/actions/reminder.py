"""
reminder.py — Smart reminder system for JARVIS.

Features:
  - Set reminders with natural date/time expressions
  - List all pending JARVIS reminders
  - Delete / cancel a reminder by name or keyword
  - Snooze a reminder (add N minutes)
  - Toast notification + sound + SAPI voice on trigger
  - Uses Windows Task Scheduler (schtasks) — no external deps
"""

import os
import re
import subprocess
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


API_CONFIG_PATH = _get_base_dir() / "config" / "api_keys.json"

_TASK_PREFIX = "JARVISReminder_"


# ── Date / time parsing ───────────────────────────────────────────────────────

_MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}


def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
    """Parse date + time strings into a datetime. Returns None on failure."""
    now = datetime.now()

    # ── Parse time ────────────────────────────────────────────────────────
    t = None
    time_lower = (time_str or "").lower().strip()

    # Try standard formats
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I %p", "%I%p"):
        try:
            t = datetime.strptime(time_lower, fmt)
            break
        except ValueError:
            pass

    # Natural time: "3pm", "3:30pm", "15:00", "noon", "midnight"
    if t is None:
        if "noon" in time_lower:
            t = now.replace(hour=12, minute=0)
        elif "midnight" in time_lower:
            t = now.replace(hour=0, minute=0)
        else:
            m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", time_lower)
            if m:
                hour   = int(m.group(1))
                minute = int(m.group(2) or 0)
                ampm   = m.group(3)
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    if t is None:
        return None

    hour, minute = t.hour, t.minute

    # ── Parse date ────────────────────────────────────────────────────────
    date_lower = (date_str or "").lower().strip()

    if not date_lower or date_lower in ("today", "tonight"):
        d = now.date()
    elif date_lower == "tomorrow":
        d = (now + timedelta(days=1)).date()
    elif date_lower == "day after tomorrow":
        d = (now + timedelta(days=2)).date()
    else:
        m2 = re.search(r"in\s+(\d+)\s+days?", date_lower)
        if m2:
            d = (now + timedelta(days=int(m2.group(1)))).date()
        else:
            # Try standard date formats
            parsed = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y",
                        "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y",
                        "%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = datetime.strptime(date_lower, fmt).date()
                    break
                except ValueError:
                    pass

            if parsed is None:
                # "15 March" or "March 15" without year
                day_m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?", date_lower)
                for month_name, month_num in _MONTH_MAP.items():
                    if month_name in date_lower and day_m:
                        day  = int(day_m.group(1))
                        year = now.year
                        candidate = datetime(year, month_num, day).date()
                        if candidate < now.date():
                            year += 1
                        parsed = datetime(year, month_num, day).date()
                        break

            if parsed is None:
                return None
            d = parsed

    result = datetime(d.year, d.month, d.day, hour, minute, 0)

    # If the time is in the past today, assume tomorrow
    if result <= now and date_lower in ("today", "tonight", ""):
        result += timedelta(days=1)

    return result


# ── Task Scheduler helpers ────────────────────────────────────────────────────

def _get_pythonw() -> str:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        w = exe[:-10] + "pythonw.exe"
        if Path(w).exists():
            return w
    return exe


def _create_notify_script(task_name: str, message: str) -> str:
    """Write a small .pyw script that fires the reminder notification."""
    temp_dir   = os.environ.get("TEMP", "C:\\Temp")
    script_path = os.path.join(temp_dir, f"{task_name}.pyw")
    project_root = str(_get_base_dir())
    safe_msg   = message.replace('"', "'").replace("\\", "/")[:200]

    code = f'''import sys, os, time
sys.path.insert(0, r"{project_root}")

# Sound
try:
    import winsound
    for freq, dur in [(600,150),(800,150),(1000,200),(1200,300)]:
        winsound.Beep(freq, dur)
        time.sleep(0.05)
except Exception:
    pass

# Toast notification
try:
    from win10toast import ToastNotifier
    ToastNotifier().show_toast("JARVIS Reminder", "{safe_msg}", duration=20, threaded=False)
except Exception:
    pass

# SAPI voice fallback
try:
    from win32com.client import Dispatch
    sapi = Dispatch("SAPI.SpVoice")
    sapi.Rate = 1
    sapi.Speak("Reminder: {safe_msg}")
except Exception:
    pass

# Cleanup
time.sleep(2)
try:
    os.remove(__file__)
except Exception:
    pass
'''
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    return script_path


def _register_task(task_name: str, target_dt: datetime, script_path: str) -> bool:
    """Register a Windows Scheduled Task using schtasks XML."""
    temp_dir = os.environ.get("TEMP", "C:\\Temp")
    xml_path = os.path.join(temp_dir, f"{task_name}.xml")
    pythonw  = _get_pythonw()

    xml = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>JARVIS Reminder</Description></RegistrationInfo>
  <Triggers>
    <TimeTrigger>
      <StartBoundary>{target_dt.strftime("%Y-%m-%dT%H:%M:%S")}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>{pythonw}</Command>
      <Arguments>"{script_path}"</Arguments>
    </Exec>
  </Actions>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Principals>
    <Principal>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
</Task>'''

    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml)

    result = subprocess.run(
        f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F',
        shell=True, capture_output=True, text=True
    )
    try:
        os.remove(xml_path)
    except Exception:
        pass

    if result.returncode != 0:
        print(f"[Reminder] schtasks error: {result.stderr.strip()}")
        return False
    return True


def _list_reminders() -> list[dict]:
    """Return all pending JARVIS reminders from Task Scheduler."""
    result = subprocess.run(
        f'schtasks /Query /FO CSV /NH /TN "{_TASK_PREFIX}"',
        shell=True, capture_output=True, text=True
    )
    # Also try without exact match — list all and filter
    result2 = subprocess.run(
        'schtasks /Query /FO CSV /NH',
        shell=True, capture_output=True, text=True
    )
    reminders = []
    for line in result2.stdout.splitlines():
        if _TASK_PREFIX in line:
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2:
                reminders.append({
                    "name":   parts[0].strip('"').strip(),
                    "next":   parts[1].strip() if len(parts) > 1 else "",
                    "status": parts[2].strip() if len(parts) > 2 else "",
                })
    return reminders


def _delete_task(task_name: str) -> bool:
    result = subprocess.run(
        f'schtasks /Delete /TN "{task_name}" /F',
        shell=True, capture_output=True, text=True
    )
    return result.returncode == 0


# ── Public entry point ────────────────────────────────────────────────────────

def reminder(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Smart reminder system.

    parameters:
        action  : set | list | delete | snooze (default: set)
        date    : date string — "today", "tomorrow", "15 March", "2025-06-01", etc.
        time    : time string — "3pm", "15:30", "9:00 AM", "noon"
        message : reminder message text
        name    : task name / keyword for delete/snooze
        minutes : minutes to snooze (default: 10)
    """
    params  = parameters or {}
    action  = params.get("action", "set").lower().strip()
    message = params.get("message", "Reminder from JARVIS").strip()
    name_kw = params.get("name", "").strip().lower()

    if player:
        player.write_log(f"[Reminder] action={action}")

    # ── LIST ──────────────────────────────────────────────────────────────
    if action == "list":
        reminders = _list_reminders()
        if not reminders:
            return "You have no pending reminders, boss."
        lines = [f"You have {len(reminders)} pending reminder(s), boss:"]
        for i, r in enumerate(reminders, 1):
            display_name = r["name"].replace(_TASK_PREFIX, "").replace("_", " ")
            lines.append(f"  {i}. {display_name} — next: {r['next']}")
        return "\n".join(lines)

    # ── DELETE ────────────────────────────────────────────────────────────
    if action in ("delete", "cancel", "remove"):
        reminders = _list_reminders()
        if not reminders:
            return "No pending reminders to delete, boss."

        # Match by keyword in task name
        matches = [r for r in reminders if name_kw in r["name"].lower()]
        if not matches:
            # Delete most recent if no keyword given
            matches = [reminders[-1]]

        deleted = []
        for r in matches:
            if _delete_task(r["name"]):
                display = r["name"].replace(_TASK_PREFIX, "").replace("_", " ")
                deleted.append(display)

        if deleted:
            return f"Deleted reminder(s): {', '.join(deleted)}, boss."
        return "Could not delete reminder, boss."

    # ── SNOOZE ────────────────────────────────────────────────────────────
    if action == "snooze":
        minutes   = int(params.get("minutes", 10))
        reminders = _list_reminders()
        if not reminders:
            return "No pending reminders to snooze, boss."

        # Match by keyword or use most recent
        matches = [r for r in reminders if name_kw in r["name"].lower()] if name_kw else [reminders[0]]
        if not matches:
            return "No matching reminder found to snooze, boss."

        r = matches[0]
        _delete_task(r["name"])

        # Re-schedule N minutes from now
        new_dt    = datetime.now() + timedelta(minutes=minutes)
        new_name  = f"{_TASK_PREFIX}{new_dt.strftime('%Y%m%d_%H%M%S')}"
        script    = _create_notify_script(new_name, message or "Snoozed reminder")
        if _register_task(new_name, new_dt, script):
            return (f"Snoozed reminder by {minutes} minutes. "
                    f"Will fire at {new_dt.strftime('%I:%M %p')}, boss.")
        return "Could not snooze reminder, boss."

    # ── SET (default) ────────────────────────────────────────────────────
    date_raw = params.get("date", "").strip()
    time_raw = params.get("time", "").strip()

    # If no date given, assume today
    if not date_raw:
        date_raw = "today"

    # If no time given, can't set a reminder
    if not time_raw:
        return "Please tell me what time to set the reminder for, boss."

    target_dt = _parse_datetime(date_raw, time_raw)

    if target_dt is None:
        return (f"I couldn't understand that date/time, boss. "
                f"Try: 'remind me at 3pm tomorrow to {message}'")

    if target_dt <= datetime.now():
        return f"That time ({target_dt.strftime('%I:%M %p on %B %d')}) is in the past, boss."

    # Sanitise message for use in task name and script
    safe_msg  = re.sub(r"[^\w\s\-]", "", message)[:60].strip()
    slug      = re.sub(r"\s+", "_", safe_msg)[:30] or "reminder"
    task_name = f"{_TASK_PREFIX}{target_dt.strftime('%Y%m%d_%H%M%S')}_{slug}"

    script_path = _create_notify_script(task_name, message)

    if not _register_task(task_name, target_dt, script_path):
        # Clean up script on failure
        try:
            os.remove(script_path)
        except Exception:
            pass
        return "I couldn't schedule the reminder due to a system error, boss."

    if player:
        player.write_log(f"[reminder] {target_dt.strftime('%Y-%m-%d %H:%M')} — {message[:40]}")

    time_fmt = target_dt.strftime("%I:%M %p").lstrip("0")
    date_fmt = target_dt.strftime("%A, %B %d")
    today    = datetime.now().date()

    if target_dt.date() == today:
        when = f"today at {time_fmt}"
    elif target_dt.date() == today + timedelta(days=1):
        when = f"tomorrow at {time_fmt}"
    else:
        when = f"{date_fmt} at {time_fmt}"

    return f"Reminder set for {when} — \"{message}\", boss."
