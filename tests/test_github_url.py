import pytest

from repo_agent_bot.github_url import (
    extract_github_repository,
    parse_github_url,
    repository_is_allowed,
)
from repo_agent_bot.models import GitHubRepository


def test_parse_github_url() -> None:
    repository = parse_github_url("https://github.com/Acme/private-app.git")
    assert repository.owner == "Acme"
    assert repository.name == "private-app"
    assert repository.slug == "Acme/private-app"


def test_extract_url_and_request() -> None:
    repository, request = extract_github_repository(
        "https://github.com/acme/mobile-app Добавь авторизацию и тесты"
    )
    assert repository == GitHubRepository("acme", "mobile-app")
    assert request == "Добавь авторизацию и тесты"


def test_extract_ignores_trailing_punctuation() -> None:
    repository, request = extract_github_repository(
        "Проверь https://github.com/acme/mobile-app. Срочно"
    )
    assert repository == GitHubRepository("acme", "mobile-app")
    assert request == "Проверь Срочно"


@pytest.mark.parametrize(
    "value",
    [
        "https://gitlab.com/acme/app",
        "file:///tmp/repo",
        "https://github.com/acme",
        "https://example.com/github.com/acme/app",
    ],
)
def test_rejects_unsupported_url(value: str) -> None:
    with pytest.raises(ValueError):
        parse_github_url(value)


def test_repository_allowlist_supports_owner_and_exact_slug() -> None:
    repository = GitHubRepository("Acme", "App")
    assert repository_is_allowed(repository, ("acme",))
    assert repository_is_allowed(repository, ("acme/app",))
    assert not repository_is_allowed(repository, ("acme/other", "other-owner"))
    assert not repository_is_allowed(repository, ())
