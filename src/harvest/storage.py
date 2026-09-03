from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from harvest.models import (
    CalibrationState,
    DailyRecord,
    FeedbackEvent,
    OnboardingPending,
    PendingDaily,
    ProjectMemory,
    UserProfile,
    WeeklyRecord,
)
from harvest.text_safety import sanitize_untrusted_text


T = TypeVar("T", bound=BaseModel)


class Storage:
    def __init__(self, root: Path):
        self.root = root.expanduser()

    def ensure(self) -> None:
        for path in (
            self.root,
            self.root / "daily",
            self.root / "weekly",
            self.root / "pending",
            self.root / "memory",
            self.root / "profile",
            self.root / "profile" / "history",
        ):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        self._migrate_terminal_safe_markdown()

    def daily_json_path(self, target: date) -> Path:
        return self.root / "daily" / f"{target:%Y}" / f"{target:%m}" / f"{target.isoformat()}.json"

    def daily_markdown_path(self, target: date) -> Path:
        return self.daily_json_path(target).with_suffix(".md")

    def pending_path(self, target: date) -> Path:
        return self.root / "pending" / f"{target.isoformat()}.json"

    def weekly_json_path(self, week: str) -> Path:
        year = week.split("-W", 1)[0]
        return self.root / "weekly" / year / f"{week}.json"

    def weekly_markdown_path(self, week: str) -> Path:
        return self.weekly_json_path(week).with_suffix(".md")

    def project_memory_path(self) -> Path:
        return self.root / "memory" / "projects.json"

    def profile_path(self) -> Path:
        return self.root / "profile" / "current.json"

    def profile_history_path(self, version: int) -> Path:
        return self.root / "profile" / "history" / f"v{version:04d}.json"

    def calibration_path(self) -> Path:
        return self.root / "profile" / "calibration.json"

    def onboarding_path(self) -> Path:
        return self.root / "pending" / "onboarding.json"

    def save_pending(self, pending: PendingDaily) -> None:
        self._write_model(self.pending_path(pending.date), pending)

    def load_pending(self, target: date) -> PendingDaily | None:
        return self._load_model(self.pending_path(target), PendingDaily)

    def delete_pending(self, target: date) -> None:
        path = self.pending_path(target)
        if path.exists():
            path.unlink()

    def save_daily(self, record: DailyRecord, markdown: str) -> None:
        self._write_model(self.daily_json_path(record.date), record)
        self._atomic_write(self.daily_markdown_path(record.date), markdown)

    def load_daily(self, target: date) -> DailyRecord | None:
        return self._load_model(self.daily_json_path(target), DailyRecord)

    def save_weekly(self, record: WeeklyRecord, markdown: str) -> None:
        self._write_model(self.weekly_json_path(record.week), record)
        self._atomic_write(self.weekly_markdown_path(record.week), markdown)

    def load_weekly(self, week: str) -> WeeklyRecord | None:
        return self._load_model(self.weekly_json_path(week), WeeklyRecord)

    def load_project_memory(self) -> ProjectMemory:
        return self._load_model(self.project_memory_path(), ProjectMemory) or ProjectMemory()

    def save_project_memory(self, memory: ProjectMemory) -> None:
        self._write_model(self.project_memory_path(), memory)

    def load_profile(self) -> UserProfile | None:
        return self._load_model(self.profile_path(), UserProfile)

    def save_profile(self, profile: UserProfile) -> None:
        history = self.profile_history_path(profile.version)
        if history.exists():
            raise ValueError(f"画像版本已存在：v{profile.version}")
        self._write_model(history, profile)
        self._write_model(self.profile_path(), profile)

    def profile_versions(self) -> list[UserProfile]:
        return [
            UserProfile.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "profile" / "history").glob("v*.json"))
        ]

    def load_profile_version(self, version: int) -> UserProfile | None:
        return self._load_model(self.profile_history_path(version), UserProfile)

    def load_calibration(self) -> CalibrationState:
        return self._load_model(self.calibration_path(), CalibrationState) or CalibrationState()

    def save_calibration(self, state: CalibrationState) -> None:
        self._write_model(self.calibration_path(), state)

    def add_feedback(self, event: FeedbackEvent) -> None:
        state = self.load_calibration()
        events = [*state.feedback_events, event][-100:]
        self.save_calibration(state.model_copy(update={"feedback_events": events}))

    def save_onboarding(self, pending: OnboardingPending) -> None:
        self._write_model(self.onboarding_path(), pending)

    def load_onboarding(self) -> OnboardingPending | None:
        return self._load_model(self.onboarding_path(), OnboardingPending)

    def delete_onboarding(self) -> None:
        path = self.onboarding_path()
        if path.exists():
            path.unlink()

    def daily_records(self, start: date, end: date) -> list[DailyRecord]:
        records: list[DailyRecord] = []
        current = start
        while current <= end:
            record = self.load_daily(current)
            if record is not None:
                records.append(record)
            current = date.fromordinal(current.toordinal() + 1)
        return records

    def all_daily_records(self) -> list[DailyRecord]:
        records: list[DailyRecord] = []
        for path in sorted((self.root / "daily").glob("*/*/*.json")):
            records.append(DailyRecord.model_validate_json(path.read_text(encoding="utf-8")))
        return records

    def _write_model(self, path: Path, model: BaseModel) -> None:
        validated = type(model).model_validate(model.model_dump(mode="python"))
        body = json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self._atomic_write(path, body)

    def _migrate_terminal_safe_markdown(self) -> None:
        state = self.load_calibration()
        if state.terminal_safety_version >= 1:
            return
        for pattern in ("daily/*/*/*.md", "weekly/*/*.md"):
            for path in self.root.glob(pattern):
                original = path.read_text(encoding="utf-8")
                safe = sanitize_untrusted_text(original)
                if safe != original:
                    self._atomic_write(path, safe)
        self.save_calibration(state.model_copy(update={"terminal_safety_version": 1}))

    def _load_model(self, path: Path, model_type: type[T]) -> T | None:
        if not path.exists():
            return None
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(0o700)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
