from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv_ints(value: str) -> frozenset[int]:
    if not value.strip():
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("TELEGRAM_ALLOWED_USERS must contain numeric user IDs") from exc


def _csv_strings(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def _bool(value: str, *, default: bool = False) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_users: frozenset[int]
    ai_api_key: str
    ai_base_url: str
    ai_model: str
    ai_max_steps: int
    github_token: str
    github_repository_allowlist: tuple[str, ...]
    github_create_pr: bool
    data_dir: Path
    max_concurrent_tasks: int
    task_timeout_seconds: int
    command_timeout_seconds: int
    max_telegram_artifact_mb: int
    sandbox_mode: str
    sandbox_image: str
    sandbox_host_data_dir: Path | None
    sandbox_memory: str
    sandbox_cpus: str
    sandbox_network: str
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_dir / "bot.sqlite3"

    @property
    def workspaces_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @classmethod
    def from_env(cls) -> Settings:
        sandbox_mode = os.getenv("SANDBOX_MODE", "docker").strip().lower()
        if sandbox_mode not in {"docker", "local"}:
            raise ValueError("SANDBOX_MODE must be either 'docker' or 'local'")

        settings = cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_allowed_users=_csv_ints(os.getenv("TELEGRAM_ALLOWED_USERS", "")),
            ai_api_key=os.getenv("AI_API_KEY", "").strip(),
            ai_base_url=os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            ai_model=os.getenv("AI_MODEL", "gpt-4.1").strip(),
            ai_max_steps=_positive_int("AI_MAX_STEPS", 30),
            github_token=os.getenv("GITHUB_TOKEN", "").strip(),
            github_repository_allowlist=_csv_strings(os.getenv("GITHUB_REPOSITORY_ALLOWLIST", "")),
            github_create_pr=_bool(os.getenv("GITHUB_CREATE_PR", "true"), default=True),
            data_dir=Path(os.getenv("DATA_DIR", "./data")).expanduser().resolve(),
            max_concurrent_tasks=_positive_int("MAX_CONCURRENT_TASKS", 1),
            task_timeout_seconds=_positive_int("TASK_TIMEOUT_SECONDS", 3600),
            command_timeout_seconds=_positive_int("COMMAND_TIMEOUT_SECONDS", 600),
            max_telegram_artifact_mb=_positive_int("MAX_TELEGRAM_ARTIFACT_MB", 45),
            sandbox_mode=sandbox_mode,
            sandbox_image=os.getenv("SANDBOX_IMAGE", "ghcr.io/cirruslabs/flutter:stable").strip(),
            sandbox_host_data_dir=(
                Path(os.environ["SANDBOX_HOST_DATA_DIR"]).expanduser().resolve()
                if os.getenv("SANDBOX_HOST_DATA_DIR", "").strip()
                else None
            ),
            sandbox_memory=os.getenv("SANDBOX_MEMORY", "4g").strip(),
            sandbox_cpus=os.getenv("SANDBOX_CPUS", "2").strip(),
            sandbox_network=os.getenv("SANDBOX_NETWORK", "none").strip(),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
        if not settings.telegram_bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        if not settings.ai_model:
            raise ValueError("AI_MODEL is required")
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.workspaces_dir.mkdir(parents=True, exist_ok=True)
        return settings
