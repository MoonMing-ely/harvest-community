from __future__ import annotations

import getpass
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Literal

# Importing readline installs Unicode-aware editing for built-in input() on
# Unix-like terminals. Without it, a terminal with IUTF8 disabled can erase
# only one byte of a Chinese character and leave the next input undecodable.
try:
    import readline as _readline  # noqa: F401
except ImportError:  # Windows consoles already provide native line editing.
    _readline = None

import typer
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from harvest.config import (
    CONFIG_PATH,
    REPORT_PROFILE_PATH,
    AppConfig,
    get_api_key,
    get_api_key_with_source,
    load_config,
    save_api_key,
    save_config,
)
from harvest.memory import apply_suggestions, build_context_snapshot, find_project, upsert_project
from harvest.models import (
    CalibrationState,
    ContextSnapshot,
    DailyRecord,
    FeedbackEvent,
    OnboardingPending,
    PendingDaily,
    ProfileContent,
    ProjectSuggestion,
    UserProfile,
    WeeklyRecord,
)
from harvest.personalization import ONBOARDING_QUESTIONS, legacy_profile_content, next_profile, profile_diff
from harvest.providers import ProviderError, ResponsesProvider, build_provider
from harvest.reminder import install_reminder, send_notification, timer_status
from harvest.render import render_daily, render_profile, render_weekly
from harvest.service import (
    DailyDraft,
    build_initial_profile,
    build_questions,
    generate_daily,
    generate_weekly,
    latest_review_week,
    make_pending,
    revise_daily,
    revise_profile_content,
    revise_weekly,
    week_bounds,
)
from harvest.storage import Storage


app = typer.Typer(name="harvest", help="本地优先、可校准的个人复盘工具。", no_args_is_help=True)
project_app = typer.Typer(help="维护跨天项目记忆。", no_args_is_help=True)
profile_app = typer.Typer(help="查看、校准和恢复用户画像。", invoke_without_command=True)
app.add_typer(project_app, name="project")
app.add_typer(profile_app, name="profile")
console = Console()


def _parse_date(value: str | None) -> date:
    if value is None:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("日期格式应为 YYYY-MM-DD") from exc


def _context() -> tuple[AppConfig, Storage]:
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        console.print(f"[red]配置读取失败：{exc}[/red]")
        raise typer.Exit(1) from exc
    storage = Storage(config.data_dir)
    storage.ensure()
    return config, storage


def _provider(config: AppConfig) -> ResponsesProvider:
    try:
        return build_provider(config)
    except ProviderError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


def _snapshot(config: AppConfig, storage: Storage, target: date) -> ContextSnapshot:
    return build_context_snapshot(storage, target, current_state_path=config.current_state_path)


def _require_profile(storage: Storage) -> UserProfile:
    profile = storage.load_profile()
    if profile is None:
        console.print("[yellow]尚未建立用户画像，请先运行 harvest onboard。[/yellow]")
        raise typer.Exit(1)
    return profile


def _show_daily(record: DailyRecord) -> None:
    console.print(Panel(Markdown(render_daily(record)), border_style="green", title="日报预览"))


def _show_weekly(record: WeeklyRecord) -> None:
    console.print(Panel(Markdown(render_weekly(record)), border_style="cyan", title="周报预览"))


def _show_profile(profile: UserProfile | ProfileContent, title: str = "用户画像") -> None:
    content = profile.content if isinstance(profile, UserProfile) else profile
    console.print(Panel(Markdown(render_profile(content)), title=title, border_style="cyan"))


def _show_context_snapshot(snapshot: ContextSnapshot) -> None:
    lines: list[str] = []
    if snapshot.active_projects:
        lines.append("[bold]Active Projects[/bold]")
        for item in snapshot.active_projects:
            next_step = f" → {item.next_step}" if item.next_step else ""
            lines.append(f"• {item.name}{next_step}")
    if snapshot.recent_progress:
        lines.append("[bold]最近进展[/bold]")
        lines.extend(f"• {item}" for item in snapshot.recent_progress)
    if snapshot.last_core_target:
        lines.append(f"[bold]上一份核心目标[/bold]\n• {snapshot.last_core_target}")
    if snapshot.current_state_hints:
        lines.append("[bold]可选本地状态提示[/bold]")
        lines.extend(f"• {item}" for item in snapshot.current_state_hints)
    console.print(Panel("\n".join(lines) if lines else "暂无近期记忆。", title="近期记忆 · 仅本地"))


