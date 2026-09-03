from datetime import date

from typer.testing import CliRunner

import harvest.cli as cli
from harvest.config import AppConfig
from harvest.models import DailyAnalysis, ProfileProposal, Usage
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


runner = CliRunner()


class OnboardingProvider:
    def generate(self, *, output_type, **kwargs):
        if output_type is ProfileProposal:
            return ProfileProposal(profile=sample_profile().content, rationale=["来自固定问卷"]), Usage()
        if output_type is DailyAnalysis:
            return DailyAnalysis(report=sample_harvest(), project_suggestions=[]), Usage()
        raise AssertionError(output_type)


def test_onboarding_saves_profile_and_first_daily_then_removes_raw_answers(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    monkeypatch.setattr(cli, "build_provider", lambda config: OnboardingProvider())
    answers = [
        "学生",
        "看清学习节奏",
        "项目、算法和状态",
        "理解和交付",
        "安静时最好",
        "自然克制",
        "只给具体下一步",
        "写了代码",
        "项目有推进",
        "理解了接口",
        "下午最投入",
        "正常吃饭",
        "补完测试",
        "",
    ]
    result = runner.invoke(cli.app, ["onboard", "--date", "2026-09-01"], input="\n".join(answers) + "\n")

    assert result.exit_code == 0, result.output
    assert storage.load_profile() is not None
    assert storage.load_daily(date(2026, 9, 1)) is not None
    assert storage.load_onboarding() is None
    assert "写了代码" not in storage.profile_path().read_text(encoding="utf-8")
    assert storage.load_calibration().first_daily_date == date(2026, 9, 1)


def test_onboarding_persists_each_answer_when_interrupted(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    monkeypatch.setattr(cli, "_context", lambda: (config, storage))
    calls = iter(["学生", KeyboardInterrupt()])

    def prompt(*args, **kwargs):
        value = next(calls)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(cli.typer, "prompt", prompt)
    result = runner.invoke(cli.app, ["onboard", "--date", "2026-09-02"])

    assert result.exit_code != 0
    pending = storage.load_onboarding()
    assert pending is not None
    assert pending.questionnaire == {"current_context": "学生"}
