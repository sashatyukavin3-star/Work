from pathlib import Path

import pytest

from repo_agent_bot.security import UnsafePathError, safe_workspace_path


def test_safe_workspace_path_accepts_child(tmp_path: Path) -> None:
    path = safe_workspace_path(tmp_path, "src/main.py")
    assert path == tmp_path / "src" / "main.py"


@pytest.mark.parametrize(
    "value",
    ["../secret", "/etc/passwd", "a/../../secret", "", ".git/config", "src/../.git/HEAD"],
)
def test_safe_workspace_path_rejects_escape(tmp_path: Path, value: str) -> None:
    with pytest.raises(UnsafePathError):
        safe_workspace_path(tmp_path, value)


def test_safe_workspace_path_rejects_outside_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-for-repo-agent-test"
    outside.mkdir(exist_ok=True)
    link = tmp_path / "linked"
    link.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(UnsafePathError):
            safe_workspace_path(tmp_path, "linked/file.txt")
    finally:
        link.unlink(missing_ok=True)
        outside.rmdir()
