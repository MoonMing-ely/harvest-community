from typer.testing import CliRunner

import harvest.cli as cli
from harvest.config import AppConfig
from harvest.models import DailyAnalysis, DailyQuestion, NetworkTrace, OnboardingProposal, Usage
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


runner = CliRunner()


def sample_questions() -> list[DailyQuestion]:
    return [
        DailyQuestion(id="recall", prompt="今天实际做了什么？", purpose="回忆事实"),
        DailyQuestion(id="progress", prompt="哪件事真正向前走了？", purpose="识别进展"),
        DailyQuestion(id="blocker", prompt="最明显的卡点是什么？", purpose="识别阻碍"),
        DailyQuestion(id="learning", prompt="今天理解或验证了什么？", purpose="观察学习过程"),
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
    user_input = "\n".join([*guided, "", *trial, "", ""]) + "\n"
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
