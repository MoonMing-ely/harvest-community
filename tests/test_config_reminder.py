import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest

from harvest.config import (
    AppConfig,
    ensure_report_profile,
    get_api_key,
    get_api_key_with_source,
    load_config,
    load_report_profile,
    save_api_key,
    save_config,
)
from harvest.reminder import (
    launchd_text,
    reminder_target,
    send_notification,
    service_text,
    timer_text,
    windows_task_command,
)


def test_config_and_secret_round_trip(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    secret_path = tmp_path / "secrets.env"
    config = AppConfig(provider="openai", data_dir=tmp_path / "records", reminder_time="22:00")
    save_config(config, config_path)
    loaded = load_config(config_path)
    assert loaded.provider == "openai"
    assert loaded.data_dir == tmp_path / "records"

    save_api_key("OPENAI_API_KEY", "sk-test", secret_path)
    assert get_api_key(loaded, secret_path) == "sk-test"
    assert get_api_key_with_source(loaded, secret_path) == ("sk-test", "secrets_file")
    if os.name != "nt":
        assert secret_path.stat().st_mode & 0o777 == 0o600


def test_config_strings_cannot_inject_toml_assignments(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    data_dir = tmp_path / 'records\nprovider = "openai"'

    save_config(AppConfig(provider="deepseek", data_dir=data_dir), config_path)

    serialized = config_path.read_text(encoding="utf-8")
    loaded = load_config(config_path)
    assert '\\nprovider = \\"openai\\"' in serialized
    assert loaded.provider == "deepseek"
    assert loaded.data_dir == data_dir


@pytest.mark.parametrize("api_key", ["", "secret\nOPENAI_API_KEY=stolen", "secret value", "secret\x1b"])
def test_api_key_rejects_whitespace_and_control_characters(tmp_path, api_key) -> None:
    with pytest.raises(ValueError, match="API Key 格式无效"):
        save_api_key("OPENAI_API_KEY", api_key, tmp_path / "secrets.env")


def test_reminder_is_non_intrusive_and_catches_up_after_downtime() -> None:
    service = service_text("/opt/harvest notify")
    timer = timer_text("22:00")
    assert "/opt/harvest notify" in service
    assert "OnCalendar=*-*-* 22:00:00" in timer
    assert "Persistent=true" in timer


def test_cross_platform_reminder_definitions() -> None:
    assert "<integer>22</integer>" in launchd_text("22:15", "/opt/harvest")
    command = windows_task_command("22:15", "C:\\Harvest\\harvest.exe")
    assert command[0] == "schtasks"
    assert "22:15" in command
    assert "/IT" in command
    assert "notify" in command[-2]


@pytest.mark.parametrize(
    ("now", "reminder_time", "expected"),
    [
        (datetime(2026, 9, 4, 21, 59), "22:00", None),
        (datetime(2026, 9, 4, 22, 0), "22:00", date(2026, 9, 4)),
        (datetime(2026, 9, 4, 23, 30), "22:00", date(2026, 9, 4)),
        (datetime(2026, 9, 5, 1, 0), "23:00", date(2026, 9, 4)),
        (datetime(2026, 9, 5, 9, 0), "22:00", None),
    ],
)
def test_reminder_target_uses_a_bounded_catch_up_window(now, reminder_time, expected) -> None:
    assert reminder_target(reminder_time, now=now) == expected


@pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
def test_notifications_use_non_modal_system_notification_centers(system, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: calls.append(command))

    send_notification(system=system)

    command = calls[0]
    joined = " ".join(command)
    if system == "Linux":
        assert command[0] == "notify-send"
        assert "--urgency=normal" in command
        assert "zenity" not in joined
    elif system == "Darwin":
        assert command[0] == "osascript"
        assert "display notification" in joined
        assert "display dialog" not in joined
    else:
        assert command[0] == "powershell.exe"
        assert "ToastNotificationManager" in joined
        assert "silent=\"true\"" in joined
        assert "Popup(" not in joined


def test_launchd_escapes_executable_path_as_xml() -> None:
    plist = launchd_text("22:15", '"/Applications/Harvest & Notes/harvest"')

    assert "Harvest &amp; Notes" in plist
    assert "Harvest & Notes" not in plist


@pytest.mark.parametrize("reminder_time", ["22:15\nOnCalendar=hourly", "24:00", "9:00"])
def test_reminder_definitions_reject_invalid_time(reminder_time) -> None:
    with pytest.raises(ValueError, match="HH:MM"):
        timer_text(reminder_time)
    with pytest.raises(ValueError, match="HH:MM"):
        launchd_text(reminder_time)
    with pytest.raises(ValueError, match="HH:MM"):
        windows_task_command(reminder_time)


def test_reminder_definitions_reject_command_control_characters() -> None:
    with pytest.raises(ValueError, match="控制字符"):
        service_text("/opt/harvest notify\nEnvironment=INJECTED=1")
    with pytest.raises(ValueError, match="控制字符"):
        launchd_text("22:15", '"/Applications/Harvest\x00/harvest"')


def test_report_profile_is_created_private_and_readable(tmp_path) -> None:
    path = tmp_path / "report-profile.md"
    ensure_report_profile(path)

    assert "报告" in load_report_profile(path)
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
