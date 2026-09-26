from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def clone_url(self) -> str:
        return f"https://github.com/{self.slug}.git"

    @property
    def web_url(self) -> str:
        return f"https://github.com/{self.slug}"


@dataclass(slots=True)
class AgentResult:
    summary: str
    tests: str = ""
    artifacts: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PublicationResult:
    branch: str | None = None
    commit_sha: str | None = None
    pull_request_url: str | None = None
    patch_path: Path | None = None


@dataclass(slots=True)
class TaskRecord:
    id: str
    chat_id: int
    user_id: int
    repository: str
    prompt: str
    status: TaskStatus
    created_at: str
    updated_at: str
    summary: str | None = None
    error: str | None = None
    branch: str | None = None
    pull_request_url: str | None = None
