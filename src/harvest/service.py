from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from harvest.config import AppConfig
from harvest.models import (
    DailyAnalysis,
    DailyQuestion,
    DailyRecord,
    NetworkTrace,
    OnboardingProposal,
    PendingDaily,
    ProfileContent,
    ProfileProposal,
    ProjectItem,
    ProjectSuggestion,
    UserProfile,
    WeeklyRecord,
    WeeklyReview,
)
from harvest.prompts import (
    DAILY_INSTRUCTIONS,
    ONBOARDING_INSTRUCTIONS,
    PROFILE_INSTRUCTIONS,
    WEEKLY_INSTRUCTIONS,
    correction_input,
    daily_input,
    onboarding_initial_input,
    onboarding_revision_input,
    profile_initial_input,
    profile_revision_input,
    weekly_input,
)
from harvest.providers import ProviderError, ResponsesProvider
from harvest.personalization import enforce_profile_boundaries


QUESTION_KEYS = (
    (
        "recall_cues",
        "先从今天打开或接触过的东西开始想。上过的课、工作、代码、网页、对话、笔记或出门做的事——它们分别让你做了什么？不用分类。",
    ),
    (
        "recent_context",
        "看看上面的近期记忆，今天这些事情有推进吗？做了哪个具体动作？完全没碰也可以直接说；还有没有临时出现的新事情？",
    ),
    ("progress", "今天哪些事情真的向前走了？可以是完成、做到一半、解决问题，或者只是确认下一步。"),
    ("work_state", "今天哪一刻最投入、最有收获、最累或最容易被打断？只说最明显的片段和原因。"),
    ("basic_care", "今天吃饭、喝水、睡眠、活动身体等基本状态怎么样？不用打分，想到哪项说哪项。"),
    ("tomorrow", "明天重新接上时，最想先做哪一步？"),
)


@dataclass(frozen=True)
class DailyDraft:
    record: DailyRecord
    project_suggestions: list[ProjectSuggestion]


def build_questions(profile: UserProfile | object | None = None) -> tuple[tuple[str, str], ...]:
    # ContextSnapshot was accepted by v0.3 callers; keep it as a harmless legacy argument.
    if isinstance(profile, UserProfile) and profile.daily_questions:
        return tuple((item.id, item.prompt) for item in profile.daily_questions)
    return QUESTION_KEYS


def make_pending(target: date, answers: dict[str, str], *, now: datetime | None = None) -> PendingDaily:
    return PendingDaily(date=target, created_at=now or datetime.now().astimezone(), answers=answers)


def validate_daily_sections(report, profile: UserProfile | ProfileContent) -> None:
    content = profile.content if isinstance(profile, UserProfile) else profile
    expected = [(theme.id, theme.title) for theme in content.themes]
    actual = [(section.theme_id, section.title) for section in report.sections]
    if actual != expected:
        raise ProviderError(f"模型返回的主线与画像不一致：expected={expected}, actual={actual}")


def validate_weekly_sections(review: WeeklyReview, profile: UserProfile) -> None:
    expected = [(theme.id, theme.title) for theme in profile.content.themes]
    actual = [(section.theme_id, section.title) for section in review.sections]
    if actual != expected:
        raise ProviderError(f"模型返回的周报主线与画像不一致：expected={expected}, actual={actual}")


def build_initial_profile(
    questionnaire: dict[str, str], daily_answers: dict[str, str], provider: ResponsesProvider
) -> ProfileProposal:
    proposal, _ = provider.generate(
        instructions=PROFILE_INSTRUCTIONS,
        input_text=profile_initial_input(questionnaire, daily_answers),
        output_type=ProfileProposal,
        schema_name="harvest_profile_initial",
    )
    return proposal.model_copy(update={"profile": enforce_profile_boundaries(proposal.profile)})


def build_initial_onboarding(
    questionnaire: dict[str, str], provider: ResponsesProvider
) -> OnboardingProposal:
    proposal, _ = provider.generate(
        instructions=ONBOARDING_INSTRUCTIONS,
        input_text=onboarding_initial_input(questionnaire),
        output_type=OnboardingProposal,
        schema_name="harvest_onboarding_initial",
    )
    return proposal.model_copy(update={"profile": enforce_profile_boundaries(proposal.profile)})


def revise_onboarding(
    current: ProfileContent,
    questions: list[DailyQuestion],
    categories: list[str],
    feedback: str,
    provider: ResponsesProvider,
    *,
    trial_answers: dict[str, str] | None = None,
    test_report=None,
) -> OnboardingProposal:
    proposal, _ = provider.generate(
        instructions=ONBOARDING_INSTRUCTIONS,
        input_text=onboarding_revision_input(
            current,
            questions,
            categories,
            feedback,
            trial_answers=trial_answers,
            test_report=test_report,
        ),
        output_type=OnboardingProposal,
        schema_name="harvest_onboarding_revision",
    )
    return proposal.model_copy(update={"profile": enforce_profile_boundaries(proposal.profile)})


def revise_profile_content(
    current: ProfileContent,
    feedback: str,
    provider: ResponsesProvider,
    *,
    evidence: dict | None = None,
) -> ProfileProposal:
    proposal, _ = provider.generate(
        instructions=PROFILE_INSTRUCTIONS,
        input_text=profile_revision_input(current, feedback, evidence=evidence),
        output_type=ProfileProposal,
        schema_name="harvest_profile_revision",
    )
    return proposal.model_copy(update={"profile": enforce_profile_boundaries(proposal.profile)})


