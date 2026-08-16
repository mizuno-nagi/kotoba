import re
import subprocess
import sys
from pathlib import Path


TASK_NAME = "JapanNewsStudyDaily"
SCHEDULE_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def validate_schedule_time(value):
    value = str(value or "").strip()
    return value if SCHEDULE_PATTERN.fullmatch(value) else ""


def build_task_command():
    if getattr(sys, "frozen", False):
        parts = [sys.executable, "--scheduled-job"]
    else:
        script = Path(__file__).resolve().parent / "desktop_app.py"
        parts = [sys.executable, str(script), "--scheduled-job"]
    return " ".join(f'"{part}"' for part in parts)


def _run_schtasks(args):
    proc = subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(detail or f"schtasks failed with code {proc.returncode}")
    return (proc.stdout or "").strip()


def task_exists():
    proc = subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode == 0


def create_or_update_task(schedule_time):
    schedule_time = validate_schedule_time(schedule_time)
    if not schedule_time:
        raise ValueError("定时时间必须是 HH:MM 格式")
    command = build_task_command()
    _run_schtasks(
        [
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/TR",
            command,
            "/SC",
            "DAILY",
            "/ST",
            schedule_time,
        ]
    )


def delete_task():
    _run_schtasks(["/Delete", "/F", "/TN", TASK_NAME])
