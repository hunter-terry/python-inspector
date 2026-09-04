"""Tests for the approval-gated runtime executor's isolation layer.

Docker is not reliably available in every environment this test suite runs
in, so the safety-critical logic (refuse when isolation can't be proven,
never shell=True, timeout enforcement) is tested with the `docker` CLI
mocked out. A real, live container run is exercised only when Docker is
actually reachable right now, and is skipped (not silently passed) otherwise.
"""
from __future__ import annotations

import subprocess

import pytest

from inspector_app.backend import sandbox
from inspector_app.backend.subprocess_utils import ToolResult


def _docker_actually_available() -> bool:
    return sandbox.check_isolation_available()[0]


def test_refuses_when_docker_is_not_on_path(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: None)
    available, reason = sandbox.check_isolation_available()
    assert not available
    assert "not installed" in reason.lower() or "path" in reason.lower()


def test_refuses_when_docker_daemon_is_unreachable(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "C:/docker.exe")
    monkeypatch.setattr(
        sandbox, "run_tool",
        lambda *a, **k: ToolResult(exit_code=1, stdout="", stderr="daemon not running", timed_out=False, launch_failed=False),
    )
    available, reason = sandbox.check_isolation_available()
    assert not available
    assert reason


def test_reports_available_when_docker_responds(monkeypatch):
    monkeypatch.setattr(sandbox.shutil, "which", lambda _name: "C:/docker.exe")
    monkeypatch.setattr(
        sandbox, "run_tool",
        lambda *a, **k: ToolResult(exit_code=0, stdout="27.0.0", stderr="", timed_out=False, launch_failed=False),
    )
    available, reason = sandbox.check_isolation_available()
    assert available
    assert reason == ""


def test_run_in_container_never_uses_shell_true(tmp_path, monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    def fake_popen(args, shell=False, **kwargs):
        captured["args"] = args
        captured["shell"] = shell
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    outcome = sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"])
    assert captured["shell"] is False
    assert isinstance(captured["args"], list)
    assert "--network" in captured["args"] and "none" in captured["args"]
    assert outcome.exit_code == 0


def test_run_in_container_never_passes_host_environment(tmp_path, monkeypatch):
    """The container must never be launched with -e/--env-file forwarding
    this process's environment (that would defeat "no inherited secrets")."""
    captured = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "", ""

    def fake_popen(args, shell=False, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"])
    assert "-e" not in captured["args"]
    assert "--env-file" not in captured["args"]


def test_run_in_container_kills_on_timeout(tmp_path, monkeypatch):
    kill_calls = []

    class FakeProcess:
        returncode = None

        def communicate(self, timeout=None):
            if not kill_calls:
                raise subprocess.TimeoutExpired(cmd="docker", timeout=timeout)
            return "partial output", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProcess())

    def fake_run(args, **kwargs):
        kill_calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    outcome = sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"], timeout=0.01)
    assert outcome.timed_out
    assert outcome.exit_code is None
    assert kill_calls, "docker kill must be invoked when the run times out"
    assert kill_calls[0][:2] == ["docker", "kill"]


def test_run_in_container_handles_docker_binary_missing(tmp_path, monkeypatch):
    def raise_not_found(*a, **k):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(subprocess, "Popen", raise_not_found)
    outcome = sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"])
    assert outcome.launch_failed
    assert outcome.exit_code is None


@pytest.mark.skipif(not _docker_actually_available(), reason="Docker daemon is not reachable in this environment")
def test_live_isolated_run_executes_pytest_with_network_disabled(tmp_path):
    (tmp_path / "test_trivial.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    ready, error = sandbox.ensure_runner_image()
    assert ready, error
    outcome = sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"], timeout=60)
    assert not outcome.launch_failed
    assert not outcome.timed_out
    assert outcome.exit_code == 0
    assert "1 passed" in outcome.stdout