def _read_and_save_api_key(config: AppConfig) -> bool:
    console.print(f"当前 Provider：[bold]{config.provider}[/bold]；模型：[bold]{config.model}[/bold]")
    key = getpass.getpass(f"{config.api_key_name}（输入不会显示）: ").strip()
    if not key:
        console.print("[yellow]输入为空，未保存。[/yellow]")
        return False
    try:
        save_api_key(config.api_key_name, key)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        return False
    console.print("[green]API Key 已保存到系统凭据库。[/green]")
    return True


def _collect_answers(
    questions: tuple[tuple[str, str], ...], answers: dict[str, str], on_change
) -> dict[str, str]:
    current = dict(answers)
    for key, question in questions:
        if key in current:
            continue
        while True:
            try:
                current[key] = typer.prompt(question, default="", show_default=False).strip()
                break
            except UnicodeDecodeError:
                console.print("[yellow]当前行不是有效 UTF-8，已丢弃；此前答案仍已保存。[/yellow]")
        on_change(current)
    return current


def _review_daily(
    draft: DailyDraft,
    config: AppConfig,
    provider: ResponsesProvider,
    active_projects,
    profile: UserProfile | ProfileContent,
    *,
    on_feedback=None,
) -> DailyDraft | None:
    current = draft
    while True:
        _show_daily(current.record)
        action = console.input("[bold][Enter] 保存 / 输入修改意见 / q 取消：[/bold]").strip()
        if not action:
            return current
        if action.lower() in {"q", "quit", "取消"}:
            return None
        if on_feedback is not None:
            on_feedback(action)
        try:
            current = revise_daily(current, action, config, provider, active_projects, profile)
        except ProviderError as exc:
            console.print(f"[red]修订失败：{exc}[/red]")


def _review_weekly(
    record: WeeklyRecord, config: AppConfig, provider: ResponsesProvider, profile: UserProfile
) -> WeeklyRecord | None:
    current = record
    while True:
        _show_weekly(current)
        action = console.input("[bold][Enter] 保存 / 输入修改意见 / q 取消：[/bold]").strip()
        if not action:
            return current
        if action.lower() in {"q", "quit", "取消"}:
            return None
        try:
            current = revise_weekly(current, action, config, provider, profile)
        except ProviderError as exc:
            console.print(f"[red]修订失败：{exc}[/red]")


def _confirm_project_updates(
    suggestions: list[ProjectSuggestion], target: date, storage: Storage
) -> None:
    if not suggestions:
        return
    lines = [
        f"• {item.action} · {item.project_name}：{item.reason}"
        + (f"；下一步：{item.next_step}" if item.next_step else "")
        for item in suggestions
    ]
    console.print(Panel("\n".join(lines), title="AI 建议更新项目记忆"))
    if not typer.confirm("应用以上更新？", default=True):
        return
    updated, applied, skipped = apply_suggestions(storage.load_project_memory(), suggestions, target)
    if applied:
        storage.save_project_memory(updated)
    for item in skipped:
        console.print(f"[yellow]跳过：{item}[/yellow]")


def _save_feedback(storage: Storage, target: date, text: str) -> None:
    if storage.load_calibration().five_report_status == "pending":
        storage.add_feedback(FeedbackEvent(date=target, kind="daily_revision", text=text))


def _process_pending(
    pending: PendingDaily, config: AppConfig, storage: Storage, profile: UserProfile
) -> DailyRecord | None:
    snapshot = _snapshot(config, storage, pending.date)
    try:
        provider = build_provider(config)
        draft = generate_daily(pending, config, provider, snapshot.active_projects, profile)
    except ProviderError as exc:
        storage.save_pending(pending.model_copy(update={"last_error": str(exc)}))
        console.print(f"[red]AI 处理失败：{exc}[/red]")
        return None
    accepted = _review_daily(
        draft,
        config,
        provider,
        snapshot.active_projects,
        profile,
        on_feedback=lambda text: _save_feedback(storage, pending.date, text),
    )
    if accepted is None:
        console.print("已取消；原始回答仍保存在 pending。")
        return None
    storage.save_daily(accepted.record, render_daily(accepted.record))
    storage.delete_pending(pending.date)
    console.print(f"[green]日报已保存：{storage.daily_markdown_path(pending.date)}[/green]")
    _confirm_project_updates(accepted.project_suggestions, pending.date, storage)
    _maybe_five_report_calibration(config, storage, provider)
    _maybe_weekly(pending.date, config, storage, provider, profile)
    return accepted.record