def generate_daily(
    pending: PendingDaily,
    config: AppConfig,
    provider: ResponsesProvider,
    active_projects: list[ProjectItem] | None,
    profile: UserProfile | ProfileContent,
    *,
    now: datetime | None = None,
) -> DailyDraft:
    analysis, usage = provider.generate(
        instructions=DAILY_INSTRUCTIONS,
        input_text=daily_input(pending.answers, active_projects, profile),
        output_type=DailyAnalysis,
        schema_name="daily_harvest",
    )
    validate_daily_sections(analysis.report, profile)
    return DailyDraft(
        record=DailyRecord(
            date=pending.date,
            generated_at=now or datetime.now().astimezone(),
            provider=config.provider,
            model=config.model,
            usage=usage,
            report=analysis.report,
        ),
        project_suggestions=analysis.project_suggestions,
    )


def generate_trial_daily(
    pending: PendingDaily,
    config: AppConfig,
    provider: ResponsesProvider,
    profile: ProfileContent,
    *,
    now: datetime | None = None,
) -> tuple[DailyDraft, NetworkTrace]:
    analysis, usage, trace = provider.generate_traced(
        instructions=DAILY_INSTRUCTIONS,
        input_text=daily_input(pending.answers, [], profile),
        output_type=DailyAnalysis,
        schema_name="daily_harvest_test",
    )
    validate_daily_sections(analysis.report, profile)
    return (
        DailyDraft(
            record=DailyRecord(
                date=pending.date,
                generated_at=now or datetime.now().astimezone(),
                provider=config.provider,
                model=config.model,
                usage=usage,
                report=analysis.report,
            ),
            project_suggestions=analysis.project_suggestions,
        ),
        trace,
    )


def revise_daily(
    draft: DailyDraft,
    correction: str,
    config: AppConfig,
    provider: ResponsesProvider,
    active_projects: list[ProjectItem] | None,
    profile: UserProfile | ProfileContent,
    *,
    now: datetime | None = None,
) -> DailyDraft:
    analysis, usage = provider.generate(
        instructions=DAILY_INSTRUCTIONS,
        input_text=correction_input(
            draft.record.report, draft.project_suggestions, correction, active_projects, profile
        ),
        output_type=DailyAnalysis,
        schema_name="daily_harvest_revision",
    )
    validate_daily_sections(analysis.report, profile)
    return DailyDraft(
        record=draft.record.model_copy(
            update={
                "generated_at": now or datetime.now().astimezone(),
                "provider": config.provider,
                "model": config.model,
                "usage": usage,
                "report": analysis.report,
            }
        ),
        project_suggestions=analysis.project_suggestions,
    )


def week_bounds(week: str) -> tuple[date, date]:
    try:
        year_text, week_text = week.split("-W", 1)
        monday = date.fromisocalendar(int(year_text), int(week_text), 1)
    except (ValueError, TypeError) as exc:
        raise ValueError("周格式应为 YYYY-Www，例如 2026-W36") from exc
    return monday, monday + timedelta(days=6)


def week_id(target: date) -> str:
    year, week, _ = target.isocalendar()
    return f"{year}-W{week:02d}"


def latest_review_week(target: date) -> str:
    if target.weekday() == 6:
        return week_id(target)
    previous_sunday = target - timedelta(days=target.weekday() + 1)
    return week_id(previous_sunday)


def generate_weekly(
    week: str,
    records: list[DailyRecord],
    config: AppConfig,
    provider: ResponsesProvider,
    profile: UserProfile,
    *,
    now: datetime | None = None,
) -> WeeklyRecord:
    if not records:
        raise ValueError("该周没有可用于总结的日报")
    start, end = week_bounds(week)
    recorded = sorted(record.date for record in records)
    all_dates = [start + timedelta(days=offset) for offset in range(7)]
    missing = [item for item in all_dates if item not in set(recorded)]
    review, usage = provider.generate(
        instructions=WEEKLY_INSTRUCTIONS,
        input_text=weekly_input(records, [item.isoformat() for item in missing], profile),
        output_type=WeeklyReview,
        schema_name="weekly_review",
    )
    validate_weekly_sections(review, profile)
    return WeeklyRecord(
        week=week,
        period_start=start,
        period_end=end,
        generated_at=now or datetime.now().astimezone(),
        provider=config.provider,
        model=config.model,
        recorded_dates=recorded,
        missing_dates=missing,
        usage=usage,
        review=review,
    )


def revise_weekly(
    record: WeeklyRecord,
    correction: str,
    config: AppConfig,
    provider: ResponsesProvider,
    profile: UserProfile,
    *,
    now: datetime | None = None,
) -> WeeklyRecord:
    payload = "请只按用户意见修订当前周报，未提及部分保持不变：\n" + json.dumps(
        {
            "current_review": record.review.model_dump(mode="json"),
            "user_correction": correction,
            "user_profile": profile.content.model_dump(mode="json"),
        },
        ensure_ascii=False,
        indent=2,
    )
    review, usage = provider.generate(
        instructions=WEEKLY_INSTRUCTIONS,
        input_text=payload,
        output_type=WeeklyReview,
        schema_name="weekly_review_revision",
    )
    validate_weekly_sections(review, profile)
    return record.model_copy(
        update={
            "generated_at": now or datetime.now().astimezone(),
            "provider": config.provider,
            "model": config.model,
            "usage": usage,
            "review": review,
        }
    )
