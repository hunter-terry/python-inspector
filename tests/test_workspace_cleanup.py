"""Regression tests for RealBackend's temp workspace-root cleanup
(commit ef9828f: retry-with-backoff around safe_rmtree).

QA originally reported an empty leftover python-inspector-<sessionid> temp
folder surviving a normal completed run. The mechanism believed responsible:
a transient file-lock race (e.g. antivirus scanning a freshly-cloned repo,
or a lingering git handle) that clears within a few hundred milliseconds --
long enough to fail a single bare removal attempt, short enough that a
short retry-with-backoff recovers.

These tests populate the workspace root with real content (a nested
directory tree, matching what a GitHub clone actually leaves behind) and
inject a fault that mimics that transient lock, instead of only proving an
already-empty directory can be removed (which was never broken).
"""
from __future__ import annotations

import time
from pathlib import Path

from inspector_app.backend import real_backend as real_backend_module
from inspector_app.backend.real_backend import RealBackend


def _populate(root: Path) -> None:
    """Layout resembling a real GitHub clone: nested dirs and files, not
    just an empty directory."""
    clone_dir = root / "clone-abc123def456"
    clone_dir.mkdir()
    (clone_dir / "src").mkdir()
    (clone_dir / "src" / "main.py").write_text("print('hello')\n")
    git_objects = clone_dir / ".git" / "objects"
    git_objects.mkdir(parents=True)
    (git_objects / "pack.idx").write_bytes(b"\x00\x01\x02")


def test_workspace_root_is_cleaned_up_on_end_session():
    backend = RealBackend()
    workspace_root = backend._workspace_root
    _populate(workspace_root)
    assert workspace_root.exists()
    assert any(workspace_root.rglob("*"))
    backend.end_session()
    assert not workspace_root.exists()


def test_cleanup_survives_a_transient_lock_via_retry(monkeypatch):
    """Reproduces the original bug: safe_rmtree fails on the first two
    attempts (simulating a transient lock that hasn't cleared yet) and
    succeeds on the third. A single bare attempt -- the pre-ef9828f
    behavior -- would have left the populated root behind; the current
    retry-with-backoff loop in _cleanup_workspace_root must not.
    """
    backend = RealBackend()
    workspace_root = backend._workspace_root
    _populate(workspace_root)

    real_safe_rmtree = real_backend_module.safe_rmtree
    calls = {"count": 0}

    def flaky_safe_rmtree(path):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(f"simulated transient lock, attempt {calls['count']}")
        real_safe_rmtree(path)

    monkeypatch.setattr(real_backend_module, "safe_rmtree", flaky_safe_rmtree)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    backend.end_session()

    assert not workspace_root.exists()
    assert calls["count"] == 3


def test_cleanup_gives_up_without_crashing_if_the_lock_never_clears(monkeypatch):
    """Boundary case: if the lock never clears (a genuinely stuck handle,
    not a transient one), cleanup must exhaust its retries and return
    quietly -- never raise out of end_session() and never hang the caller.
    """
    backend = RealBackend()
    workspace_root = backend._workspace_root
    _populate(workspace_root)

    calls = {"count": 0}

    def always_fails(path):
        calls["count"] += 1
        raise PermissionError("simulated permanently held lock")

    monkeypatch.setattr(real_backend_module, "safe_rmtree", always_fails)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    backend.end_session()  # must not raise

    assert workspace_root.exists()
    assert calls["count"] == 4  # 3 attempts in the retry loop + 1 final attempt
