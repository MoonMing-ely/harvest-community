import json
from datetime import date, datetime

from typer.testing import CliRunner

import harvest.cli as cli
from harvest.config import AppConfig
from harvest.models import (
    CalibrationState,
    DailyAnalysis,
    DailyQuestion,
    DailyRecord,
    NetworkTrace,
    OnboardingPending,
    OnboardingProposal,
    Usage,
)
from harvest.render import render_daily
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


runner = CliRunner()


def sample_questions() -> list[DailyQuestion]:
    return [
        DailyQuestion(id="moment", prompt="哪个片段最值得回看？", purpose="找到体验入口"),
        DailyQuestion(id="experience", prompt="当时有什么感受？", purpose="观察体验"),
        DailyQuestion(id="response", prompt="你怎样回应阻碍或选择？", purpose="观察应对"),
        DailyQuestion(id="growth", prompt="理解或判断发生了什么变化？", purpose="观察成长"),
        DailyQuestion(
            id="basic_care", prompt="吃饭、喝水、睡眠和活动怎么样？", purpose="关注基本状态", kind="wellbeing"
        ),
        DailyQuestion(id="tomorrow", prompt="明天先接上哪一步？", purpose="形成衔接", kind="tomorrow"),
    ]


class OnboardingProvider:
    def generate(self, *, output_type, **kwargs):
        if output_type is OnboardingProposal:
            return OnboardingProposal(
                profile=sample_profile().content,
                daily_questions=sample_questions(),
                rationale=["来自引导问卷"],
            ), Usage()
        raise AssertionError(output_type)

    def generate_traced(self, *, output_type, schema_name, **kwargs):
        if output_type is DailyAnalysis:
            value = DailyAnalysis(report=sample_harvest(), project_suggestions=[])
        else:
            value = output_type(status="ok")
        usage = Usage(input_tokens=10, output_tokens=5, total_tokens=15)
        trace = NetworkTrace(
            endpoint="https://example.test/responses",
            provider="deepseek",
            model="test-model",
            schema_name=schema_name,
            status_code=200,
            elapsed_ms=12,
            request_payload={"store": False},
            response_payload={"status": "completed"},
            usage=usage,
        )
        return value, usage, trace


def test_onboarding_saves_only_confirmed_profile_and_questions(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    provider = OnboardingProvider()
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "_configure_and_test_api", lambda: (config, provider))

    guided = ["1", "1", "1", "1", "1", "1", "先复现错误，再缩小输入，最后读文档确认"]
    trial = ["写了代码", "完成接口", "格式不稳定", "用最小输入定位", "正常吃饭", "补测试"]
    user_input = "\n".join([*guided, "", "1", *trial, "", "1"]) + "\n"
    result = runner.invoke(cli.app, ["onboard"], input=user_input)

    assert result.exit_code == 0, result.output
    profile = storage.load_profile()
    assert profile is not None
    assert [item.id for item in profile.daily_questions] == [item.id for item in sample_questions()]
    assert storage.all_daily_records() == []
    assert storage.load_onboarding() is None
    assert storage.load_calibration().first_daily_date is None
    assert "写了代码" not in storage.profile_path().read_text(encoding="utf-8")
    assert "测试数据已清除" in result.output
    assert "harvest profile rebuild" in result.output
    assert "harvest revise YYYY-MM-DD" in result.output
    assert "脱敏" not in result.output


def test_trial_persists_trace_summary_without_request_or_response(tmp_path) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    pending = OnboardingPending(
        date=date(2026, 9, 3),
        created_at=datetime.now(),
        proposed_profile=sample_profile().content,
        proposed_questions=sample_questions(),
        daily_answers={item.id: "包含个人体验的回答" for item in sample_questions()},
    )

    result = cli._run_trial(pending, config, OnboardingProvider(), storage)

    assert result is not None
    saved_text = storage.onboarding_path().read_text(encoding="utf-8")
    assert '"last_trace"' in saved_text
    assert '"request_payload"' not in saved_text
    assert '"response_payload"' not in saved_text
    assert "包含个人体验的回答" in saved_text  # 回答仍用于中断恢复，由完成建档时清除。


