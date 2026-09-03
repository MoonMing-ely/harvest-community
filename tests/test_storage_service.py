from datetime import date, datetime

from harvest.config import AppConfig
from harvest.models import DailyRecord, Usage, WeeklyReview, WeeklyThemeSummary
from harvest.render import render_daily
from harvest.service import generate_weekly, latest_review_week, make_pending, week_bounds, week_id
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


def test_pending_lifecycle_and_formal_record_drops_raw_answers(tmp_path) -> None:
    storage = Storage(tmp_path / "records")
    storage.ensure()
    target = date(2026, 9, 1)
    pending = make_pending(target, {"main": "私人原始回答"}, now=datetime(2026, 9, 1, 22, 0))
    storage.save_pending(pending)
    assert storage.load_pending(target).answers["main"] == "私人原始回答"

    record = DailyRecord(
        date=target,
        generated_at=datetime(2026, 9, 1, 22, 1),
        provider="deepseek",
        model="deepseek-v4-flash",
        usage=Usage(),
        report=sample_harvest(),
    )
    storage.save_daily(record, render_daily(record))
    storage.delete_pending(target)
    assert storage.load_pending(target) is None
    formal_json = storage.daily_json_path(target).read_text(encoding="utf-8")
    assert "私人原始回答" not in formal_json
    assert storage.daily_markdown_path(target).exists()


def test_week_calculation_handles_sunday_and_catchup() -> None:
    assert week_id(date(2026, 9, 6)) == "2026-W36"
    assert latest_review_week(date(2026, 9, 6)) == "2026-W36"
    assert latest_review_week(date(2026, 9, 7)) == "2026-W36"
    assert week_bounds("2026-W36") == (date(2026, 8, 31), date(2026, 9, 6))


def test_weekly_review_marks_missing_days_without_treating_them_as_zero(tmp_path) -> None:
    class WeeklyProvider:
        def generate(self, **kwargs):
            return WeeklyReview(
                summary="本周只有一份记录，无法判断其余日期。",
                sections=[
                    WeeklyThemeSummary(theme_id="projects", title="项目", summary="证据不足。"),
                    WeeklyThemeSummary(theme_id="algorithms", title="算法题", summary="形成了一项算法理解。"),
                    WeeklyThemeSummary(theme_id="learning_state", title="学习状态", summary="有一次连续学习记录。"),
                ],
                persistent_items=[],
                recommendations=["继续保护最长连续时间块"],
                core_direction="完成摩尔投票",
            ), Usage(input_tokens=20, output_tokens=10, total_tokens=30)

    daily = DailyRecord(
        date=date(2026, 9, 1),
        generated_at=datetime(2026, 9, 1, 22, 0),
        provider="deepseek",
        model="deepseek-v4-flash",
        usage=Usage(),
        report=sample_harvest(),
    )
    weekly = generate_weekly(
        "2026-W36",
        [daily],
        AppConfig(data_dir=tmp_path),
        WeeklyProvider(),
        sample_profile(),
        now=datetime(2026, 9, 7, 8, 0),
    )
    assert weekly.recorded_dates == [date(2026, 9, 1)]
    assert len(weekly.missing_dates) == 6
    assert date(2026, 9, 1) not in weekly.missing_dates
