from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProcessResult:
    returncode: int
    stdout: str


def _trim_output(value: str, limit: int = 60_000) -> str:
    if len(value) <= limit:
        return value
    half = limit // 2
    return f"{value[:half]}\n\n... output truncated ...\n\n{value[-half:]}"


async def run_process(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 600,
    check: bool = False,
    inherit_env: bool = True,
) -> ProcessResult:
    process_env = os.environ.copy() if inherit_env else {}
    if env:
        process_env.update(env)
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=process_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except (TimeoutError, asyncio.CancelledError) as exc:
        try:
            os.killpg(process.pid, 15)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            try:
                os.killpg(process.pid, 9)
            except ProcessLookupError:
                pass
            await process.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise TimeoutError(
            f"Command timed out after {timeout_seconds} seconds: {args[0]}"
        ) from None

    output = _trim_output(stdout.decode("utf-8", errors="replace"))
    result = ProcessResult(returncode=process.returncode or 0, stdout=output)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(args)}\n{output}")
    return result
