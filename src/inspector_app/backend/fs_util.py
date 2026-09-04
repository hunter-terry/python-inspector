"""Shared filesystem helpers: which directories to skip when walking a
scanned project (never the project's own .git history, virtualenvs, or
caches), used by both the scanners and the test-suite detector; and a
cleanup helper that tolerates git's read-only object files on Windows.
"""
from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

IGNORED_DIR_NAMES = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "site-packages",
    ".idea", ".vscode",
}


def is_ignored(path: Path, project_dir: Path) -> bool:
    try:
        rel_parts = path.resolve().relative_to(project_dir.resolve()).parts
    except ValueError:
        return True
    return any(part in IGNORED_DIR_NAMES for part in rel_parts)


def has_pytest_suite(project_dir: Path) -> bool:
    """Best-effort, read-only detection of a discoverable pytest suite."""
    for pattern in ("test_*.py", "*_test.py"):
        for match in project_dir.rglob(pattern):
            if match.is_file() and not is_ignored(match, project_dir):
                return True
    return False


def safe_rmtree(path: Path) -> None:
    """shutil.rmtree that tolerates git's read-only object files on Windows.

    A plain `shutil.rmtree(path, ignore_errors=True)` silently leaves a
    cloned repository's `.git/objects/**` files behind on Windows (they are
    created read-only), which would defeat "temporary GitHub contents are
    removed" without ever raising. This retries each failure once after
    clearing the read-only bit, and only then gives up on that one entry.
    """
    if not path.exists():
        return

    def _on_error(func, target_path, _exc_info):
        try:
            os.chmod(target_path, stat.S_IWRITE)
            func(target_path)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_on_error, ignore_errors=False)