def _proposal_confirm(before: ProfileContent, after: ProfileContent) -> bool:
    changes = profile_diff(before, after)
    console.print(Panel("\n".join(f"• {item}" for item in changes) or "画像内容没有变化", title="画像差异"))
    _show_profile(after, "拟议画像")
    return typer.confirm("应用这份画像？", default=True)


def _maybe_five_report_calibration(
    config: AppConfig, storage: Storage, provider: ResponsesProvider
) -> None:
    state = storage.load_calibration()
    records = storage.all_daily_records()
    if state.five_report_status != "pending" or len({item.date for item in records}) < 5:
        return
    action = console.input("已完成 5 份日报。[Enter] 现在微调 / later 稍后 / never 不再询问：").strip().lower()
    if action == "later":
        return
    if action == "never":
        storage.save_calibration(
            state.model_copy(update={"five_report_status": "dismissed", "feedback_events": []})
        )
        return
    answers = [
        typer.prompt("目前报告哪些地方效果好", default="", show_default=False).strip(),
        typer.prompt("哪些地方持续不像你或不准确", default="", show_default=False).strip(),
        typer.prompt("以后希望增加或减少关注什么", default="", show_default=False).strip(),
    ]
    feedback = "\n".join(item for item in answers if item)
    if not feedback:
        storage.save_calibration(
            state.model_copy(update={"five_report_status": "completed", "feedback_events": []})
        )
        return
    profile = _require_profile(storage)
    evidence = {
        "confirmed_reports": [item.model_dump(mode="json") for item in records[-5:]],
        "revision_feedback": [item.model_dump(mode="json") for item in state.feedback_events],
    }
    try:
        proposal = revise_profile_content(profile.content, feedback, provider, evidence=evidence)
    except ProviderError as exc:
        console.print(f"[red]画像微调失败：{exc}[/red] 下次仍会询问。")
        return
    if not _proposal_confirm(profile.content, proposal.profile):
        return
    storage.save_profile(next_profile(proposal.profile, profile, "five_report"))
    storage.save_calibration(
        state.model_copy(update={"five_report_status": "completed", "feedback_events": []})
    )
    console.print("[green]五日报告微调已生效，将从下一份日报开始使用。[/green]")


def _generate_week(
    week: str, config: AppConfig, storage: Storage, provider: ResponsesProvider, profile: UserProfile
) -> WeeklyRecord | None:
    records = storage.daily_records(*week_bounds(week))
    if not records:
        console.print(f"[yellow]{week} 没有日报。[/yellow]")
        return None
    try:
        draft = generate_weekly(week, records, config, provider, profile)
    except ProviderError as exc:
        console.print(f"[red]周报生成失败：{exc}[/red]")
        return None
    accepted = _review_weekly(draft, config, provider, profile)
    if accepted is None:
        return None
    storage.save_weekly(accepted, render_weekly(accepted))
    console.print(f"[green]周报已保存：{storage.weekly_markdown_path(week)}[/green]")
    return accepted


def _maybe_weekly(
    target: date,
    config: AppConfig,
    storage: Storage,
    provider: ResponsesProvider,
    profile: UserProfile,
) -> None:
    week = latest_review_week(target)
    start, end = week_bounds(week)
    if storage.load_weekly(week) is None and end <= target and storage.daily_records(start, end):
        _generate_week(week, config, storage, provider, profile)


