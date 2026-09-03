from __future__ import annotations

import getpass
import json
import re
import subprocess
from dataclasses import replace
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
    DailyQuestion,
    DailyRecord,
    FeedbackEvent,
    NetworkTrace,
    OnboardingPending,
    PendingDaily,
    ProfileContent,
    ProjectSuggestion,
    UserProfile,
    WeeklyRecord,
)
from harvest.personalization import legacy_profile_content, next_profile, profile_diff
from harvest.providers import ProviderError, ResponsesProvider, build_provider
from harvest.reminder import install_reminder, send_notification, timer_status
from harvest.render import render_daily, render_profile, render_weekly
from harvest.cli_help import ChineseTyper
from harvest.service import (
    DailyDraft,
    build_initial_onboarding,
    build_questions,
    generate_daily,
    generate_trial_daily,
    generate_weekly,
    latest_review_week,
    make_pending,
    revise_daily,
    revise_onboarding,
    revise_profile_content,
    revise_weekly,
    week_bounds,
)
from harvest.storage import Storage


app = ChineseTyper(
    name="harvest",
    help="本地优先、可校准的个人复盘工具。",
    invoke_without_command=True,
)
project_app = ChineseTyper(help="维护跨天项目记忆。", no_args_is_help=True)
profile_app = ChineseTyper(help="查看、校准和恢复用户画像。", invoke_without_command=True)
app.add_typer(project_app, name="project")
app.add_typer(profile_app, name="profile")
console = Console()


GUIDED_PROFILE_CHOICES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "current_context",
        "你目前主要处在哪些阶段或角色？",
        ("学生或备考", "工作或实习", "独立项目", "自由职业", "生活调整期"),
    ),
    (
        "recurring_threads",
        "你希望长期关注哪些领域？",
        ("项目与工作", "学习与技术", "创作与兴趣", "生活与健康", "关系与家庭"),
    ),
    (
        "review_purpose",
        "你最希望复盘帮助你看清什么？",
        ("真实进展", "反复卡点", "时间与注意力", "状态变化", "下一步方向"),
    ),
    (
        "progress_signals",
        "哪些变化对你来说算真正的进展？",
        ("完成可交付结果", "理解关键机制", "解决具体问题", "形成稳定习惯", "明确下一步"),
    ),
    (
        "expression",
        "你希望日志怎样表达？",
        ("简洁直接", "自然克制", "温和但不空泛", "更重事实", "允许保留矛盾和未完成"),
    ),
    (
        "actions",
        "你希望 AI 怎样给出建议？",
        ("只给一个核心下一步", "给一到两个具体建议", "先指出依据再建议", "少建议多观察", "不替我做重要判断"),
    ),
)

LEARNING_HABIT_QUESTION = (
    "learning_habits",
    "回忆最近一次真正弄懂难点或解决卡点的过程：你先做了什么、卡在哪里、最后靠什么突破？",
)

FEEDBACK_CATEGORIES = {
    "1": "用户画像",
    "2": "每日问题",
    "3": "日志内容",
    "4": "表达格式",
}


class _ConnectionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"]


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
        console.print("[yellow]尚未建立用户画像，请直接运行 harvest 完成首次向导。[/yellow]")
        raise typer.Exit(1)
    return profile


def _show_daily(record: DailyRecord, title: str = "日报预览") -> None:
    console.print(Panel(Markdown(render_daily(record)), border_style="green", title=title))


def _show_weekly(record: WeeklyRecord) -> None:
    console.print(Panel(Markdown(render_weekly(record)), border_style="cyan", title="周报预览"))


def _show_profile(profile: UserProfile | ProfileContent, title: str = "用户画像") -> None:
    content = profile.content if isinstance(profile, UserProfile) else profile
    console.print(Panel(Markdown(render_profile(content)), title=title, border_style="cyan"))


def _show_context_snapshot(snapshot: ContextSnapshot) -> None:
    lines: list[str] = []
    if snapshot.active_projects:
        lines.append("[bold]进行中的项目[/bold]")
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
    console.print(f"当前 AI 服务商：[bold]{config.provider}[/bold]；模型：[bold]{config.model}[/bold]")
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


def _is_pause(value: str) -> bool:
    return value.strip().lower() in {"q", "quit", "暂停", "退出"}


