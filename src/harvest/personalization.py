from __future__ import annotations

from datetime import datetime
from typing import Any

from harvest.models import DailyQuestion, LEGACY_THEMES, ProfileContent, ThemeDefinition, UserProfile


ONBOARDING_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("current_context", "你目前主要处在什么阶段？平时有哪些重要角色或责任？"),
    ("review_purpose", "你希望复盘主要帮助你看清什么，而不只是记录什么？"),
    ("recurring_threads", "目前有哪些会持续数周或更久的事情、兴趣或生活领域？"),
    ("progress_signals", "对你来说，哪些变化算真正的进展？哪些阻碍值得被注意？"),
    ("work_style", "你通常在什么状态下做得最好？有哪些反复出现的节奏或困难？"),
    ("expression", "你希望报告以什么语气和篇幅书写？有哪些说法会让你不舒服？"),
    ("actions", "你希望 AI 怎样提出下一步？哪些判断或建议不应由 AI 擅自作出？"),
)

REQUIRED_BOUNDARIES = (
    "不编造用户没有提供的事实",
    "不做心理或健康诊断",
    "不评价用户的人格或能力",
)


def enforce_profile_boundaries(content: ProfileContent) -> ProfileContent:
    optional = [item for item in content.interpretation_boundaries if item not in REQUIRED_BOUNDARIES]
    return content.model_copy(
        update={"interpretation_boundaries": [*REQUIRED_BOUNDARIES, *optional][:5]}
    )


def profile_diff(before: ProfileContent, after: ProfileContent) -> list[str]:
    old = before.model_dump(mode="json")
    new = after.model_dump(mode="json")
    labels = {
        "current_context": "当前阶段",
        "review_purposes": "复盘目的",
        "themes": "长期主线",
        "attention_preferences": "关注信号",
        "tentative_observations": "暂定观察",
        "expression_preferences": "表达偏好",
        "action_preferences": "行动偏好",
        "interpretation_boundaries": "解释边界",
    }
    changes: list[str] = []
    old_themes = {item["id"]: item for item in old["themes"]}
    new_themes = {item["id"]: item for item in new["themes"]}
    added = [item["title"] for key, item in new_themes.items() if key not in old_themes]
    removed = [item["title"] for key, item in old_themes.items() if key not in new_themes]
    modified = [
        new_themes[key]["title"]
        for key in old_themes.keys() & new_themes.keys()
        if old_themes[key] != new_themes[key]
    ]
    if added:
        changes.append("长期主线新增：" + "、".join(added))
    if removed:
        changes.append("长期主线删除：" + "、".join(removed))
    if modified:
        changes.append("长期主线修改：" + "、".join(modified))
    if not (added or removed or modified) and old["themes"] != new["themes"]:
        changes.append("长期主线：顺序调整")
    for key, label in labels.items():
        if key != "themes" and old[key] != new[key]:
            changes.append(f"{label}：将被更新")
    return changes


def next_profile(
    content: ProfileContent,
    previous: UserProfile | None,
    stage: str,
    *,
    daily_questions: list[DailyQuestion] | None = None,
) -> UserProfile:
    now = datetime.now().astimezone()
    return UserProfile(
        version=1 if previous is None else previous.version + 1,
        stage=stage,
        created_at=now if previous is None else previous.created_at,
        updated_at=now,
        content=enforce_profile_boundaries(content),
        daily_questions=(
            daily_questions
            if daily_questions is not None
            else (previous.daily_questions if previous is not None else [])
        ),
    )


def legacy_profile_content(markdown: str = "") -> ProfileContent:
    themes = [
        ThemeDefinition(
            id=key,
            title=title,
            description=f"持续关注与{title}有关的事实、变化、阻碍和下一步。",
        )
        for key, title in LEGACY_THEMES
    ]
    context = "从旧版 Harvest 报告画像迁移而来。"
    if markdown.strip():
        compact = " ".join(line.strip("- ") for line in markdown.splitlines() if line.strip().startswith("- "))
        context = (compact or context)[:600]
    return ProfileContent(
        current_context=context,
        review_purposes=["形成连续、诚实、可回看的日常观察记录"],
        themes=themes,
        attention_preferences=["区分事实、变化、阻碍和下一步"],
        expression_preferences=["自然、克制，不强行积极，不使用效率评分"],
        action_preferences=["建议少而具体，并且只能来自当天信息"],
        interpretation_boundaries=["不编造事实，不诊断心理，不评价人格或能力"],
    )


def profile_payload(profile: UserProfile | ProfileContent) -> dict[str, Any]:
    content = profile.content if isinstance(profile, UserProfile) else profile
    return content.model_dump(mode="json")