@app.command()
def setup() -> None:
    """配置模型、数据目录、凭据和桌面提醒。"""
    current = load_config()
    console.print(Panel("配置和记录只保存在本机。", title="Harvest Setup"))
    provider_name = typer.prompt("Provider（deepseek/openai）", default=current.provider).strip().lower()
    if provider_name not in {"deepseek", "openai"}:
        raise typer.BadParameter("Provider 必须是 deepseek 或 openai")
    data_dir = Path(typer.prompt("数据目录", default=str(current.data_dir))).expanduser()
    reminder_time = typer.prompt("每日提醒时间", default=current.reminder_time).strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", reminder_time):
        raise typer.BadParameter("提醒时间格式应为 HH:MM")
    config = AppConfig(
        provider=provider_name,
        deepseek_model=current.deepseek_model,
        openai_model=current.openai_model,
        data_dir=data_dir,
        reminder_time=reminder_time,
        timezone=current.timezone,
        current_state_path=current.current_state_path,
    )
    save_config(config)
    Storage(data_dir).ensure()
    if typer.confirm(f"现在保存 {config.api_key_name} 到系统凭据库？", default=get_api_key(config) is None):
        _read_and_save_api_key(config)
    if typer.confirm("安装每日桌面提醒？", default=True):
        try:
            install_reminder(reminder_time)
            console.print(f"[green]提醒已启用：每天 {reminder_time}[/green]")
        except (OSError, subprocess.SubprocessError) as exc:
            console.print(f"[yellow]提醒安装失败，但不影响日报：{exc}[/yellow]")
    console.print(f"[green]配置已保存：{CONFIG_PATH}[/green]")
    if Storage(data_dir).load_profile() is None:
        console.print("下一步运行 [bold]harvest onboard[/bold] 建立用户画像。")


@app.command()
def auth() -> None:
    """把当前 Provider 的 API Key 保存到系统凭据库。"""
    config = load_config()
    if not _read_and_save_api_key(config):
        raise typer.Exit(1)
    _, source = get_api_key_with_source(config)
    console.print(f"凭据来源：{source}。可运行 harvest doctor --api-test 验证。")


