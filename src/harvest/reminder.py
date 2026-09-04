from __future__ import annotations

import platform
import re
import shlex
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path


SERVICE_NAME = "harvest-reminder.service"
TIMER_NAME = "harvest-reminder.timer"
WINDOWS_TASK_NAME = "Harvest Daily Reminder"
MACOS_LABEL = "io.harvest.reminder"
REMINDER_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")
REMINDER_GRACE_MINUTES = 180


def _validate_reminder_time(reminder_time: str) -> str:
    if REMINDER_TIME_PATTERN.fullmatch(reminder_time) is None:
        raise ValueError("提醒时间格式应为 HH:MM")
    return reminder_time


def _validate_command_parts(parts: list[str]) -> list[str]:
    if not parts or any(
        not part or any(not character.isprintable() for character in part)
        for part in parts
    ):
        raise ValueError("提醒命令包含无效控制字符")
    return parts


def reminder_target(
    reminder_time: str,
    *,
    now: datetime | None = None,
    grace_minutes: int = REMINDER_GRACE_MINUTES,
) -> date | None:
    """Return the report date due for a reminder, within a short catch-up window."""
    reminder_time = _validate_reminder_time(reminder_time)
    if grace_minutes < 0:
        raise ValueError("补提醒窗口不能为负数")
    current = now or datetime.now().astimezone()
    hour, minute = (int(part) for part in reminder_time.split(":"))
    scheduled_today = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for scheduled in (scheduled_today, scheduled_today - timedelta(days=1)):
        elapsed = current - scheduled
        if timedelta(0) <= elapsed <= timedelta(minutes=grace_minutes):
            return scheduled.date()
    return None


def executable_args() -> list[str]:
    located = shutil.which("harvest")
    if located:
        return [located]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "harvest"]


def service_text(command: str | None = None) -> str:
    if command is None:
        command = shlex.join(_validate_command_parts([*executable_args(), "notify"]))
    elif any(not character.isprintable() for character in command):
        raise ValueError("提醒命令包含无效控制字符")
    return "\n".join(
        [
            "[Unit]",
            "Description=Harvest evening reminder",
            "",
            "[Service]",
            "Type=oneshot",
            f"ExecStart={command}",
            "",
        ]
    )


def timer_text(reminder_time: str) -> str:
    reminder_time = _validate_reminder_time(reminder_time)
    return "\n".join(
        [
            "[Unit]",
            "Description=Daily Harvest reminder",
            "",
            "[Timer]",
            f"OnCalendar=*-*-* {reminder_time}:00",
            "Persistent=true",
            "AccuracySec=1min",
            "Unit=harvest-reminder.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def launchd_text(reminder_time: str, command: str | None = None) -> str:
    reminder_time = _validate_reminder_time(reminder_time)
    hour, minute = reminder_time.split(":")
    parts = _validate_command_parts((shlex.split(command) if command else executable_args()) + ["notify"])
    arguments = "\n".join(f"        <string>{escape(part)}</string>" for part in parts)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>{MACOS_LABEL}</string>
    <key>ProgramArguments</key><array>
{arguments}
    </array>
    <key>StartCalendarInterval</key><dict>
        <key>Hour</key><integer>{int(hour)}</integer>
        <key>Minute</key><integer>{int(minute)}</integer>
    </dict>
</dict></plist>
"""


def windows_task_command(reminder_time: str, command: str | None = None) -> list[str]:
    reminder_time = _validate_reminder_time(reminder_time)
    parts = _validate_command_parts(
        (shlex.split(command, posix=False) if command else executable_args()) + ["notify"]
    )
    return [
        "schtasks",
        "/Create",
        "/SC",
        "DAILY",
        "/ST",
        reminder_time,
        "/TN",
        WINDOWS_TASK_NAME,
        "/IT",
        "/TR",
        subprocess.list2cmdline(parts),
        "/F",
    ]


def install_reminder(reminder_time: str, *, run_command: bool = True, system: str | None = None) -> tuple[Path, ...]:
    system = system or platform.system()
    if system == "Linux":
        root = Path.home() / ".config" / "systemd" / "user"
        root.mkdir(parents=True, exist_ok=True)
        service = root / SERVICE_NAME
        timer = root / TIMER_NAME
        service.write_text(service_text(), encoding="utf-8")
        timer.write_text(timer_text(reminder_time), encoding="utf-8")
        if run_command:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", TIMER_NAME], check=True)
        return service, timer
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(launchd_text(reminder_time), encoding="utf-8")
        if run_command:
            subprocess.run(["launchctl", "unload", str(path)], check=False)
            subprocess.run(["launchctl", "load", str(path)], check=True)
        return (path,)
    if system == "Windows":
        if run_command:
            subprocess.run(windows_task_command(reminder_time), check=True)
        return ()
    raise OSError(f"暂不支持的系统：{system}")


def remove_reminder(*, run_command: bool = True, system: str | None = None) -> None:
    system = system or platform.system()
    if system == "Linux":
        root = Path.home() / ".config" / "systemd" / "user"
        if run_command:
            subprocess.run(["systemctl", "--user", "disable", "--now", TIMER_NAME], check=False)
        for path in (root / SERVICE_NAME, root / TIMER_NAME):
            if path.exists():
                path.unlink()
        if run_command:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    elif system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        if run_command:
            subprocess.run(["launchctl", "unload", str(path)], check=False)
        if path.exists():
            path.unlink()
    elif system == "Windows" and run_command:
        subprocess.run(["schtasks", "/Delete", "/TN", WINDOWS_TASK_NAME, "/F"], check=False)


def timer_status(*, system: str | None = None) -> tuple[bool, str]:
    system = system or platform.system()
    if system == "Linux":
        if shutil.which("systemctl") is None:
            return False, "未找到 systemctl"
        result = subprocess.run(
            ["systemctl", "--user", "is-enabled", TIMER_NAME], capture_output=True, text=True, check=False
        )
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"
        return path.exists(), str(path)
    if system == "Windows":
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", WINDOWS_TASK_NAME], capture_output=True, text=True, check=False
        )
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    return False, f"暂不支持的系统：{system}"


def send_notification(*, system: str | None = None) -> None:
    system = system or platform.system()
    if system == "Linux":
        subprocess.run(
            [
                "notify-send",
                "--app-name=Harvest",
                "--urgency=normal",
                "--icon=appointment-soon",
                "Daily Harvest",
                "今天的日志还没有生成。到自然断点后运行 harvest。",
            ],
            check=True,
        )
    elif system == "Darwin":
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "今天的日志还没有生成。到自然断点后运行 harvest。" '
                'with title "Daily Harvest"',
            ],
            check=True,
        )
    elif system == "Windows":
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null;"
            "$xml=New-Object Windows.Data.Xml.Dom.XmlDocument;"
            "$xml.LoadXml('<toast duration=\"short\"><visual><binding template=\"ToastGeneric\">"
            "<text>Daily Harvest</text><text>今天的日志还没有生成。到自然断点后运行 harvest。</text>"
            "</binding></visual><audio silent=\"true\"/></toast>');"
            "$toast=New-Object Windows.UI.Notifications.ToastNotification $xml;"
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('Harvest').Show($toast)"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], check=True)
    else:
        raise OSError(f"暂不支持的系统：{system}")
