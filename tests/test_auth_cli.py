from typer.testing import CliRunner
from contextlib import contextmanager

import harvest.cli as cli
import harvest.config as config_module
from harvest.config import AppConfig


runner = CliRunner()


def test_auth_saves_key_and_reports_provider(monkeypatch, tmp_path) -> None:
    config = AppConfig(provider="deepseek", data_dir=tmp_path)
    captured: dict[str, str] = {}
    secrets_path = tmp_path / "secrets.env"

    def fake_save(name: str, value: str) -> None:
        captured.update(name=name, value=value)
        secrets_path.write_text(f"{name}={value}\n", encoding="utf-8")

    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "sk-deepseek-test")
    monkeypatch.setattr(cli, "save_api_key", fake_save)
    monkeypatch.setattr(cli, "get_api_key_with_source", lambda config: ("sk-deepseek-test", "secrets_file"))

    result = runner.invoke(cli.app, ["auth"])

    assert result.exit_code == 0, result.output
    assert captured == {"name": "DEEPSEEK_API_KEY", "value": "sk-deepseek-test"}
    assert "deepseek" in result.output
    assert "API Key" in result.output
    assert "已保存" in result.output


def test_test_launcher_can_isolate_keyring_service(monkeypatch) -> None:
    calls = []

    class FakeKeyring:
        @staticmethod
        def set_password(service, name, value):
            calls.append((service, name, value))

    monkeypatch.setenv("HARVEST_KEYRING_SERVICE", "harvest-isolated-test")
    monkeypatch.setattr(config_module, "keyring", FakeKeyring())

    config_module.save_api_key("DEEPSEEK_API_KEY", "secret")

    assert calls == [("harvest-isolated-test", "DEEPSEEK_API_KEY", "secret")]


def test_first_run_can_use_key_in_memory_when_keyring_is_unavailable(monkeypatch) -> None:
    config = AppConfig(provider="deepseek")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: "temporary-secret")
    monkeypatch.setattr(
        cli,
        "save_api_key",
        lambda name, value: (_ for _ in ()).throw(RuntimeError("系统凭据库不可用")),
    )

    key = cli._prompt_api_key(config, allow_session_only=True)

    assert key == "temporary-secret"


def test_ai_status_uses_animated_dots_and_explains_wait(monkeypatch) -> None:
    captured = {}

    @contextmanager
    def fake_status(message, *, spinner):
        captured.update(message=message, spinner=spinner)
        yield

    monkeypatch.setattr(cli.console, "status", fake_status)

    with cli._ai_status("正在调用 AI"):
        pass

    assert captured["spinner"] == "dots"
    assert "正在调用 AI" in captured["message"]
    assert "可能需要几十秒" in captured["message"]