@app.command()
def onboard(target_date: str | None = typer.Option(None, "--date", help="首份日报日期")) -> None:
    """通过问卷、真实样例和最多三轮反馈建立用户画像。"""
    target = _parse_date(target_date)
    config, storage = _context()
    existing = storage.load_profile()
    if existing is not None:
        console.print("[yellow]画像已经存在；请使用 harvest profile recalibrate。[/yellow]")
        return
    if storage.load_daily(target) is not None:
        console.print(f"[red]{target} 已有日报，请选择其他日期建立首份样例。[/red]")
        raise typer.Exit(1)
    pending = storage.load_onboarding() or OnboardingPending(date=target, created_at=datetime.now().astimezone())
    if pending.date != target:
        console.print(f"[yellow]发现 {pending.date} 的 onboarding，将继续该日期。[/yellow]")
        target = pending.date
    pending = pending.model_copy(
        update={
            "questionnaire": _collect_answers(
                ONBOARDING_QUESTIONS,
                pending.questionnaire,
                lambda value: storage.save_onboarding(pending.model_copy(update={"questionnaire": value})),
            )
        }
    )
    storage.save_onboarding(pending)
    pending = pending.model_copy(
        update={
            "daily_answers": _collect_answers(
                build_questions(),
                pending.daily_answers,
                lambda value: storage.save_onboarding(pending.model_copy(update={"daily_answers": value})),
            )
        }
    )
    storage.save_onboarding(pending)
    if not any(pending.daily_answers.values()):
        console.print("[yellow]首日样例至少需要一项真实回答。[/yellow]")
        return
    provider = _provider(config)
    content = pending.proposed_profile
    if content is None:
        try:
            content = build_initial_profile(pending.questionnaire, pending.daily_answers, provider).profile
        except ProviderError as exc:
            storage.save_onboarding(pending.model_copy(update={"last_error": str(exc)}))
            console.print(f"[red]画像建立失败：{exc}[/red]")
            return
        pending = pending.model_copy(update={"proposed_profile": content, "last_error": None})
        storage.save_onboarding(pending)
    draft: DailyDraft | None = None
    while True:
        if pending.sample_record is not None:
            draft = DailyDraft(
                record=pending.sample_record,
                project_suggestions=pending.sample_project_suggestions,
            )
        else:
            try:
                draft = generate_daily(
                    make_pending(target, pending.daily_answers), config, provider, [], content
                )
            except ProviderError as exc:
                storage.save_onboarding(pending.model_copy(update={"last_error": str(exc)}))
                console.print(f"[red]样例生成失败：{exc}[/red]")
                return
            pending = pending.model_copy(
                update={
                    "sample_record": draft.record,
                    "sample_project_suggestions": draft.project_suggestions,
                    "last_error": None,
                }
            )
            storage.save_onboarding(pending)
        _show_profile(content, f"画像草案 · 第 {pending.revision_round + 1} 版")
        _show_daily(draft.record)
        action = console.input("[Enter] 接受画像和首份日报 / 输入画像反馈 / q 暂停：").strip()
        if not action:
            profile = next_profile(content, None, "initial" if pending.revision_round == 0 else "revised")
            storage.save_profile(profile)
            storage.save_daily(draft.record, render_daily(draft.record))
            storage.save_calibration(
                CalibrationState(
                    onboarding_completed=True,
                    first_daily_date=target,
                    feedback_events=[
                        FeedbackEvent(date=target, kind="profile_feedback", text=item)
                        for item in pending.feedback
                    ],
                )
            )
            storage.delete_onboarding()
            console.print("[green]画像与首份日报已保存。[/green]")
            _confirm_project_updates(draft.project_suggestions, target, storage)
            return
        if action.lower() in {"q", "quit", "暂停"}:
            console.print("onboarding 进度已保存。")
            return
        if pending.revision_round >= 3:
            console.print("[yellow]已达到三轮修改上限；请接受或暂停，之后可重新校准。[/yellow]")
            continue
        try:
            proposal = revise_profile_content(
                content,
                action,
                provider,
                evidence={"first_day_answers": pending.daily_answers},
            )
        except ProviderError as exc:
            console.print(f"[red]画像修改失败：{exc}[/red]")
            continue
        pending = pending.model_copy(
            update={
                "revision_round": pending.revision_round + 1,
                "feedback": [*pending.feedback, action],
            }
        )
        if _proposal_confirm(content, proposal.profile):
            content = proposal.profile
            pending = pending.model_copy(
                update={
                    "proposed_profile": content,
                    "sample_record": None,
                    "sample_project_suggestions": [],
                }
            )
        storage.save_onboarding(pending)


@profile_app.callback()
def profile_show(ctx: typer.Context) -> None:
    """不带子命令时显示当前画像。"""
    if ctx.invoked_subcommand is not None:
        return
    _, storage = _context()
    profile = _require_profile(storage)
    _show_profile(profile, f"用户画像 · v{profile.version} · {profile.stage}")


@profile_app.command("recalibrate")
def profile_recalibrate() -> None:
    """根据当前反馈提出并确认一个新画像版本。"""
    config, storage = _context()
    profile = _require_profile(storage)
    feedback = typer.prompt("当前效果哪里好、哪里不像你、希望怎样调整").strip()
    if not feedback:
        return
    try:
        proposal = revise_profile_content(profile.content, feedback, _provider(config))
    except ProviderError as exc:
        console.print(f"[red]画像校准失败：{exc}[/red]")
        raise typer.Exit(1) from exc
    if _proposal_confirm(profile.content, proposal.profile):
        storage.save_profile(next_profile(proposal.profile, profile, "manual"))
        console.print("[green]新画像已生效。[/green]")


@profile_app.command("history")
def profile_history() -> None:
    """列出画像版本。"""
    _, storage = _context()
    for item in storage.profile_versions():
        console.print(f"v{item.version} · {item.stage} · {item.updated_at.isoformat()}")


@profile_app.command("restore")
def profile_restore(version: int = typer.Argument(..., min=1)) -> None:
    """把历史画像内容恢复为一个新的当前版本。"""
    _, storage = _context()
    current = _require_profile(storage)
    selected = storage.load_profile_version(version)
    if selected is None:
        console.print(f"[red]不存在画像版本 v{version}。[/red]")
        raise typer.Exit(1)
    if _proposal_confirm(current.content, selected.content):
        storage.save_profile(next_profile(selected.content, current, "restored"))
        console.print("[green]历史画像已恢复为新的当前版本。[/green]")


