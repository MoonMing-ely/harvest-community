from __future__ import annotations

from harvest.models import DailyRecord, ProfileContent, ReportSection, WeeklyRecord
from harvest.text_safety import escape_markdown_text


def _safe(value: str) -> str:
    return escape_markdown_text(value)


def _items(items: list[str], empty: str = "无明确记录") -> list[str]:
    return [f"- {_safe(item)}" for item in items] if items else [f"- {_safe(empty)}"]


def _theme(section: ReportSection) -> list[str]:
    lines = [f"## {_safe(section.title)}"]
    if not section.narrative and not section.progress and not section.next_step:
        return [*lines, "今天没有留下明确记录。"]
    if section.narrative:
        lines.extend(["", _safe(section.narrative)])
    if section.progress:
        lines.extend(["", "**留下的进展**", *[f"- {_safe(item)}" for item in section.progress]])
    if section.next_step:
        lines.extend(["", f"**下一步**：{_safe(section.next_step)}"])
    return lines


def render_daily(record: DailyRecord) -> str:
    report = record.report
    lines = [f"# Daily Harvest · {record.date.isoformat()}", "", "## 今日回望", "", _safe(report.overview)]
    for section in report.sections:
        lines.extend(["", *_theme(section)])
    lines.extend(
        [
            "",
            "## 明日行动",
            *_items(report.tomorrow.suggestions),
            "",
            "## 核心目标",
            f"- {_safe(report.tomorrow.core_target or '未明确')}",
            "",
        ]
    )
    return "\n".join(lines)


def render_weekly(record: WeeklyRecord) -> str:
    review = record.review
    recorded = "、".join(item.isoformat() for item in record.recorded_dates) or "无"
    missing = "、".join(item.isoformat() for item in record.missing_dates) or "无"
    lines = [
        f"# Weekly Review · {record.week}",
        "",
        f"> {record.period_start.isoformat()} 至 {record.period_end.isoformat()}",
        "",
        "## DATA COVERAGE",
        f"- 已记录：{recorded}",
        f"- 缺失日期：{missing}",
        "",
        "## 总览",
        _safe(review.summary),
    ]
    for section in review.sections:
        lines.extend(["", f"## {_safe(section.title)}", _safe(section.summary)])
    lines.extend(
        [
            "",
            "## 持续事项",
            *_items(review.persistent_items),
            "",
            "## 下周行动",
            *_items(review.recommendations),
            "",
            "## 核心方向",
            f"- {_safe(review.core_direction or '未形成足够证据')}",
            "",
        ]
    )
    return "\n".join(lines)


def render_profile(content: ProfileContent) -> str:
    lines = ["# Harvest 用户画像", "", "## 当前阶段", "", _safe(content.current_context), "", "## 复盘目的"]
    lines.extend(_items(content.review_purposes))
    lines.extend(["", "## 长期主线"])
    for theme in content.themes:
        lines.append(f"- **{_safe(theme.title)}**（`{theme.id}`）：{_safe(theme.description)}")
    groups = (
        ("关注信号", content.attention_preferences),
        ("表达偏好", content.expression_preferences),
        ("行动偏好", content.action_preferences),
        ("解释边界", content.interpretation_boundaries),
    )
    for title, items in groups:
        lines.extend(["", f"## {title}", *_items(items)])
    lines.extend(["", "## 暂定观察"])
    if content.tentative_observations:
        for item in content.tentative_observations:
            lines.append(f"- {_safe(item.statement)}（{item.confidence}；依据：{_safe(item.evidence)}）")
    else:
        lines.append("- 暂无")
    return "\n".join(lines) + "\n"
