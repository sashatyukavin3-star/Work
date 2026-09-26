from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import GitHubRepository

_GITHUB_TEXT_URL = re.compile(
    r"(?P<url>https?://(?:www\.)?github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?)",
    re.IGNORECASE,
)
_VALID_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def extract_github_repository(text: str) -> tuple[GitHubRepository | None, str]:
    """Return a repository and the message text left after its first GitHub URL."""
    match = _GITHUB_TEXT_URL.search(text)
    if not match:
        return None, text.strip()
    raw_url = match.group("url")
    clean_url = raw_url.rstrip(".,;:!?)]}")
    repository = parse_github_url(clean_url)
    # Punctuation trimmed from the URL is intentionally discarded.
    remaining = f"{text[: match.start()]} {text[match.end() :]}".strip()
    return repository, " ".join(remaining.split())


def parse_github_url(value: str) -> GitHubRepository:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "github.com",
        "www.github.com",
    }:
        raise ValueError("Only https://github.com/owner/repository links are supported")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("GitHub URL must contain an owner and repository")
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name or not _VALID_PART.fullmatch(owner) or not _VALID_PART.fullmatch(name):
        raise ValueError("Invalid GitHub owner or repository name")
    return GitHubRepository(owner=owner, name=name)


def repository_is_allowed(repository: GitHubRepository, allowlist: tuple[str, ...]) -> bool:
    """An entry can be an owner or an exact owner/repository slug."""
    slug = repository.slug.lower()
    owner = repository.owner.lower()
    return any(entry == owner or entry == slug for entry in allowlist)