@profile_app.command("import-legacy")
def profile_import_legacy(
    path: Path = typer.Argument(REPORT_PROFILE_PATH, help="旧版 report-profile.md 路径"),
) -> None:
    """显式导入旧版 Markdown 画像；不会自动读取个人文件。"""
    _, storage = _context()
    if storage.load_profile() is not None:
        console.print("[red]当前数据目录已经存在结构化画像。[/red]")
        raise typer.Exit(1)
    if not path.exists():
        console.print(f"[red]文件不存在：{path}[/red]")
        raise typer.Exit(1)
    content = legacy_profile_content(path.read_text(encoding="utf-8"))
    profile = next_profile(content, None, "initial")
    _show_profile(profile, "旧版画像迁移预览")
    if typer.confirm("确认导入？", default=True):
        storage.save_profile(profile)
        storage.save_calibration(CalibrationState(onboarding_completed=True))
        console.print("[green]旧版画像已导入；原文件未修改。[/green]")


@project_app.command("list")
def project_list(show_all: bool = typer.Option(False, "--all")) -> None:
    _, storage = _context()
    projects = storage.load_project_memory().projects
    if not show_all:
        projects = [item for item in projects if item.status == "active"]
    for item in sorted(projects, key=lambda value: (value.status, value.name.casefold())):
        suffix = f" · next: {item.next_step}" if item.next_step else ""
        console.print(f"• [bold]{item.name}[/bold] · {item.status}{suffix}")


@project_app.command("add")
def project_add(name: str, next_step: str | None = typer.Option(None, "--next-step", "-n")) -> None:
    _, storage = _context()
    memory = storage.load_project_memory()
    if find_project(memory, name):
        raise typer.BadParameter("项目已存在")
    storage.save_project_memory(
        upsert_project(memory, name=name, status="active", target=date.today(), next_step=next_step)
    )


@project_app.command("update")
def project_update(name: str, next_step: str | None = typer.Option(None, "--next-step", "-n")) -> None:
    _, storage = _context()
    memory = storage.load_project_memory()
    item = find_project(memory, name)
    if item is None:
        raise typer.BadParameter("未找到项目")
    storage.save_project_memory(
        upsert_project(
            memory,
            name=item.name,
            status=item.status,
            target=date.today(),
            next_step=next_step,
            require_existing=True,
        )
    )


def _set_project_status(name: str, status: str) -> None:
    _, storage = _context()
    memory = storage.load_project_memory()
    item = find_project(memory, name)
    if item is None:
        raise typer.BadParameter("未找到项目")
    storage.save_project_memory(
        upsert_project(memory, name=item.name, status=status, target=date.today(), require_existing=True)
    )


@project_app.command("pause")
def project_pause(name: str) -> None:
    _set_project_status(name, "paused")


@project_app.command("complete")
def project_complete(name: str) -> None:
    _set_project_status(name, "completed")


@project_app.command("activate")
def project_activate(name: str) -> None:
    _set_project_status(name, "active")


@app.command()
def daily(target_date: str | None = typer.Option(None, "--date")) -> None:
    """回答六个引导问题并生成日报。"""
    target = _parse_date(target_date)
    config, storage = _context()
    profile = _require_profile(storage)
    if storage.load_daily(target):
        console.print(f"[yellow]{target} 已有正式日报。[/yellow]")
        return
    snapshot = _snapshot(config, storage, target)
    _show_context_snapshot(snapshot)
    pending = storage.load_pending(target) or make_pending(target, {})
    storage.save_pending(pending)
    answers = _collect_answers(
        build_questions(snapshot),
        pending.answers,
        lambda value: storage.save_pending(pending.model_copy(update={"answers": value})),
    )
    pending = pending.model_copy(update={"answers": answers})
    storage.save_pending(pending)
    if not any(answers.values()):
        storage.delete_pending(target)
        return
    _process_pending(pending, config, storage, profile)


