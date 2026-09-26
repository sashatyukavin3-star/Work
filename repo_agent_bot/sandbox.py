from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from .process import ProcessResult, run_process


class SandboxError(RuntimeError):
    pass


class CommandSandbox:
    def __init__(
        self,
        *,
        mode: str,
        workspace: Path,
        mount_workspace: Path | None = None,
        image: str,
        memory: str,
        cpus: str,
        network: str,
        command_timeout: int,
    ) -> None:
        self.mode = mode
        self.workspace = workspace.resolve()
        # A containerized orchestrator must give Docker the equivalent path on the host.
        self.mount_workspace = (mount_workspace or workspace).resolve()
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.network = network
        self.command_timeout = command_timeout
        self.container_name = f"repo-agent-{uuid.uuid4().hex[:12]}"
        self._started = False

    async def __aenter__(self) -> CommandSandbox:
        if self.mode == "local":
            self._started = True
            return self
        if not shutil.which("docker"):
            raise SandboxError(
                "Docker is not installed. Install Docker or explicitly set SANDBOX_MODE=local "
                "only for trusted repositories."
            )
        check = await run_process(["docker", "info"], timeout_seconds=30)
        if check.returncode != 0:
            raise SandboxError(f"Docker is unavailable: {check.stdout}")
        uid_gid = f"{os.getuid()}:{os.getgid()}"
        result = await run_process(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                self.container_name,
                "--workdir",
                "/workspace",
                "--volume",
                f"{self.mount_workspace}:/workspace",
                # Prevent commands in the worker from altering host-side Git config or hooks.
                "--volume",
                f"{self.mount_workspace / '.git'}:/workspace/.git:ro",
                "--memory",
                self.memory,
                "--cpus",
                self.cpus,
                "--pids-limit",
                "512",
                "--cap-drop",
                "ALL",
                "--network",
                self.network,
                "--security-opt",
                "no-new-privileges:true",
                "--user",
                uid_gid,
                "--entrypoint",
                "/bin/sh",
                self.image,
                "-c",
                "while :; do sleep 3600; done",
            ],
            timeout_seconds=max(300, self.command_timeout),
        )
        if result.returncode != 0:
            raise SandboxError(f"Could not start sandbox image {self.image}: {result.stdout}")
        self._started = True
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.mode == "docker" and self._started:
            await run_process(
                ["docker", "rm", "--force", self.container_name], timeout_seconds=30, check=False
            )
        self._started = False

    async def run(self, command: str, timeout_seconds: int | None = None) -> ProcessResult:
        if not self._started:
            raise SandboxError("Sandbox has not been started")
        timeout_seconds = min(timeout_seconds or self.command_timeout, self.command_timeout)
        if self.mode == "local":
            # Never expose Telegram, GitHub, or AI credentials to model-generated commands.
            agent_home = self.workspace.parent / ".agent-home"
            agent_home.mkdir(parents=True, exist_ok=True)
            safe_environment = {
                "HOME": str(agent_home),
                "LANG": os.getenv("LANG", "C.UTF-8"),
                "PATH": os.getenv("PATH", os.defpath),
            }
            return await run_process(
                ["/bin/sh", "-lc", command],
                cwd=self.workspace,
                env=safe_environment,
                timeout_seconds=timeout_seconds,
                inherit_env=False,
            )
        return await run_process(
            ["docker", "exec", self.container_name, "/bin/sh", "-lc", command],
            timeout_seconds=timeout_seconds,
        )
