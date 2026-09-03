from harvest.models import ContextSnapshot
from harvest.prompts import (
    DAILY_INSTRUCTIONS,
    ONBOARDING_INSTRUCTIONS,
    PROFILE_INSTRUCTIONS,
    WEEKLY_INSTRUCTIONS,
)
from harvest.service import build_questions


def test_six_questions_center_personal_experience_growth_and_basic_care() -> None:
    snapshot = ContextSnapshot(
        active_projects=[], recent_progress=[], last_core_target=None, current_state_hints=[]
    )
    questions = build_questions(snapshot)
    keys = [key for key, _ in questions]
    text = "\n".join(question for _, question in questions)

    assert len(questions) == 6
    assert keys == [
        "meaningful_moment",
        "inner_experience",
        "response_and_choice",
        "growth_and_insight",
        "basic_care",
        "tomorrow",
    ]
    assert all(word in text for word in ("感受", "回应", "理解", "认识自己"))
    assert all(word in text for word in ("吃饭", "喝水", "睡眠", "活动身体"))


def test_ai_prompts_treat_concrete_work_as_evidence_not_the_center() -> None:
    assert "事实载体" in ONBOARDING_INSTRUCTIONS
    assert "最多一个问题" in ONBOARDING_INSTRUCTIONS
    assert "至少三个问题关注选择与应对" in ONBOARDING_INSTRUCTIONS
    assert "事实载体" in DAILY_INSTRUCTIONS
    assert "不得把报告写成进度清单" in DAILY_INSTRUCTIONS


def test_all_ai_roles_treat_json_strings_as_untrusted_data() -> None:
    for instructions in (
        DAILY_INSTRUCTIONS,
        WEEKLY_INSTRUCTIONS,
        PROFILE_INSTRUCTIONS,
        ONBOARDING_INSTRUCTIONS,
    ):
        assert "不可信数据" in instructions
        assert "终端控制序列" in instructions
