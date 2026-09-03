from datetime import date, datetime

from harvest.memory import apply_suggestions, build_context_snapshot, read_active_project_hints, upsert_project
from harvest.models import (
    ContextSnapshot,
    DailyRecord,
    ProjectMemory,
    ProjectSuggestion,
    Tomorrow,
    ReportSection,
    Usage,
)
from harvest.prompts import daily_input
from harvest.render import render_daily
from harvest.storage import Storage
from tests.test_models_render import sample_harvest, sample_profile


def daily_record(target: date, progress: list[str], core_target: str | None) -> DailyRecord:
    report = sample_harvest()
    sections = [
        ReportSection(
            theme_id=item.theme_id,
            title=item.title,
            narrative=item.narrative,
            progress=progress if item.theme_id == "algorithms" else [],
            next_step=item.next_step,
        )
        for item in report.sections
    ]
    report = report.model_copy(update={"sections": sections, "tomorrow": Tomorrow(suggestions=[], core_target=core_target)})
    return DailyRecord(
        date=target,
        generated_at=datetime.combine(target, datetime.min.time()),
        provider="deepseek",
        model="deepseek-v4-flash",
        usage=Usage(),
        report=report,
    )


def test_context_uses_seven_days_deduplicates_and_keeps_current_state_local(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    memory = upsert_project(
        ProjectMemory(),
        name="Personal Work System",
        status="active",
        target=date(2026, 9, 7),
        next_step="试用日报",
    )
    storage.save_project_memory(memory)
    for target, progress, core in [
        (date(2026, 9, 1), ["旧进展"], "旧目标"),
        (date(2026, 9, 5), ["重复进展", "补测试"], "继续测试"),
        (date(2026, 9, 6), ["重复进展", "验证提醒"], "第一次真实使用"),
    ]:
        record = daily_record(target, progress, core)
        storage.save_daily(record, render_daily(record))
    state_path = tmp_path / "current-state.md"
    state_path.write_text(
        "# State\n\n## Active project\n\n- 私密本地项目提示\n- 第二条提示\n\n## Update policy\n- 不应读取\n",
        encoding="utf-8",
    )

    snapshot = build_context_snapshot(storage, date(2026, 9, 8), current_state_path=state_path)

    assert [item.name for item in snapshot.active_projects] == ["Personal Work System"]
    assert snapshot.recent_progress == ["重复进展", "验证提醒", "补测试"]
    assert snapshot.last_core_target == "第一次真实使用"
    assert snapshot.current_state_hints == ["私密本地项目提示", "第二条提示"]
    payload = daily_input({"recall_cues": "今天做了测试"}, snapshot.active_projects, sample_profile())
    assert "Personal Work System" in payload
    assert "私密本地项目提示" not in payload
    assert "重复进展" not in payload
    assert "自然、克制" in payload


def test_current_state_parser_reads_only_active_project_section(tmp_path) -> None:
    path = tmp_path / "state.md"
    path.write_text(
        "## Active project\n- 项目 A\n\n## Private\n- 不得读取\n",
        encoding="utf-8",
    )
    assert read_active_project_hints(path) == ["项目 A"]


def test_project_suggestions_require_exact_match_and_do_not_duplicate() -> None:
    memory = upsert_project(
        ProjectMemory(), name="Project Alpha", status="active", target=date(2026, 9, 1), next_step=None
    )
    suggestions = [
        ProjectSuggestion(
            action="update",
            project_name="Project Alpha",
            reason="今天推进了",
            next_step="补测试",
        ),
        ProjectSuggestion(
            action="complete",
            project_name="不存在的项目",
            reason="误判",
            next_step=None,
        ),
    ]
    updated, applied, skipped = apply_suggestions(memory, suggestions, date(2026, 9, 8))
    assert applied == ["update: Project Alpha"]
    assert len(skipped) == 1
    assert updated.projects[0].next_step == "补测试"
    assert updated.projects[0].last_seen == date(2026, 9, 8)


def test_empty_context_is_valid(tmp_path) -> None:
    storage = Storage(tmp_path / "data")
    storage.ensure()
    snapshot = build_context_snapshot(storage, date(2026, 9, 8), current_state_path=tmp_path / "missing.md")
    assert snapshot == ContextSnapshot(
        active_projects=[], recent_progress=[], last_core_target=None, current_state_hints=[]
    )
