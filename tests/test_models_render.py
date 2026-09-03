from datetime import date, datetime

import pytest
from pydantic import ValidationError

from harvest.models import (
    DailyHarvest,
    DailyRecord,
    ProfileContent,
    ReportSection,
    ThemeDefinition,
    Tomorrow,
    Usage,
    UserProfile,
)
from harvest.render import render_daily


def sample_profile() -> UserProfile:
    content = ProfileContent(
        current_context="正在学习软件开发，并关注日常状态。",
        review_purposes=["看清学习进展和状态变化"],
        themes=[
            ThemeDefinition(id="projects", title="项目", description="持续项目和工具建设"),
            ThemeDefinition(id="algorithms", title="算法题", description="算法理解和实现"),
            ThemeDefinition(id="learning_state", title="学习状态", description="专注、精力和学习方式"),
        ],
        expression_preferences=["自然、克制"],
        interpretation_boundaries=["不编造事实，不诊断心理，不评价人格或能力"],
    )
    moment = datetime(2026, 9, 1, 20, 0)
    return UserProfile(
        version=1, stage="initial", created_at=moment, updated_at=moment, content=content
    )


def sample_harvest() -> DailyHarvest:
    return DailyHarvest(
        overview="今天的注意力主要落在算法练习上，也觉察到频繁切换带来的消耗。",
        sections=[
            ReportSection(theme_id="projects", title="项目"),
            ReportSection(
                theme_id="algorithms",
                title="算法题",
                narrative="练习了摩尔投票。思路已经比开始时清楚，但代码还没有收束。",
                progress=["理解净票数含义", "代码尚未完成"],
                next_step="完成算法实现",
            ),
            ReportSection(
                theme_id="learning_state",
                title="学习状态",
                narrative="学习中多次转去检查 Agent，连续思考因此被切开。",
                progress=["上下文切换较多"],
            ),
        ],
        tomorrow=Tomorrow(suggestions=["先完成算法实现"], core_target="写完摩尔投票"),
    )


def test_daily_schema_rejects_invented_extra_fields() -> None:
    payload = sample_harvest().model_dump()
    payload["score"] = 99
    with pytest.raises(ValidationError):
        DailyHarvest.model_validate(payload)


def test_profile_rejects_duplicate_theme_ids() -> None:
    payload = sample_profile().content.model_dump()
    payload["themes"][1]["id"] = "projects"
    with pytest.raises(ValidationError, match="不能重复"):
        ProfileContent.model_validate(payload)


def test_daily_markdown_contains_dynamic_human_sections() -> None:
    record = DailyRecord(
        date=date(2026, 9, 1),
        generated_at=datetime(2026, 9, 1, 22, 0),
        provider="deepseek",
        model="deepseek-v4-flash",
        usage=Usage(input_tokens=100, output_tokens=50, total_tokens=150),
        report=sample_harvest(),
    )
    markdown = render_daily(record)
    assert "# Daily Harvest · 2026-09-01" in markdown
    assert "## 算法题" in markdown
    assert "理解净票数含义" in markdown
    assert "## 学习状态" in markdown
    assert "代码还没有收束" in markdown


def test_legacy_v2_daily_is_migrated_on_read() -> None:
    legacy = {
        "overview": "旧日报",
        "projects": {"narrative": "推进项目", "progress": [], "next_step": None},
        "algorithms": {"narrative": None, "progress": [], "next_step": None},
        "technical_foundations": {"narrative": None, "progress": [], "next_step": None},
        "learning_state": {"narrative": None, "progress": [], "next_step": None},
        "life_state": {"narrative": None, "progress": [], "next_step": None},
        "drawing": {"narrative": None, "progress": [], "next_step": None},
        "tomorrow": {"suggestions": [], "core_target": None},
    }
    migrated = DailyHarvest.model_validate(legacy)
    assert [item.theme_id for item in migrated.sections] == [
        "projects",
        "algorithms",
        "technical_foundations",
        "learning_state",
        "life_state",
        "drawing",
    ]
