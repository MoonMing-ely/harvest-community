from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ThemeDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,31}$")
    title: str = Field(min_length=1, max_length=20)
    description: str = Field(min_length=1, max_length=240)
    attention_signals: list[str] = Field(default_factory=list, max_length=5)
    exclusions: list[str] = Field(default_factory=list, max_length=3)


class TentativeObservation(StrictModel):
    statement: str = Field(min_length=1, max_length=180)
    evidence: str = Field(min_length=1, max_length=240)
    confidence: Literal["low", "medium"] = "low"


class ProfileContent(StrictModel):
    current_context: str = Field(min_length=1, max_length=600)
    review_purposes: list[str] = Field(min_length=1, max_length=3)
    themes: list[ThemeDefinition] = Field(min_length=3, max_length=7)
    attention_preferences: list[str] = Field(default_factory=list, max_length=5)
    tentative_observations: list[TentativeObservation] = Field(default_factory=list, max_length=4)
    expression_preferences: list[str] = Field(default_factory=list, max_length=5)
    action_preferences: list[str] = Field(default_factory=list, max_length=4)
    interpretation_boundaries: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique_themes(self) -> "ProfileContent":
        ids = [theme.id for theme in self.themes]
        titles = [theme.title.casefold() for theme in self.themes]
        if len(ids) != len(set(ids)):
            raise ValueError("画像主线 ID 不能重复")
        if len(titles) != len(set(titles)):
            raise ValueError("画像主线标题不能重复")
        return self


class UserProfile(StrictModel):
    schema_version: int = 1
    version: int = Field(ge=1)
    stage: Literal["initial", "revised", "five_report", "manual", "restored"]
    created_at: datetime
    updated_at: datetime
    content: ProfileContent


class ProfileProposal(StrictModel):
    profile: ProfileContent
    rationale: list[str] = Field(default_factory=list, max_length=6)


class ReportSection(StrictModel):
    theme_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=20)
    narrative: str | None = Field(default=None, max_length=320)
    progress: list[str] = Field(default_factory=list, max_length=3)
    next_step: str | None = None


class Tomorrow(StrictModel):
    suggestions: list[str] = Field(default_factory=list, max_length=2)
    core_target: str | None = None


LEGACY_THEMES: tuple[tuple[str, str], ...] = (
    ("projects", "项目"),
    ("algorithms", "算法题"),
    ("technical_foundations", "技术基础"),
    ("learning_state", "学习状态"),
    ("life_state", "生活状态"),
    ("drawing", "绘画"),
)


class DailyHarvest(StrictModel):
    overview: str = Field(min_length=1, max_length=320)
    sections: list[ReportSection] = Field(min_length=3, max_length=7)
    tomorrow: Tomorrow

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_sections(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "sections" in value:
            return value
        if not any(key in value for key, _ in LEGACY_THEMES):
            return value
        migrated = dict(value)
        migrated["sections"] = [
            {"theme_id": key, "title": title, **(migrated.pop(key, {}) or {})}
            for key, title in LEGACY_THEMES
        ]
        return migrated

    def progress_items(self) -> list[str]:
        return [item for section in self.sections for item in section.progress]

    def section(self, theme_id: str) -> ReportSection | None:
        return next((item for item in self.sections if item.theme_id == theme_id), None)


class ProjectSuggestion(StrictModel):
    action: Literal["add", "update", "pause", "complete"]
    project_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    next_step: str | None = None


class DailyAnalysis(StrictModel):
    report: DailyHarvest
    project_suggestions: list[ProjectSuggestion] = Field(default_factory=list, max_length=2)


class Usage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class DailyRecord(StrictModel):
    schema_version: int = 3
    date: date
    generated_at: datetime
    provider: str
    model: str
    usage: Usage
    report: DailyHarvest

    @model_validator(mode="before")
    @classmethod
    def upgrade_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("schema_version", 2) < 3:
            return {**value, "schema_version": 3}
        return value


class WeeklyThemeSummary(StrictModel):
    theme_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=20)
    summary: str = Field(min_length=1)


class WeeklyReview(StrictModel):
    summary: str
    sections: list[WeeklyThemeSummary] = Field(min_length=3, max_length=7)
    persistent_items: list[str]
    recommendations: list[str] = Field(max_length=2)
    core_direction: str | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_sections(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "sections" in value:
            return value
        if not any(key in value for key, _ in LEGACY_THEMES):
            return value
        migrated = dict(value)
        migrated["sections"] = [
            {"theme_id": key, "title": title, "summary": migrated.pop(key, "证据不足。")}
            for key, title in LEGACY_THEMES
        ]
        return migrated


class WeeklyRecord(StrictModel):
    schema_version: int = 3
    week: str
    period_start: date
    period_end: date
    generated_at: datetime
    provider: str
    model: str
    recorded_dates: list[date]
    missing_dates: list[date]
    usage: Usage
    review: WeeklyReview

    @model_validator(mode="before")
    @classmethod
    def upgrade_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("schema_version", 2) < 3:
            return {**value, "schema_version": 3}
        return value


class PendingDaily(StrictModel):
    schema_version: int = 1
    date: date
    created_at: datetime
    answers: dict[str, str]
    last_error: str | None = None


class OnboardingPending(StrictModel):
    schema_version: int = 1
    date: date
    created_at: datetime
    questionnaire: dict[str, str] = Field(default_factory=dict)
    daily_answers: dict[str, str] = Field(default_factory=dict)
    proposed_profile: ProfileContent | None = None
    sample_record: DailyRecord | None = None
    sample_project_suggestions: list[ProjectSuggestion] = Field(default_factory=list, max_length=2)
    revision_round: int = Field(default=0, ge=0, le=3)
    feedback: list[str] = Field(default_factory=list, max_length=3)
    last_error: str | None = None


class FeedbackEvent(StrictModel):
    date: date
    kind: Literal["daily_revision", "profile_feedback"]
    text: str = Field(min_length=1, max_length=2000)


class CalibrationState(StrictModel):
    schema_version: int = 1
    onboarding_completed: bool = False
    first_daily_date: date | None = None
    five_report_status: Literal["pending", "completed", "dismissed"] = "pending"
    feedback_events: list[FeedbackEvent] = Field(default_factory=list, max_length=100)


class ProjectItem(StrictModel):
    name: str = Field(min_length=1)
    status: Literal["active", "paused", "completed"]
    last_seen: date
    next_step: str | None = None


class ProjectMemory(StrictModel):
    schema_version: int = 1
    projects: list[ProjectItem] = Field(default_factory=list)


class ContextSnapshot(StrictModel):
    active_projects: list[ProjectItem]
    recent_progress: list[str]
    last_core_target: str | None
    current_state_hints: list[str]
