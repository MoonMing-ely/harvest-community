from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

try:
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover - only used by unpackaged development environments
    keyring = None

    class KeyringError(Exception):
        pass

try:
    from platformdirs import user_config_path
except ImportError:  # pragma: no cover
    def user_config_path(appname: str, appauthor=False) -> Path:
        return Path.home() / ".config" / appname


CONFIG_DIR = Path(user_config_path("harvest", appauthor=False))
CONFIG_PATH = CONFIG_DIR / "config.toml"
SECRETS_PATH = CONFIG_DIR / "secrets.env"
REPORT_PROFILE_PATH = CONFIG_DIR / "report-profile.md"
DEFAULT_DATA_DIR = Path.home() / "Documents" / "Harvest"
DEFAULT_REPORT_PROFILE = """# Harvest Report Profile

> 此文件的内容会与每次 Daily Harvest 回答一起发送给当前模型供应商。

## 当前阶段

- 正在建立广泛的软件开发能力，以真实项目积累工程经验，以 C++ 和算法训练问题建模能力。
- 比起记住孤立命令，更重视理解技术为什么存在、位于系统哪一层，以及它和已有知识的关系。
- 绘画是独立而长期的创造主线，不应被简化成生产力指标。

## 日报关注点

- 项目：区分探索、配置、实现、验证和真正交付；没有产出时如实说明注意力去了哪里。
- 算法题：关注理解了什么方法、能否独立重建思路、实现还卡在哪里。
- 技术基础：关注机制、设计理由和知识之间的新连接，不只罗列看过的材料。
- 学习状态：观察连续专注、上下文切换、AI 使用方式与实际理解之间的关系。
- 生活状态：平实记录吃饭、喝水、睡眠、活动和情绪，不诊断、不说教。
- 绘画：关注练习内容、视觉判断、手感变化和作品推进，不以功利结果衡量。

## 表达偏好

- 使用自然、克制、有节奏的中文，先写事实，再写变化或张力。
- 有人文关怀，但不强行积极、不空泛鼓励，也不把暂时没有产出写成失败。
- 允许一天同时包含投入、分心、收获、疲惫和未完成，不急着消除矛盾。
- 避免管理术语、效率评分和过度总结；报告应像可靠的观察记录，而不是绩效评价。
"""


@dataclass(frozen=True)
class AppConfig:
    provider: str = "deepseek"
    deepseek_model: str = "deepseek-v4-flash"
    openai_model: str = "gpt-5.6-luna"
    data_dir: Path = DEFAULT_DATA_DIR
    reminder_time: str = "22:00"
    timezone: str = "Asia/Shanghai"
    current_state_path: Path | None = None

    @property
    def model(self) -> str:
        return self.deepseek_model if self.provider == "deepseek" else self.openai_model

    @property
    def api_key_name(self) -> str:
        return "DEEPSEEK_API_KEY" if self.provider == "deepseek" else "OPENAI_API_KEY"


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    provider = str(raw.get("provider", "deepseek")).lower()
    if provider not in {"deepseek", "openai"}:
        raise ValueError("provider 必须是 deepseek 或 openai")
    return AppConfig(
        provider=provider,
        deepseek_model=str(raw.get("deepseek_model", "deepseek-v4-flash")),
        openai_model=str(raw.get("openai_model", "gpt-5.6-luna")),
        data_dir=Path(str(raw.get("data_dir", DEFAULT_DATA_DIR))).expanduser(),
        reminder_time=str(raw.get("reminder_time", "22:00")),
        timezone=str(raw.get("timezone", "Asia/Shanghai")),
        current_state_path=(
            Path(str(raw["current_state_path"])).expanduser() if raw.get("current_state_path") else None
        ),
    )


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(
        [
            f"provider = {_toml_string(config.provider)}",
            f"deepseek_model = {_toml_string(config.deepseek_model)}",
            f"openai_model = {_toml_string(config.openai_model)}",
            f"data_dir = {_toml_string(str(config.data_dir))}",
            f"reminder_time = {_toml_string(config.reminder_time)}",
            f"timezone = {_toml_string(config.timezone)}",
            *(
                [f"current_state_path = {_toml_string(str(config.current_state_path))}"]
                if config.current_state_path is not None
                else []
            ),
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def save_api_key(name: str, value: str, path: Path | None = None) -> None:
    if name not in {"DEEPSEEK_API_KEY", "OPENAI_API_KEY"}:
        raise ValueError("不支持的 API Key 名称")
    if path is not None:
        existing = _read_secret_file(path)
        existing[name] = value.strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        body = "".join(f"{key}={item}\n" for key, item in sorted(existing.items()))
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)
        return
    if keyring is None:
        raise RuntimeError("系统凭据库不可用；请改用环境变量")
    try:
        keyring.set_password(_keyring_service(), name, value.strip())
    except KeyringError as exc:
        raise RuntimeError("系统凭据库不可用；请改用环境变量") from exc


def _read_secret_file(path: Path = SECRETS_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if re.fullmatch(r"[A-Z0-9_]+", key):
            values[key] = value
    return values


def get_api_key(config: AppConfig, path: Path | None = None) -> str | None:
    return get_api_key_with_source(config, path)[0]


def get_api_key_with_source(config: AppConfig, path: Path | None = None) -> tuple[str | None, str]:
    environment_value = os.environ.get(config.api_key_name)
    if environment_value:
        return environment_value, "environment"
    if path is not None:
        file_value = _read_secret_file(path).get(config.api_key_name)
        return (file_value, "secrets_file") if file_value else (None, "missing")
    if keyring is not None:
        try:
            stored = keyring.get_password(_keyring_service(), config.api_key_name)
        except KeyringError:
            stored = None
        if stored:
            return stored, "system_keyring"
    # One-way compatibility for installations created before cross-platform keyring support.
    legacy = _read_secret_file(SECRETS_PATH).get(config.api_key_name)
    if legacy:
        return legacy, "legacy_secrets_file"
    return None, "missing"


def _keyring_service() -> str:
    """Allow explicit test launchers to isolate credentials from normal Harvest installs."""
    return os.environ.get("HARVEST_KEYRING_SERVICE", "harvest")


def ensure_report_profile(path: Path = REPORT_PROFILE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(DEFAULT_REPORT_PROFILE, encoding="utf-8")
    path.chmod(0o600)
    return path


def load_report_profile(path: Path = REPORT_PROFILE_PATH, *, max_chars: int = 8000) -> str:
    ensure_report_profile(path)
    return path.read_text(encoding="utf-8").strip()[:max_chars]
