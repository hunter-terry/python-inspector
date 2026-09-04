"""Tests for public-GitHub-only retrieval: URL validation, cancellation, and
a real (network-dependent, gracefully skipped if unavailable) clone of a
tiny, stable public repository to prove retrieval + cleanup actually work
end to end.
"""
from __future__ import annotations

import socket
import subprocess

import pytest

from inspector_app.backend import github_source
from inspector_app.backend.fs_util import safe_rmtree

TINY_PUBLIC_REPO = "https://github.com/octocat/Hello-World"


def _network_available() -> bool:
    try:
        socket.create_connection(("github.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/owner/repo",
        "https://github.com/owner/repo.git",
        "https://github.com/owner/repo/",
    ],
)
def test_valid_public_github_urls_accepted(url):
    ok, normalized = github_source.validate_github_url(url)
    assert ok
    assert normalized == "https://github.com/owner/repo.git"


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://gitlab.com/owner/repo",
        "http://github.com/owner/repo",  # not https
        "https://github.com/owner",  # missing repo
        "ssh://git@github.com/owner/repo.git",
        "https://user:password@github.com/owner/repo",
        "https://github.com/owner/repo/extra/path",
    ],
)
def test_invalid_or_unsupported_urls_rejected_clearly(url):
    ok, message = github_source.validate_github_url(url)
    assert not ok
    assert message  # a real, human-readable reason, not a blank string


def test_clone_of_invalid_url_fails_without_touching_filesystem(tmp_path):
    dest = tmp_path / "clone"
    outcome = github_source.clone_repository("https://gitlab.com/owner/repo", dest, is_cancelled=lambda: False)
    assert not outcome.ok
    assert not outcome.cancelled
    assert not dest.exists() or not any(dest.iterdir())


def test_cancelling_a_clone_terminates_it_and_cleans_up(tmp_path, monkeypatch):
    dest = tmp_path / "clone"

    class FakeProcess:
        def __init__(self):
            self.terminated = False
            self.killed = False

        def poll(self):
            return None  # never finishes on its own

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.killed = True

        def communicate(self):
            return "", ""

    fake = FakeProcess()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake)

    outcome = github_source.clone_repository(TINY_PUBLIC_REPO, dest, is_cancelled=lambda: True)
    assert outcome.cancelled
    assert not outcome.ok
    assert fake.terminated
    assert not dest.exists()


def test_clone_never_passes_shell_true(tmp_path, monkeypatch):
    captured = {}

    class FakeProcess:
        def poll(self):
            return 0

        def communicate(self):
            return "", ""

        returncode = 0

    def fake_popen(args, cwd=None, env=None, shell=False, **kwargs):
        captured["shell"] = shell
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    github_source.clone_repository(TINY_PUBLIC_REPO, tmp_path / "unused", is_cancelled=lambda: False)
    assert captured["shell"] is False
    assert isinstance(captured["args"], list)


@pytest.mark.skipif(not _network_available(), reason="no network access to github.com in this environment")
def test_live_clone_of_tiny_public_repo_and_cleanup(tmp_path):
    dest = tmp_path / "hello-world"
    outcome = github_source.clone_repository(TINY_PUBLIC_REPO, dest, is_cancelled=lambda: False)
    assert outcome.ok, outcome.error
    assert dest.is_dir()
    assert any(dest.iterdir())

    # Simulate "session end" cleanup.
    safe_rmtree(dest)
    assert not dest.exists()


@pytest.mark.skipif(not _network_available(), reason="no network access to github.com in this environment")
def test_live_clone_of_nonexistent_repo_fails_clearly(tmp_path):
    dest = tmp_path / "does-not-exist"
    outcome = github_source.clone_repository(
        "https://github.com/octocat/this-repo-should-not-exist-python-inspector-test",
        dest,
        is_cancelled=lambda: False,
    )
    assert not outcome.ok
    assert not outcome.cancelled
    assert outcome.error
    assert not dest.exists()