def _prompt_guided_choice(prompt: str, options: tuple[str, ...]) -> str | None:
    lines = [f"{index}. {item}" for index, item in enumerate(options, start=1)]
    console.print(Panel("\n".join(lines), title=prompt))
    raw = typer.prompt("输入编号（可多选，用逗号分隔）或直接填写；回车跳过，q 暂停", default="", show_default=False)
    if _is_pause(raw):
        return None
    selected: list[str] = []
    for token in re.split(r"[,，、]", raw):
        item = token.strip()
        if not item:
            continue
        if item.isdigit() and 1 <= int(item) <= len(options):
            value = options[int(item) - 1]
        else:
            value = item
        if value not in selected:
            selected.append(value)
    return "、".join(selected)


def _collect_guided_profile(pending: OnboardingPending, storage: Storage) -> OnboardingPending | None:
    current = pending
    for key, prompt, options in GUIDED_PROFILE_CHOICES:
        if key in current.questionnaire:
            continue
        answer = _prompt_guided_choice(prompt, options)
        if answer is None:
            storage.save_onboarding(current)
            return None
        current = current.model_copy(
            update={"questionnaire": {**current.questionnaire, key: answer}}
        )
        storage.save_onboarding(current)
    learning_key, learning_prompt = LEARNING_HABIT_QUESTION
    if learning_key not in current.questionnaire:
        answer = typer.prompt(
            learning_prompt + "（可回车跳过，输入 q 暂停）", default="", show_default=False
        ).strip()
        if _is_pause(answer):
            storage.save_onboarding(current)
            return None
        current = current.model_copy(
            update={"questionnaire": {**current.questionnaire, learning_key: answer}}
        )
        storage.save_onboarding(current)
    return current


def _show_questions(questions: list[DailyQuestion], title: str = "个人每日问题") -> None:
    lines = [f"{index}. {item.prompt}" for index, item in enumerate(questions, start=1)]
    console.print(Panel("\n".join(lines), title=title, border_style="cyan"))


def _question_diff(before: list[DailyQuestion], after: list[DailyQuestion]) -> list[str]:
    old = {item.id: item for item in before}
    new = {item.id: item for item in after}
    changes: list[str] = []
    added = [item.prompt for key, item in new.items() if key not in old]
    removed = [item.prompt for key, item in old.items() if key not in new]
    modified = [
        new[key].prompt for key in old.keys() & new.keys() if old[key] != new[key]
    ]
    if added:
        changes.append("新增问题：" + "；".join(added))
    if removed:
        changes.append("删除问题：" + "；".join(removed))
    if modified:
        changes.append("调整问题：" + "；".join(modified))
    return changes


def _show_design_diff(
    before_profile: ProfileContent,
    before_questions: list[DailyQuestion],
    after_profile: ProfileContent,
    after_questions: list[DailyQuestion],
) -> None:
    changes = [*profile_diff(before_profile, after_profile), *_question_diff(before_questions, after_questions)]
    console.print(Panel("\n".join(f"• {item}" for item in changes) or "内容没有变化", title="本轮变化"))
    _show_profile(after_profile, "拟议画像")
    _show_questions(after_questions, "拟议每日问题")


def _select_feedback() -> tuple[list[str], str] | None:
    console.print(
        Panel(
            "\n".join(f"{key}. {value}" for key, value in FEEDBACK_CATEGORIES.items()),
            title="希望改进哪些部分",
        )
    )
    raw = typer.prompt(
        "输入编号（可多选）；直接回车表示满意，q 暂停", default="", show_default=False
    ).strip()
    if _is_pause(raw):
        return None
    if not raw:
        return [], ""
    categories = [
        FEEDBACK_CATEGORIES[token]
        for token in re.split(r"[,，、]", raw)
        if token.strip() in FEEDBACK_CATEGORIES
    ]
    categories = list(dict.fromkeys(categories))
    if not categories:
        console.print("[yellow]没有识别到分类编号，请重新选择。[/yellow]")
        return _select_feedback()
    feedback = typer.prompt("请具体说明希望怎样改进").strip()
    if not feedback:
        console.print("[yellow]没有填写改进内容，本轮不修改。[/yellow]")
        return [], ""
    return categories, feedback


