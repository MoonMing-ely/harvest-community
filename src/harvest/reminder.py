from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


SERVICE_NAME = "harvest-reminder.service"
TIMER_NAME = "harvest-reminder.timer"
WINDOWS_TASK_NAME = "Harvest Daily Reminder"
MACOS_LABEL = "io.harvest.reminder"


def executable_args() -> list[str]:
    located = shutil.which("harvest")
    if located:
        return [located]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "harvest"]


def service_text(command: str | None = None) -> str:
    command = command or shlex.join([*executable_args(), "notify"])
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
    return "\n".join(
        [
            "[Unit]",
            "Description=Daily Harvest reminder",
            "",
            "[Timer]",
            f"OnCalendar=*-*-* {reminder_time}:00",
            "AccuracySec=1min",
            "Unit=harvest-reminder.service",
            "",
            "[Install]",
            "WantedBy=timers.target",
            "",
        ]
    )


def launchd_text(reminder_time: str, command: str | None = None) -> str:
    hour, minute = reminder_time.split(":")
    parts = (shlex.split(command) if command else executable_args()) + ["notify"]
    arguments = "\n".join(f"        <string>{part}</string>" for part in parts)
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
    parts = (shlex.split(command, posix=False) if command else executable_args()) + ["notify"]
    return [
        "schtasks",
        "/Create",
        "/SC",
        "DAILY",
        "/ST",
        reminder_time,
        "/TN",
        WINDOWS_TASK_NAME,
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
        subprocess.run(["notify-send", "Daily Harvest", "到自然断点后，运行 harvest daily。"], check=True)
    elif system == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'display notification "到自然断点后，运行 harvest daily。" with title "Daily Harvest"'],
            check=True,
        )
    elif system == "Windows":
        script = (
            "$ws=New-Object -ComObject WScript.Shell;"
            "$ws.Popup('到自然断点后，运行 harvest daily。',10,'Daily Harvest',64)"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True)
    else:
        raise OSError(f"暂不支持的系统：{system}")
