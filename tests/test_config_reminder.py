from pathlib import Path

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
from harvest.reminder import launchd_text, service_text, timer_text, windows_task_command


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
    assert secret_path.stat().st_mode & 0o777 == 0o600


def test_reminder_is_non_intrusive_and_not_persistent() -> None:
    service = service_text("/opt/harvest notify")
    timer = timer_text("22:00")
    assert "/opt/harvest notify" in service
    assert "OnCalendar=*-*-* 22:00:00" in timer
    assert "Persistent=true" not in timer


def test_cross_platform_reminder_definitions() -> None:
    assert "<integer>22</integer>" in launchd_text("22:15", "/opt/harvest")
    command = windows_task_command("22:15", "C:\\Harvest\\harvest.exe")
    assert command[0] == "schtasks"
    assert "22:15" in command
    assert "notify" in command[-2]


def test_report_profile_is_created_private_and_readable(tmp_path) -> None:
    path = tmp_path / "report-profile.md"
    ensure_report_profile(path)

    assert "报告" in load_report_profile(path)
    assert path.stat().st_mode & 0o777 == 0o600