def _show_trace(trace: NetworkTrace, *, include_payloads: bool = False) -> None:
    usage = trace.usage
    lines = [
        f"AI 服务商：{trace.provider}",
        f"模型：{trace.model}",
        f"接口：{trace.endpoint}",
        f"HTTP 状态：{trace.status_code}",
        f"结构名称：{trace.schema_name}",
        f"耗时：{trace.elapsed_ms} ms",
        f"Token：输入 {usage.input_tokens or 0} / 输出 {usage.output_tokens or 0} / 合计 {usage.total_tokens or 0}",
    ]
    console.print(Panel("\n".join(lines), title="网络与格式检查"))
    if include_payloads:
        detail = {
            "request": trace.request_payload,
            "response": trace.response_payload,
        }
        console.print(Panel(json.dumps(detail, ensure_ascii=False, indent=2), title="脱敏技术详情"))


def _configure_and_test_api() -> tuple[AppConfig, ResponsesProvider] | None:
    current = load_config()
    console.print(Panel("第一步只配置 AI 服务商与 API Key。测试会发送一次最小真实请求。", title="步骤 1/4 · API 配置"))
    while True:
        provider_name = typer.prompt(
            "AI 服务商（deepseek/openai）", default=current.provider
        ).strip().lower()
        if _is_pause(provider_name):
            return None
        if provider_name not in {"deepseek", "openai"}:
            console.print("[yellow]请输入 deepseek 或 openai。[/yellow]")
            continue
        config = replace(current, provider=provider_name)
        save_config(config)
        if get_api_key(config) is None and not _read_and_save_api_key(config):
            console.print(
                f"[yellow]未保存 Key。凭据库不可用时，请先设置环境变量 {config.api_key_name} 后重试。[/yellow]"
            )
            action = console.input("[Enter] 重新输入 / q 暂停：").strip()
            if _is_pause(action):
                return None
            continue
        try:
            provider = build_provider(config)
            _, _, trace = provider.generate_traced(
                instructions='只返回 {"status":"ok"}，用于验证网络和结构化响应。',
                input_text="Harvest 首次启动连接测试。",
                output_type=_ConnectionCheck,
                schema_name="harvest_connection_check",
            )
        except ProviderError as exc:
            console.print(f"[red]API 验证失败：{exc}[/red]")
            action = console.input("r 重试 / k 更换 API Key / c 更换服务商 / q 暂停：").strip().lower()
            if action == "r":
                continue
            if action == "k":
                _read_and_save_api_key(config)
                current = config
                continue
            if _is_pause(action):
                return None
            current = config
            continue
        console.print("[green]✓ API Key、网络与结构化响应均可用。[/green]")
        _show_trace(trace)
        if typer.confirm("查看本次测试的脱敏技术详情？", default=False):
            _show_trace(trace, include_payloads=True)
        return config, provider


def _save_onboarding(storage: Storage, pending: OnboardingPending, **updates) -> OnboardingPending:
    current = pending.model_copy(update=updates)
    storage.save_onboarding(current)
    return current


def _revise_onboarding_design(
    pending: OnboardingPending,
    categories: list[str],
    feedback: str,
    provider: ResponsesProvider,
    storage: Storage,
) -> tuple[OnboardingPending, bool]:
    if pending.proposed_profile is None or not pending.proposed_questions:
        raise ValueError("首次向导缺少可修订的画像或问题集")
    try:
        proposal = revise_onboarding(
            pending.proposed_profile,
            pending.proposed_questions,
            categories,
            feedback,
            provider,
            trial_answers=pending.daily_answers,
            test_report=pending.sample_record.report if pending.sample_record else None,
        )
    except ProviderError as exc:
        console.print(f"[red]修改失败：{exc}[/red]")
        return _save_onboarding(storage, pending, last_error=str(exc)), False
    _show_design_diff(
        pending.proposed_profile,
        pending.proposed_questions,
        proposal.profile,
        proposal.daily_questions,
    )
    if not typer.confirm("应用本轮修改？", default=True):
        console.print("本轮修改未应用。")
        return pending, False
    current = _save_onboarding(
        storage,
        pending,
        proposed_profile=proposal.profile,
        proposed_questions=proposal.daily_questions,
        revision_round=pending.revision_round + 1,
        feedback=[*pending.feedback, feedback],
        feedback_categories=list(dict.fromkeys([*pending.feedback_categories, *categories])),
        last_error=None,
    )
    return current, True


