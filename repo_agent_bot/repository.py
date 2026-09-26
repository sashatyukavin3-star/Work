from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import httpx

from .models import AgentResult, GitHubRepository, PublicationResult
from .process import ProcessResult, run_process

_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")
_MAX_COMMIT_FILE_BYTES = 10 * 1024 * 1024


class RepositoryClient:
    def __init__(self, github_token: str, command_timeout: int = 600) -> None:
        self.github_token = github_token
        self.command_timeout = command_timeout

    @staticmethod
    def _base_environment() -> dict[str, str]:
        return {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": tempfile.gettempdir(),
            "LANG": os.getenv("LANG", "C.UTF-8"),
            "PATH": os.getenv("PATH", os.defpath),
        }

    def _auth_environment(self) -> tuple[dict[str, str], tempfile.TemporaryDirectory[str]]:
        directory = tempfile.TemporaryDirectory(prefix="repo-agent-auth-")
        script = Path(directory.name) / "askpass.sh"
        script.write_text(
            "#!/bin/sh\n"
            'case "$1" in\n'
            "  *Username*) printf '%s\\n' 'x-access-token' ;;\n"
            "  *) printf '%s\\n' \"$REPO_AGENT_GITHUB_TOKEN\" ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        script.chmod(0o700)
        environment = self._base_environment()
        environment.update(
            {
                "GIT_ASKPASS": str(script),
                "REPO_AGENT_GITHUB_TOKEN": self.github_token,
            }
        )
        return environment, directory

    async def _git(
        self,
        root: Path,
        *args: str,
        auth: bool = False,
        check: bool = True,
    ) -> ProcessResult:
        env = self._base_environment()
        auth_directory: tempfile.TemporaryDirectory[str] | None = None
        if auth and self.github_token:
            env, auth_directory = self._auth_environment()
        try:
            return await run_process(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "credential.helper=",
                    *args,
                ],
                cwd=root,
                env=env,
                timeout_seconds=self.command_timeout,
                check=check,
                inherit_env=False,
            )
        finally:
            if auth_directory:
                auth_directory.cleanup()

    async def clone(self, repository: GitHubRepository, destination: Path) -> str:
        destination.parent.mkdir(parents=True, exist_ok=True)
        env = self._base_environment()
        auth_directory: tempfile.TemporaryDirectory[str] | None = None
        if self.github_token:
            env, auth_directory = self._auth_environment()
        try:
            await run_process(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "credential.helper=",
                    "clone",
                    "--no-tags",
                    repository.clone_url,
                    str(destination),
                ],
                cwd=destination.parent,
                env=env,
                timeout_seconds=self.command_timeout,
                check=True,
                inherit_env=False,
            )
        finally:
            if auth_directory:
                auth_directory.cleanup()

        result = await self._git(
            destination,
            "symbolic-ref",
            "--short",
            "refs/remotes/origin/HEAD",
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip().startswith("origin/"):
            return result.stdout.strip().removeprefix("origin/")
        return (await self._git(destination, "branch", "--show-current")).stdout.strip()

    async def create_work_branch(self, root: Path, task_id: str) -> str:
        suffix = _BRANCH_SAFE.sub("-", task_id.lower()).strip("-")[:32]
        branch = f"agent/telegram-{suffix}"
        await self._git(root, "checkout", "-b", branch)
        return branch

    async def _validate_origin(self, root: Path, repository: GitHubRepository) -> None:
        origin = (await self._git(root, "remote", "get-url", "origin")).stdout.strip()
        accepted = {repository.clone_url, repository.web_url}
        if origin not in accepted:
            raise RuntimeError(
                "Repository origin changed during the agent run; refusing to publish"
            )

    async def changed_files(self, root: Path) -> list[str]:
        result = await self._git(root, "status", "--porcelain=v1", "-z")
        values = result.stdout.split("\x00")
        files: list[str] = []
        for value in values:
            if not value:
                continue
            path = value[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            files.append(path)
        return files

    async def _unstage_large_files(self, root: Path) -> list[str]:
        result = await self._git(root, "diff", "--cached", "--name-only", "-z")
        removed: list[str] = []
        for relative in result.stdout.split("\x00"):
            if not relative:
                continue
            path = root / relative
            if path.is_file() and path.stat().st_size > _MAX_COMMIT_FILE_BYTES:
                await self._git(root, "reset", "--", relative)
                removed.append(relative)
        return removed

    async def publish(
        self,
        root: Path,
        repository: GitHubRepository,
        base_branch: str,
        branch: str,
        task_id: str,
        prompt: str,
        result: AgentResult,
        *,
        create_pr: bool,
    ) -> PublicationResult:
        await self._validate_origin(root, repository)
        changed = await self.changed_files(root)
        if not changed:
            return PublicationResult()

        await self._git(root, "add", "-A")
        skipped = await self._unstage_large_files(root)
        staged = await self._git(root, "diff", "--cached", "--name-only")
        if not staged.stdout.strip():
            return PublicationResult()

        await self._git(root, "config", "user.name", "Repo Agent Bot")
        await self._git(root, "config", "user.email", "repo-agent-bot@users.noreply.github.com")
        title = " ".join(prompt.strip().split())[:72] or f"Agent task {task_id[:8]}"
        await self._git(root, "commit", "-m", f"agent: {title}")
        sha = (await self._git(root, "rev-parse", "HEAD")).stdout.strip()

        patch_path = root.parent / f"{task_id}.patch"
        patch_result = await self._git(root, "format-patch", "-1", "-o", str(root.parent))
        generated_patch = Path(patch_result.stdout.strip().splitlines()[-1])
        if not generated_patch.is_absolute():
            generated_patch = root / generated_patch
        generated_patch.replace(patch_path)

        publication = PublicationResult(branch=branch, commit_sha=sha, patch_path=patch_path)
        if not self.github_token:
            return publication

        await self._git(root, "push", "--set-upstream", "origin", branch, auth=True)
        if create_pr:
            publication.pull_request_url = await self._create_pull_request(
                repository=repository,
                base=base_branch,
                head=branch,
                title=title,
                body=self._pull_request_body(task_id, prompt, result, skipped),
            )
        return publication

    async def _create_pull_request(
        self,
        *,
        repository: GitHubRepository,
        base: str,
        head: str,
        title: str,
        body: str,
    ) -> str:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"https://api.github.com/repos/{repository.slug}/pulls",
                headers=headers,
                json={"title": title, "head": head, "base": base, "body": body},
            )
        if response.status_code == 422:
            # A retry after a network interruption may find the already-created PR.
            async with httpx.AsyncClient(timeout=30) as client:
                lookup = await client.get(
                    f"https://api.github.com/repos/{repository.slug}/pulls",
                    headers=headers,
                    params={"head": f"{repository.owner}:{head}", "state": "open"},
                )
            lookup.raise_for_status()
            pulls = lookup.json()
            if pulls:
                return str(pulls[0]["html_url"])
        response.raise_for_status()
        return str(response.json()["html_url"])

    @staticmethod
    def _pull_request_body(
        task_id: str,
        prompt: str,
        result: AgentResult,
        skipped: list[str],
    ) -> str:
        skipped_text = ""
        if skipped:
            skipped_text = "\n\n### Not committed (over 10 MB)\n" + "\n".join(
                f"- `{path}`" for path in skipped
            )
        return (
            "## Telegram coding-agent task\n\n"
            f"**Task ID:** `{task_id}`\n\n"
            f"### Request\n{prompt}\n\n"
            f"### Result\n{result.summary}\n\n"
            f"### Checks\n{result.tests or 'Not reported'}"
            f"{skipped_text}\n\n"
            "_Generated by Repo Agent Bot._"
        )
