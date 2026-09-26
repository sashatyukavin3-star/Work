from __future__ import annotations

from pathlib import Path


class UnsafePathError(ValueError):
    pass


def safe_workspace_path(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    """Resolve a model-supplied path and keep it inside the task workspace."""
    if not relative or "\x00" in relative:
        raise UnsafePathError("Path is empty or invalid")
    candidate_input = Path(relative)
    if candidate_input.is_absolute():
        raise UnsafePathError("Absolute paths are not allowed")

    root = root.resolve()
    candidate = root.joinpath(candidate_input).resolve(strict=not allow_missing)
    try:
        workspace_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise UnsafePathError("Path escapes the repository workspace") from exc
    if workspace_relative.parts and workspace_relative.parts[0].lower() == ".git":
        raise UnsafePathError("The repository's .git metadata is not accessible")
    return candidate