def _collect_trial_answers(pending: OnboardingPending, storage: Storage) -> OnboardingPending:
    console.print(
        Panel(
            "这是一次真实 API 测试，不是正式日报，也不会写入日报目录。\n"
            "你可以认真回答，也可以每题直接回车；所有问题都可跳过。",
            title="步骤 3/4 · 测试输入、输出、网络与格式",
            border_style="yellow",
        )
    )
    question_pairs = tuple((item.id, item.prompt) for item in pending.proposed_questions)
    answers = _collect_answers(
        question_pairs,
        pending.daily_answers,
        lambda value: storage.save_onboarding(pending.model_copy(update={"daily_answers": value})),
    )
    return _save_onboarding(storage, pending, daily_answers=answers)


def _run_trial(
    pending: OnboardingPending,
    config: AppConfig,
    provider: ResponsesProvider,
    storage: Storage,
) -> OnboardingPending | None:
    if pending.proposed_profile is None:
        raise ValueError("首次向导缺少画像草案")
    try:
        draft, trace = generate_trial_daily(
            make_pending(pending.date, pending.daily_answers),
            config,
            provider,
            pending.proposed_profile,
        )
    except ProviderError as exc:
        pending = _save_onboarding(storage, pending, last_error=str(exc))
        console.print(f"[red]测试失败：{exc}[/red]")
        action = console.input("[Enter] 稍后重试 / q 暂停：").strip()
        return None if _is_pause(action) else pending
    pending = _save_onboarding(
        storage,
        pending,
        step="trial_review",
        sample_record=draft.record,
        sample_project_suggestions=draft.project_suggestions,
        last_trace=trace,
        trial_run_count=pending.trial_run_count + 1,
        last_error=None,
    )
    answered = sum(bool(value) for value in pending.daily_answers.values())
    console.print(
        Panel(
            "✓ 测试输入已组装（有效回答：%d）\n"
            "✓ 真实网络请求成功\n"
            "✓ 响应符合约定 JSON 格式\n"
            "✓ 测试日志已生成且尚未保存为正式日报" % answered,
            title="测试状态",
            border_style="green",
        )
    )
    _show_daily(draft.record, "测试日志 · 不会保存")
    _show_trace(trace)
    if typer.confirm("查看本次测试的脱敏请求与响应？", default=False):
        _show_trace(trace, include_payloads=True)
    return pending


def _finish_onboarding(pending: OnboardingPending, storage: Storage) -> None:
    if pending.proposed_profile is None or not pending.proposed_questions:
        raise ValueError("首次向导结果不完整")
    profile = next_profile(
        pending.proposed_profile,
        None,
        "initial" if pending.revision_round == 0 else "revised",
        daily_questions=pending.proposed_questions,
    )
    storage.save_profile(profile)
    storage.save_calibration(
        CalibrationState(
            onboarding_version=2,
            onboarding_completed=True,
            first_daily_date=None,
        )
    )
    # 删除问卷原文、测试答案、测试报告和网络追踪，只保留用户确认后的画像与问题集。
    storage.delete_onboarding()
    console.print(
        Panel(
            "首次调试已完成，测试数据已清除；尚未创建任何正式日报。\n\n"
            "直接运行 harvest：开始今天的正式复盘\n"
            "harvest settings：修改服务商、数据目录或提醒\n"
            "harvest --help：查看全部命令",
            title="Harvest 已准备好",
            border_style="green",
        )
    )


