from harvest.models import ContextSnapshot
from harvest.service import build_questions


def test_six_questions_use_retrieval_cues_and_basic_care_without_classification() -> None:
    snapshot = ContextSnapshot(
        active_projects=[], recent_progress=[], last_core_target=None, current_state_hints=[]
    )
    questions = build_questions(snapshot)
    keys = [key for key, _ in questions]
    text = "\n".join(question for _, question in questions)

    assert len(questions) == 6
    assert keys == ["recall_cues", "recent_context", "progress", "work_state", "basic_care", "tomorrow"]
    assert "打开或接触过" in text
    assert "不用分类" in text
    assert all(word in text for word in ("吃饭", "喝水", "睡眠", "活动身体"))