@app.command()
def resume(target_date: str | None = typer.Argument(None)) -> None:
    target = _parse_date(target_date)
    config, storage = _context()
    profile = _require_profile(storage)
    pending = storage.load_pending(target)
    if pending is None:
        console.print(f"[yellow]没有找到 {target} 的 pending。[/yellow]")
        raise typer.Exit(1)
    snapshot = _snapshot(config, storage, target)
    answers = _collect_answers(
        build_questions(snapshot),
        pending.answers,
        lambda value: storage.save_pending(pending.model_copy(update={"answers": value})),
    )
    _process_pending(pending.model_copy(update={"answers": answers}), config, storage, profile)


@app.command()
def revise(
    target_date: str | None = typer.Argument(None),
    correction: str | None = typer.Option(None, "--correction", "-c"),
) -> None:
    target = _parse_date(target_date)
    config, storage = _context()
    profile = _require_profile(storage)
    record = storage.load_daily(target)
    if record is None:
        console.print(f"[red]没有找到 {target} 日报。[/red]")
        raise typer.Exit(1)
    correction = (correction or typer.prompt("请说明要修改什么")).strip()
    if not correction:
        return
    provider = _provider(config)
    snapshot = _snapshot(config, storage, target)
    _save_feedback(storage, target, correction)
    try:
        draft = revise_daily(
            DailyDraft(record=record, project_suggestions=[]),
            correction,
            config,
            provider,
            snapshot.active_projects,
            profile,
        )
    except ProviderError as exc:
        console.print(f"[red]修订失败：{exc}[/red]")
        raise typer.Exit(1) from exc
    accepted = _review_daily(
        draft,
        config,
        provider,
        snapshot.active_projects,
        profile,
        on_feedback=lambda text: _save_feedback(storage, target, text),
    )
    if accepted:
        storage.save_daily(accepted.record, render_daily(accepted.record))


@app.command("show")
def show_record(target_date: str | None = typer.Argument(None), week: str | None = typer.Option(None, "--week")) -> None:
    _, storage = _context()
    if week:
        record = storage.load_weekly(week)
        if record is None:
            raise typer.BadParameter("未找到周报")
        _show_weekly(record)
        return
    record = storage.load_daily(_parse_date(target_date))
    if record is None:
        raise typer.BadParameter("未找到日报")
    _show_daily(record)


@app.command()
def weekly(week: str | None = typer.Option(None, "--week")) -> None:
    config, storage = _context()
    profile = _require_profile(storage)
    selected = week or latest_review_week(date.today())
    if storage.load_weekly(selected):
        console.print(f"[yellow]{selected} 已有周报。[/yellow]")
        return
    _generate_week(selected, config, storage, _provider(config), profile)


@app.command("notify", hidden=True)
def notify_user() -> None:
    """由系统定时器调用，只显示本地通知。"""
    try:
        send_notification()
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[red]通知失败：{exc}[/red]")
        raise typer.Exit(1) from exc


class _Ping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]


@app.command()
def doctor(api_test: bool = typer.Option(False, "--api-test")) -> None:
    """检查配置、画像、数据目录、凭据、提醒和可选 API 连通性。"""
    checks: list[tuple[str, bool, str]] = []
    try:
        config = load_config()
        storage = Storage(config.data_dir)
        storage.ensure()
        key, source = get_api_key_with_source(config)
        enabled, detail = timer_status()
        checks.extend(
            [
                ("配置", CONFIG_PATH.exists(), str(CONFIG_PATH)),
                ("数据目录", config.data_dir.is_dir(), str(config.data_dir)),
                ("用户画像", storage.load_profile() is not None, str(storage.profile_path())),
                ("API Key", key is not None, source),
                ("桌面提醒", enabled, detail),
            ]
        )
        if api_test:
            result, _ = build_provider(config).generate(
                instructions='只输出 {"status":"ok"}。',
                input_text="连通性检查",
                output_type=_Ping,
                schema_name="connection_test",
            )
            checks.append(("API 连通性", result.status == "ok", f"{config.provider}/{config.model}"))
    except (OSError, ValueError, ProviderError) as exc:
        checks.append(("运行检查", False, str(exc)))
    failed = False
    for name, ok, detail in checks:
        failed = failed or not ok
        console.print(f"{'[green]✓[/green]' if ok else '[red]✗[/red]'} {name}: {detail}")
    if failed:
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