def _run_onboarding(
    config: AppConfig, storage: Storage, provider: ResponsesProvider
) -> None:
    pending = storage.load_onboarding() or OnboardingPending(
        date=date.today(), created_at=datetime.now().astimezone()
    )
    storage.save_onboarding(pending)
    while True:
        if pending.step == "profile_inputs":
            console.print(
                Panel(
                    "通过六组选择和一个具体经历，建立第一版用户画像与每日问题。\n"
                    "选择题可多选或自定义，任何一题都可以跳过。",
                    title="步骤 2/4 · 选择与用户画像",
                )
            )
            collected = _collect_guided_profile(pending, storage)
            if collected is None:
                console.print("进度已保存，下次运行 harvest 会继续。")
                return
            pending = collected
            try:
                proposal = build_initial_onboarding(pending.questionnaire, provider)
            except ProviderError as exc:
                _save_onboarding(storage, pending, last_error=str(exc))
                console.print(f"[red]画像与问题生成失败：{exc}[/red]")
                return
            pending = _save_onboarding(
                storage,
                pending,
                step="profile_review",
                proposed_profile=proposal.profile,
                proposed_questions=proposal.daily_questions,
                last_error=None,
            )

        if pending.step == "profile_review":
            if pending.proposed_profile is None:
                pending = _save_onboarding(storage, pending, step="profile_inputs")
                continue
            _show_profile(pending.proposed_profile, "画像草案")
            _show_questions(pending.proposed_questions, "个人每日问题草案")
            action = console.input("[Enter] 确认并开始测试 / m 提出修改 / q 暂停：").strip().lower()
            if _is_pause(action):
                console.print("进度已保存，下次运行 harvest 会继续。")
                return
            if action == "m":
                if pending.revision_round >= 3:
                    console.print("[yellow]已达到三轮修改上限，请确认测试或暂停。[/yellow]")
                    continue
                selection = _select_feedback()
                if selection is None:
                    console.print("进度已保存，下次运行 harvest 会继续。")
                    return
                categories, feedback = selection
                if feedback:
                    pending, _ = _revise_onboarding_design(
                        pending, categories, feedback, provider, storage
                    )
                continue
            pending = _save_onboarding(storage, pending, step="trial_input")

        if pending.step == "trial_input":
            pending = _collect_trial_answers(pending, storage)
            trial = _run_trial(pending, config, provider, storage)
            if trial is None:
                console.print("测试进度已保存，下次运行 harvest 会继续。")
                return
            pending = trial
            if pending.step != "trial_review":
                continue

        if pending.step == "trial_review":
            console.print(
                Panel(
                    "请根据刚才的真实测试，决定是否调整画像、问题或日志表现。\n"
                    "直接回车表示满意并完成首次调试。",
                    title="步骤 4/4 · 改进建议与确认",
                )
            )
            selection = _select_feedback()
            if selection is None:
                console.print("进度已保存，下次运行 harvest 会继续。")
                return
            categories, feedback = selection
            if not feedback:
                _finish_onboarding(pending, storage)
                return
            if pending.revision_round >= 3:
                console.print("[yellow]已达到三轮修改上限；请直接回车确认，或 q 暂停。[/yellow]")
                continue
            old_questions = list(pending.proposed_questions)
            revised, accepted = _revise_onboarding_design(
                pending, categories, feedback, provider, storage
            )
            if not accepted:
                pending = revised
                continue
            new_ids = {item.id for item in revised.proposed_questions}
            if pending.trial_run_count == 1:
                kept_answers: dict[str, str] = {}
                console.print("第一次修改后会重新询问全部测试问题。")
            else:
                old_ids = {item.id for item in old_questions}
                kept_answers = {
                    key: value
                    for key, value in pending.daily_answers.items()
                    if key in old_ids and key in new_ids
                }
                console.print("已保留 ID 未变化的问题答案，只询问新增问题。")
            pending = _save_onboarding(
                storage,
                revised,
                step="trial_input",
                daily_answers=kept_answers,
                sample_record=None,
                sample_project_suggestions=[],
                last_trace=None,
            )


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


def _start_or_resume_onboarding() -> None:
    config, storage = _context()
    if storage.load_profile() is not None:
        console.print("[yellow]用户画像已经存在；可直接运行 harvest 开始正式复盘。[/yellow]")
        return
    pending = storage.load_onboarding()
    if pending is not None and get_api_key(config) is not None:
        console.print(f"[cyan]继续上次保存的首次调试：{pending.step}[/cyan]")
        _run_onboarding(config, storage, _provider(config))
        return
    configured = _configure_and_test_api()
    if configured is None:
        console.print("首次调试已暂停。")
        return
    config, provider = configured
    storage = Storage(config.data_dir)
    storage.ensure()
    _run_onboarding(config, storage, provider)


