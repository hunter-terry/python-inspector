"""Regression tests for the 5 findings from Claude Code's review of the
current codebase (2026-09-06), frozen *before* the repair so each test is
the ground truth for "fixed" rather than something the repair candidate
gets to define for itself. See the linked Claude Code Work Inbox
Maintenance row for the full write-up of each finding.

Every test here is expected to FAIL against the code as reviewed and PASS
once the corresponding fix lands. None of them should need Docker to be
reachable -- `docker`/`subprocess.Popen` are mocked throughout.
"""
from __future__ import annotations

import json
import subprocess

from inspector_app.backend import real_backend, sandbox, scanners
from inspector_app.backend.subprocess_utils import ToolResult
from inspector_app.models import CheckOutcome, ScannerRunRecord
from inspector_app.ui import theme


# -- Finding 1: closing the app mid-run doesn't cancel the sandboxed run ----

def test_run_in_container_stops_promptly_when_cancelled(tmp_path, monkeypatch):
    """`run_in_isolated_container` must accept a cooperative cancel check
    (matching the pattern `github_source.clone_repository` already uses)
    and kill the container promptly when it fires, instead of only ever
    reacting to the full `timeout`. This is what lets closing the app
    during an approved run stop in a couple of seconds instead of hanging
    for up to ~2 minutes."""
    kill_calls = []

    class FakeProcess:
        returncode = None

        def poll(self):
            return None  # never exits on its own during this test

        def communicate(self, timeout=None):
            return "partial output", ""

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProcess())

    def fake_run(args, **kwargs):
        kill_calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    outcome = sandbox.run_in_isolated_container(
        tmp_path, ["pytest", "-q"], timeout=120, is_cancelled=lambda: True,
    )
    assert kill_calls, "docker kill must be invoked promptly when cancelled, without waiting for the full timeout"
    assert kill_calls[0][:2] == ["docker", "kill"]
    assert outcome.timed_out or getattr(outcome, "cancelled", False)


def test_run_approved_check_forwards_cancellation_to_the_container(tmp_path, monkeypatch):
    """`RealBackend.run_approved_check` must accept an `is_cancelled`
    callable and pass it through to the sandbox, so the app's own
    `_cancel_flag` (set on close/back-to-start) can actually reach the
    running container instead of being ignored."""
    backend = real_backend.RealBackend()
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_x.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    backend._current_root_path = project
    backend._current_source_label = "local"
    backend._current_has_tests = True

    monkeypatch.setattr(sandbox, "check_isolation_available", lambda: (True, ""))
    monkeypatch.setattr(sandbox, "ensure_runner_image", lambda: (True, ""))

    captured = {}

    def fake_run_in_isolated_container(workspace, command, *, timeout=120, is_cancelled=None):
        captured["is_cancelled"] = is_cancelled
        return sandbox.ContainerRunOutcome(exit_code=0, stdout="ok", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "run_in_isolated_container", fake_run_in_isolated_container)

    from inspector_app.models import ApprovalRequest

    request = ApprovalRequest("RUN-x", "finding-1", "pytest -q", "", "", "")
    backend._pending_requests["RUN-x"] = {"finding_id": "finding-1", "source_label": "local", "runnable": True}

    sentinel = object()
    backend.run_approved_check(request, is_cancelled=sentinel)
    assert captured.get("is_cancelled") is sentinel


# -- Finding 2: a failed "Save report" shows its error in the success color -

def test_theme_defines_distinct_success_and_error_colors():
    assert hasattr(theme, "SUCCESS_COLOR")
    assert hasattr(theme, "ERROR_COLOR")
    assert theme.SUCCESS_COLOR != theme.ERROR_COLOR


# -- Finding 3: one scanner crashing aborts the whole scan -------------------

def test_one_scanner_crash_does_not_abort_the_whole_scan(tmp_path, monkeypatch):
    """A scanner raising an unexpected exception (not just a timeout or a
    JSON-parse error, which are already handled inside each scanner) must
    be reported as one FAILED ScannerRunRecord, and must never prevent the
    other scanners in the same run from completing."""

    def boom(project_dir):
        raise KeyError("UNDEFINED")

    def ok(project_dir):
        return ScannerRunRecord("ok-scanner", "1.0", CheckOutcome.RAN), ()

    monkeypatch.setattr(real_backend, "ALL_SCANNERS", (boom, ok))

    backend = real_backend.RealBackend()
    result = backend.scan_local_project(
        str(tmp_path), on_progress=lambda *a: None, is_cancelled=lambda: False,
    )
    assert not result.failed, "one scanner's crash must not fail the whole scan"
    outcomes = {r.scanner_name: r.outcome for r in result.scanners_run}
    assert outcomes.get("ok-scanner") == CheckOutcome.RAN
    assert CheckOutcome.FAILED in outcomes.values()


# -- Finding 4: the Docker sandbox runs unnecessarily privileged ------------

def test_run_in_container_drops_privileges_and_locks_the_root_filesystem(tmp_path, monkeypatch):
    captured = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    def fake_popen(args, shell=False, **kwargs):
        captured["args"] = args
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    sandbox.run_in_isolated_container(tmp_path, ["pytest", "-q"])
    args = captured["args"]
    assert "--cap-drop" in args and "ALL" in args, "container should drop all capabilities it does not need to run pytest"
    assert "--read-only" in args, "container's own root filesystem should be read-only (the workspace mount is unaffected)"


# -- Finding 5: bandit secret redaction is a 3-item test-ID allowlist -------

def test_bandit_redacts_any_future_hardcoded_credential_finding_by_cwe(tmp_path, monkeypatch):
    """Redaction must key off bandit's own CWE-798 (hard-coded credentials)
    tag on the finding, not only the current 3 known test IDs (B105/106/107)
    -- so a future bandit release that renames or adds a hardcoded-secret
    rule under a different test_id is still caught, instead of leaking the
    literal value the way B105-107 already once did."""
    sentinel = "sk-live-SENTINELVALUE12345"
    fake_payload = {
        "results": [{
            "test_id": "B999",
            "test_name": "hypothetical_future_hardcoded_secret_rule",
            "issue_severity": "LOW",
            "issue_confidence": "HIGH",
            "issue_text": f"Possible hardcoded secret: '{sentinel}'",
            "code": f"token = '{sentinel}'\n",
            "filename": str(tmp_path / "app.py"),
            "line_number": 3,
            "issue_cwe": {"id": 798, "link": "https://cwe.mitre.org/data/definitions/798.html"},
        }],
    }

    def fake_run_tool(args, **kwargs):
        if "--version" in args:
            return ToolResult(exit_code=0, stdout="9.9.9", stderr="", timed_out=False, launch_failed=False)
        return ToolResult(exit_code=1, stdout=json.dumps(fake_payload), stderr="", timed_out=False, launch_failed=False)

    monkeypatch.setattr("inspector_app.backend.scanners.run_tool", fake_run_tool)
    _, findings = scanners.run_bandit(tmp_path)

    assert len(findings) == 1
    assert sentinel not in findings[0].evidence
    assert sentinel not in findings[0].summary
    assert findings[0].category == "Security: Secrets"
