from datetime import date, datetime, timedelta

import pytest

import harvest.cli as cli
from harvest.config import AppConfig
from harvest.models import (
    CalibrationState,
    DailyAnalysis,
    DailyRecord,
    FeedbackEvent,
    ProfileProposal,
    ReportSection,
    Usage,
)
from harvest.personalization import REQUIRED_BOUNDARIES, next_profile, profile_diff
from harvest.providers import ProviderError
from harvest.render import render_daily
from harvest.service import validate_daily_sections
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


class ProfileProvider:
    def __init__(self, profile):
        self.profile = profile

    def generate(self, *, output_type, **kwargs):
        assert output_type is ProfileProposal
        changed = self.profile.content.model_copy(
            update={"expression_preferences": ["简洁、直接，避免空泛鼓励"]}
        )
        return ProfileProposal(profile=changed, rationale=["用户明确要求更直接"]), Usage()


def test_profile_versions_are_immutable_and_restorable(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    first = sample_profile()
    storage.save_profile(first)
    second = next_profile(
        first.content.model_copy(update={"action_preferences": ["只给一个最小下一步"]}),
        first,
        "manual",
    )
    storage.save_profile(second)

    assert storage.load_profile().version == 2
    assert [item.version for item in storage.profile_versions()] == [1, 2]
    assert storage.load_profile_version(1).content.action_preferences == []
    with pytest.raises(ValueError, match="版本已存在"):
        storage.save_profile(second)


def test_program_enforces_non_negotiable_interpretation_boundaries() -> None:
    source = sample_profile()
    content = source.content.model_copy(update={"interpretation_boundaries": ["只写中文"]})
    profile = next_profile(content, None, "initial")
    assert profile.content.interpretation_boundaries[:3] == list(REQUIRED_BOUNDARIES)


def test_profile_diff_reports_theme_add_remove_and_other_changes() -> None:
    before = sample_profile().content
    after = before.model_copy(
        update={
            "themes": [*before.themes[1:], before.themes[0].model_copy(update={"title": "长期项目"})],
            "expression_preferences": ["直接"],
        }
    )
    changes = profile_diff(before, after)
    assert any("主线修改" in item for item in changes)
    assert any("表达偏好" in item for item in changes)


def test_report_sections_must_match_profile_order() -> None:
    report = sample_harvest()
    wrong = report.model_copy(update={"sections": list(reversed(report.sections))})
    with pytest.raises(ProviderError, match="主线与画像不一致"):
        validate_daily_sections(wrong, sample_profile())


def test_fifth_distinct_report_triggers_confirmed_profile_update_without_rewriting_report(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    profile = sample_profile()
    storage.save_profile(profile)
    start = date(2026, 9, 1)
    for offset in range(5):
        target = start + timedelta(days=offset)
        record = DailyRecord(
            date=target,
            generated_at=datetime(2026, 9, 1 + offset, 22, 0),
            provider="deepseek",
            model="test",
            usage=Usage(),
            report=sample_harvest(),
        )
        storage.save_daily(record, render_daily(record))
    original_fifth = storage.daily_json_path(start + timedelta(days=4)).read_text(encoding="utf-8")
    storage.save_calibration(
        CalibrationState(
            onboarding_completed=True,
            first_daily_date=start,
            feedback_events=[
                FeedbackEvent(date=start, kind="daily_revision", text="不要空泛鼓励")
            ],
        )
    )
    monkeypatch.setattr(cli.console, "input", lambda *args, **kwargs: "")
    answers = iter(["整体自然", "偶尔太长", "更直接"])
    monkeypatch.setattr(cli.typer, "prompt", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(cli, "_proposal_confirm", lambda before, after: True)

    cli._maybe_five_report_calibration(config, storage, ProfileProvider(profile))

    assert storage.load_profile().stage == "five_report"
    assert storage.load_profile().version == 2
    state = storage.load_calibration()
    assert state.five_report_status == "completed"
    assert state.feedback_events == []
    assert storage.daily_json_path(start + timedelta(days=4)).read_text(encoding="utf-8") == original_fifth


def test_five_report_calibration_counts_distinct_saved_dates(tmp_path, monkeypatch) -> None:
    config = AppConfig(data_dir=tmp_path / "data")
    storage = Storage(config.data_dir)
    storage.ensure()
    storage.save_profile(sample_profile())
    for offset in range(4):
        target = date(2026, 9, 1) + timedelta(days=offset)
        record = DailyRecord(
            date=target,
            generated_at=datetime.now(),
            provider="deepseek",
            model="test",
            usage=Usage(),
            report=sample_harvest(),
        )
        storage.save_daily(record, render_daily(record))
    monkeypatch.setattr(cli.console, "input", lambda *args, **kwargs: pytest.fail("不应询问"))
    cli._maybe_five_report_calibration(config, storage, ProfileProvider(sample_profile()))
    assert storage.load_profile().version == 1