@app.callback()
def main(ctx: typer.Context) -> None:
    """不带命令时，首次运行进入向导，完成后开始今天的正式复盘。"""
    if ctx.invoked_subcommand is not None:
        return
    _, storage = _context()
    if storage.load_profile() is None:
        _start_or_resume_onboarding()
    else:
        daily()


@app.command()
def setup() -> None:
    """兼容旧命令：启动或继续首次调试。"""
    _start_or_resume_onboarding()


@app.command()
def settings() -> None:
    """修改 AI 服务商、数据目录和桌面提醒。"""
    current = load_config()
    console.print(Panel("配置和记录只保存在本机。API Key 只写入系统凭据库。", title="Harvest 设置"))
    provider_name = typer.prompt("AI 服务商（deepseek/openai）", default=current.provider).strip().lower()
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
        console.print("下一步直接运行 [bold]harvest[/bold] 完成首次调试。")


@app.command()
def auth() -> None:
    """把当前 AI 服务商的 API Key 保存到系统凭据库。"""
    config = load_config()
    if not _read_and_save_api_key(config):
        raise typer.Exit(1)
    _, source = get_api_key_with_source(config)
    console.print(f"凭据来源：{source}。可运行 harvest doctor --api-test 验证。")


@app.command()
def onboard(target_date: str | None = typer.Option(None, "--date", help="首份日报日期")) -> None:
    """兼容旧命令：启动或继续首次调试。"""
    if target_date is not None:
        console.print("[yellow]--date 已忽略：首次测试不会创建正式日报。[/yellow]")
    _start_or_resume_onboarding()


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
    """列出进行中的项目；--all 同时显示暂停和已完成项目。"""
    _, storage = _context()
    projects = storage.load_project_memory().projects
    if not show_all:
        projects = [item for item in projects if item.status == "active"]
    for item in sorted(projects, key=lambda value: (value.status, value.name.casefold())):
        suffix = f" · next: {item.next_step}" if item.next_step else ""
        console.print(f"• [bold]{item.name}[/bold] · {item.status}{suffix}")


@project_app.command("add")
def project_add(name: str, next_step: str | None = typer.Option(None, "--next-step", "-n")) -> None:
    """添加一个需要跨天记住的项目。"""
    _, storage = _context()
    memory = storage.load_project_memory()
    if find_project(memory, name):
        raise typer.BadParameter("项目已存在")
    storage.save_project_memory(
        upsert_project(memory, name=name, status="active", target=date.today(), next_step=next_step)
    )


@project_app.command("update")
def project_update(name: str, next_step: str | None = typer.Option(None, "--next-step", "-n")) -> None:
    """更新项目的下一步。"""
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
    """暂停跟踪一个项目。"""
    _set_project_status(name, "paused")


@project_app.command("complete")
def project_complete(name: str) -> None:
    """把项目标记为已完成。"""
    _set_project_status(name, "completed")


@project_app.command("activate")
def project_activate(name: str) -> None:
    """重新启用一个项目。"""
    _set_project_status(name, "active")


@app.command()
def daily(target_date: str | None = typer.Option(None, "--date")) -> None:
    """回答个人引导问题并生成正式日报。"""
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
        build_questions(profile),
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
    """继续指定日期尚未完成的正式日报。"""
    target = _parse_date(target_date)
    config, storage = _context()
    profile = _require_profile(storage)
    pending = storage.load_pending(target)
    if pending is None:
        console.print(f"[yellow]没有找到 {target} 的 pending。[/yellow]")
        raise typer.Exit(1)
    snapshot = _snapshot(config, storage, target)
    answers = _collect_answers(
        build_questions(profile),
        pending.answers,
        lambda value: storage.save_pending(pending.model_copy(update={"answers": value})),
    )
    _process_pending(pending.model_copy(update={"answers": answers}), config, storage, profile)


@app.command()
def revise(
    target_date: str | None = typer.Argument(None),
    correction: str | None = typer.Option(None, "--correction", "-c"),
) -> None:
    """修订一份已保存的正式日报。"""
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
    """查看指定日期的日报或指定周的周报。"""
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
    """生成指定周的周报。"""
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
