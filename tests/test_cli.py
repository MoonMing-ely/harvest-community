from datetime import date

from typer.testing import CliRunner

import harvest.cli as cli
from harvest.config import AppConfig
from harvest.models import ContextSnapshot, DailyAnalysis, NetworkTrace, ProjectSuggestion, Usage
from harvest.providers import ProviderError
from harvest.service import make_pending
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


runner = CliRunner()


class FakeProvider:
    def generate(self, *, instructions, input_text, output_type, schema_name):
        return DailyAnalysis(report=sample_harvest(), project_suggestions=[]), Usage(
            input_tokens=10, output_tokens=5, total_tokens=15
        )


class TracedFakeProvider:
    def generate_traced(self, *, schema_name, output_type, **kwargs):
        usage = Usage(input_tokens=3, output_tokens=1, total_tokens=4)
        trace = NetworkTrace(
            endpoint="https://example.test/responses",
            provider="deepseek",
            model="test-model",
            schema_name=schema_name,
            status_code=200,
            elapsed_ms=8,
            request_payload={"input": "连通性检查"},
            response_payload={"status": "completed"},
            usage=usage,
        )
        return output_type(status="ok"), usage, trace


def _prepare_doctor(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    config_path = tmp_path / "config.toml"
    config_path.write_text("provider = 'deepseek'\n", encoding="utf-8")
    monkeypatch.setattr(cli, "CONFIG_PATH", config_path)
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(cli, "get_api_key_with_source", lambda config: ("secret", "测试凭据"))
    monkeypatch.setattr(cli, "timer_status", lambda: (True, "测试提醒"))
    monkeypatch.setattr(cli, "build_provider", lambda config: TracedFakeProvider())


def test_doctor_api_test_hides_raw_details_by_default(tmp_path, monkeypatch) -> None:
    _prepare_doctor(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["doctor", "--api-test"])

    assert result.exit_code == 0, result.output
    assert "网络与格式检查" in result.output
    assert '"request"' not in result.output
    assert "可能包含你输入的个人内容" not in result.output


def test_doctor_details_is_explicit_and_warns_about_personal_content(tmp_path, monkeypatch) -> None:
    _prepare_doctor(tmp_path, monkeypatch)

    result = runner.invoke(cli.app, ["doctor", "--api-test", "--details"])

    assert result.exit_code == 0, result.output
    assert "可能包含你输入的个人内容" in result.output
    assert '"request"' in result.output
    assert '"Authorization"' not in result.output
    assert "secret" not in result.output


def test_doctor_details_requires_api_test() -> None:
    result = runner.invoke(cli.app, ["doctor", "--details"])

    assert result.exit_code == 2
    assert "harvest doctor --api-test --details" in result.output


def empty_snapshot() -> ContextSnapshot:
    return ContextSnapshot(active_projects=[], recent_progress=[], last_core_target=None, current_state_hints=[])


def test_daily_cli_saves_confirmed_report_without_raw_answers(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: FakeProvider())
    monkeypatch.setattr(cli, "_snapshot", lambda config, storage, target: empty_snapshot())

    result = runner.invoke(
        cli.app,
        ["daily", "--date", "2026-09-01"],
        input="做算法\n完成一个证明\n理解了净票数\n很累\n吃饭喝水正常\n写完算法\n\n",
    )

    assert result.exit_code == 0, result.output
    assert storage.load_daily(date(2026, 9, 1)) is not None
    assert storage.load_pending(date(2026, 9, 1)) is None
    assert "做算法" not in storage.daily_json_path(date(2026, 9, 1)).read_text(encoding="utf-8")


def test_daily_cli_keeps_pending_when_provider_fails(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: (_ for _ in ()).throw(ProviderError("offline")))
    monkeypatch.setattr(cli, "_snapshot", lambda config, storage, target: empty_snapshot())

    result = runner.invoke(
        cli.app,
        ["daily", "--date", "2026-09-02"],
        input="做算法\n\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    pending = storage.load_pending(date(2026, 9, 2))
    assert pending is not None
    assert pending.answers["meaningful_moment"] == "做算法"
    assert pending.last_error == "offline"


def test_daily_cli_retries_bad_utf8_line_and_preserves_earlier_answers(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: (_ for _ in ()).throw(ProviderError("offline")))
    monkeypatch.setattr(cli, "_snapshot", lambda config, storage, target: empty_snapshot())
    responses = iter(
        [
            "画了两个小时",
            UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
            "算法题有进展",
            "学会了一种方法",
            "很投入",
            "正常吃饭喝水",
            "继续做算法",
        ]
    )

    def prompt(*args, **kwargs):
        response = next(responses)
        if isinstance(response, Exception):
            saved = storage.load_pending(date(2026, 9, 4))
            assert saved is not None
            assert saved.answers == {"meaningful_moment": "画了两个小时"}
            raise response
        return response

    monkeypatch.setattr(cli.typer, "prompt", prompt)
    result = runner.invoke(cli.app, ["daily", "--date", "2026-09-04"])

    assert result.exit_code == 0, result.output
    assert "此前答案仍已保存" in result.output
    pending = storage.load_pending(date(2026, 9, 4))
    assert pending is not None
    assert pending.answers["inner_experience"] == "算法题有进展"
    assert pending.last_error == "offline"


def test_daily_cli_continues_incomplete_pending(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    storage.save_pending(
        make_pending(date(2026, 9, 5), {"meaningful_moment": "已经保存的第一题"})
    )
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: FakeProvider())
    monkeypatch.setattr(cli, "_snapshot", lambda config, storage, target: empty_snapshot())

    result = runner.invoke(
        cli.app,
        ["daily", "--date", "2026-09-05"],
        input="继续项目\n完成一部分\n很投入\n正常吃饭\n继续下一步\n\n",
    )

    assert result.exit_code == 0, result.output
    assert storage.load_daily(date(2026, 9, 5)) is not None


def test_daily_cli_applies_confirmed_project_suggestion(tmp_path, monkeypatch) -> None:
    class SuggestingProvider:
        def generate(self, **kwargs):
            return DailyAnalysis(
                report=sample_harvest(),
                project_suggestions=[
                    ProjectSuggestion(
                        action="add",
                        project_name="算法基础",
                        reason="需要跨多天继续学习",
                        next_step="完成摩尔投票实现",
                    )
                ],
            ), Usage()

    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: SuggestingProvider())
    monkeypatch.setattr(cli, "_snapshot", lambda config, storage, target: empty_snapshot())

    result = runner.invoke(
        cli.app,
        ["daily", "--date", "2026-09-03"],
        input="做算法\n\n理解了抵消\n很投入\n吃饭喝水正常\n完成代码\n\ny\n",
    )

    assert result.exit_code == 0, result.output
    projects = storage.load_project_memory().projects
    assert len(projects) == 1
    assert projects[0].name == "算法基础"
    assert projects[0].next_step == "完成摩尔投票实现"


def test_project_suggestion_is_not_applied_by_default(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    suggestion = ProjectSuggestion(
        action="add",
        project_name="未经确认的项目",
        reason="模型建议",
    )
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))

    result = runner.invoke(cli.app, ["project", "list"], input="\n")
    assert result.exit_code == 0
    monkeypatch.setattr(cli.typer, "confirm", lambda *args, **kwargs: kwargs["default"])
    cli._confirm_project_updates([suggestion], date(2026, 9, 3), storage)

    assert storage.load_project_memory().projects == []


def test_project_commands_manage_status_without_ai(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))

    added = runner.invoke(cli.app, ["project", "add", "问卷项目", "--next-step", "调整结果页"])
    paused = runner.invoke(cli.app, ["project", "pause", "问卷项目"])
    listed = runner.invoke(cli.app, ["project", "list", "--all"])

    assert added.exit_code == 0, added.output
    assert paused.exit_code == 0, paused.output
    assert listed.exit_code == 0, listed.output
    assert "问卷项目" in listed.output
    assert "paused" in listed.output