def test_legacy_onboarding_trace_discards_payloads_on_load_and_resave(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    legacy = OnboardingPending(
        date=date(2026, 9, 3),
        created_at=datetime.now(),
        proposed_profile=sample_profile().content,
        proposed_questions=sample_questions(),
    ).model_dump(mode="json")
    legacy["schema_version"] = 3
    legacy["last_trace"] = {
        "endpoint": "https://example.test/responses",
        "provider": "deepseek",
        "model": "test-model",
        "schema_name": "daily_harvest_test",
        "status_code": 200,
        "elapsed_ms": 12,
        "request_payload": {"input": "旧的个人回答"},
        "response_payload": {"output": "旧的模型结果"},
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    }
    storage.onboarding_path().write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    pending = storage.load_onboarding()

    assert pending is not None
    assert pending.schema_version == 4
    assert pending.last_trace is not None
    storage.save_onboarding(pending)
    saved_text = storage.onboarding_path().read_text(encoding="utf-8")
    assert "旧的个人回答" not in saved_text
    assert "旧的模型结果" not in saved_text


def test_onboarding_persists_each_answer_when_interrupted(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    provider = OnboardingProvider()
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "_configure_and_test_api", lambda: (config, provider))
    calls = iter(["1", KeyboardInterrupt()])

    def prompt(*args, **kwargs):
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(cli.typer, "prompt", prompt)
    result = runner.invoke(cli.app, ["onboard"])

    assert result.exit_code != 0
    pending = storage.load_onboarding()
    assert pending is not None
    assert pending.questionnaire == {"current_context": "学生或备考"}


def test_no_argument_runs_daily_after_onboarding(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    called = []
    monkeypatch.setattr(cli, "daily", lambda: called.append(True))

    result = runner.invoke(cli.app, [])

    assert result.exit_code == 0, result.output
    assert called == [True]


def test_strict_menu_reprompts_text_and_marks_recommendation(monkeypatch, capsys) -> None:
    answers = iter(["随便写的文字", "2"])
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: next(answers))

    selected = cli._prompt_menu(
        "下一步", (("1", "立即完成"), ("2", "继续修改")), recommended="1"
    )

    assert selected == "2"
    output = capsys.readouterr().out
    assert "立即完成（推荐）" in output
    assert "无法识别" in output


def test_trial_answer_review_can_correct_one_question(tmp_path, monkeypatch) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    pending = OnboardingPending(
        date=date(2026, 9, 3),
        created_at=datetime.now(),
        proposed_profile=sample_profile().content,
        proposed_questions=sample_questions(),
        daily_answers={item.id: "原答案" for item in sample_questions()},
    )
    storage.save_onboarding(pending)
    answers = iter(["9", "1", "修改后的答案", ""])
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: next(answers))

    reviewed = cli._review_trial_answers(pending, storage)

    assert reviewed is not None
    assert reviewed.daily_answers["moment"] == "修改后的答案"


def test_more_than_three_confirmed_revisions_are_allowed(tmp_path, monkeypatch) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    pending = OnboardingPending(
        date=date(2026, 9, 3),
        created_at=datetime.now(),
        proposed_profile=sample_profile().content,
        proposed_questions=sample_questions(),
        trial_run_count=1,
    )
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: "2")

    for index in range(4):
        pending, outcome = cli._revise_onboarding_design(
            pending,
            ["每日问题"],
            f"第 {index + 1} 次修改",
            OnboardingProvider(),
            storage,
            after_trial=True,
        )
        assert outcome == "continue"

    assert pending.revision_round == 4
    assert len(pending.feedback) == 4


def test_rebuild_creates_new_profile_version_without_rewriting_logs(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    original = sample_profile()
    storage.save_profile(original)
    record = DailyRecord(
        date=date(2026, 9, 1),
        generated_at=datetime.now(),
        provider="deepseek",
        model="test",
        usage=Usage(),
        report=sample_harvest(),
    )
    storage.save_daily(record, render_daily(record))
    before = storage.daily_json_path(record.date).read_text(encoding="utf-8")
    storage.save_calibration(
        CalibrationState(onboarding_completed=True, first_daily_date=record.date)
    )
    pending = OnboardingPending(
        date=date(2026, 9, 3),
        created_at=datetime.now(),
        mode="rebuild",
        start_strategy="current",
        baseline_profile_version=original.version,
        step="trial_review",
        proposed_profile=original.content,
        proposed_questions=sample_questions(),
        trial_run_count=1,
    )
    storage.save_onboarding(pending)

    cli._finish_onboarding(pending, storage)

    rebuilt = storage.load_profile()
    assert rebuilt is not None
    assert rebuilt.version == 2
    assert rebuilt.stage == "rebuilt"
    assert storage.daily_json_path(record.date).read_text(encoding="utf-8") == before
    assert storage.load_calibration().first_daily_date == record.date
    assert storage.load_onboarding() is None


def test_profile_rebuild_can_start_from_current_design(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    profile = sample_profile()
    storage.save_profile(profile)
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "get_api_key", lambda config: "secret")
    monkeypatch.setattr(cli, "build_provider", lambda config: OnboardingProvider())

    result = runner.invoke(cli.app, ["profile", "rebuild"], input="1\nq\n")

    assert result.exit_code == 0, result.output
    pending = storage.load_onboarding()
    assert pending is not None
    assert pending.mode == "rebuild"
    assert pending.start_strategy == "current"
    assert pending.baseline_profile_version == profile.version
    assert pending.proposed_profile == profile.content
    assert storage.load_profile() == profile
    assert "基于当前画像和问题集调整（推荐）" in result.output


def test_personalized_choices_accept_text_without_recommendation(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: "我正在转换学习方向")

    selected = cli._prompt_guided_choice("你目前在哪个阶段？", ("学生", "工作"))

    assert selected == "我正在转换学习方向"
    assert "推荐" not in capsys.readouterr().out
