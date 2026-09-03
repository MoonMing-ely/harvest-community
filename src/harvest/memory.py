from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from harvest.models import ContextSnapshot, ProjectItem, ProjectMemory, ProjectSuggestion
from harvest.storage import Storage


DEFAULT_CURRENT_STATE_PATH = Path.home() / "Documents" / "AI-Assistant" / "current-state.md"


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def find_project(memory: ProjectMemory, name: str) -> ProjectItem | None:
    wanted = normalize_name(name)
    return next((project for project in memory.projects if normalize_name(project.name) == wanted), None)


def upsert_project(
    memory: ProjectMemory,
    *,
    name: str,
    status: str,
    target: date,
    next_step: str | None = None,
    require_existing: bool = False,
) -> ProjectMemory:
    clean_name = " ".join(name.split())
    if not clean_name:
        raise ValueError("项目名称不能为空")
    existing = find_project(memory, clean_name)
    if require_existing and existing is None:
        raise ValueError(f"未找到项目：{clean_name}")
    if existing is None:
        updated = ProjectItem.model_validate(
            {"name": clean_name, "status": status, "last_seen": target, "next_step": next_step}
        )
        return memory.model_copy(update={"projects": [*memory.projects, updated]})
    replacement = ProjectItem.model_validate(
        {
            "name": existing.name,
            "status": status,
            "last_seen": target,
            "next_step": next_step if next_step is not None else existing.next_step,
        }
    )
    return memory.model_copy(
        update={
            "projects": [
                replacement if normalize_name(project.name) == normalize_name(existing.name) else project
                for project in memory.projects
            ]
        }
    )


def apply_suggestions(
    memory: ProjectMemory,
    suggestions: list[ProjectSuggestion],
    target: date,
) -> tuple[ProjectMemory, list[str], list[str]]:
    current = memory
    applied: list[str] = []
    skipped: list[str] = []
    status_for_action = {"add": "active", "update": "active", "pause": "paused", "complete": "completed"}
    for suggestion in suggestions:
        existing = find_project(current, suggestion.project_name)
        if suggestion.action == "add" and existing is not None:
            skipped.append(f"{suggestion.project_name}：已存在，未重复添加")
            continue
        if suggestion.action != "add" and existing is None:
            skipped.append(f"{suggestion.project_name}：名称未精确匹配现有项目")
            continue
        current = upsert_project(
            current,
            name=suggestion.project_name,
            status=status_for_action[suggestion.action],
            target=target,
            next_step=suggestion.next_step,
            require_existing=suggestion.action != "add",
        )
        applied.append(f"{suggestion.action}: {suggestion.project_name}")
    return current, applied, skipped


def build_context_snapshot(
    storage: Storage,
    target: date,
    *,
    current_state_path: Path | None = None,
) -> ContextSnapshot:
    memory = storage.load_project_memory()
    active = [project for project in memory.projects if project.status == "active"]
    active.sort(key=lambda project: project.last_seen, reverse=True)

    start = target - timedelta(days=7)
    end = target - timedelta(days=1)
    records = list(reversed(storage.daily_records(start, end))) if start <= end else []
    progress: list[str] = []
    seen: set[str] = set()
    last_core_target: str | None = None
    for record in records:
        if last_core_target is None and record.report.tomorrow.core_target:
            last_core_target = record.report.tomorrow.core_target
        for item in record.report.progress_items():
            key = item.casefold().strip()
            if key and key not in seen:
                seen.add(key)
                progress.append(item)
                if len(progress) == 3:
                    break
        if len(progress) == 3 and last_core_target is not None:
            break

    return ContextSnapshot(
        active_projects=active[:5],
        recent_progress=progress[:3],
        last_core_target=last_core_target,
        current_state_hints=(
            read_active_project_hints(current_state_path, limit=2) if current_state_path is not None else []
        ),
    )


def read_active_project_hints(path: Path, *, limit: int = 2) -> list[str]:
    if not path.exists():
        return []
    hints: list[str] = []
    in_section = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "## Active project":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- "):
            hint = line[2:].strip()
            if hint:
                hints.append(hint[:180])
                if len(hints) == limit:
                    break
    return hints
