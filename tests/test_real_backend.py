"""Integration tests for RealBackend orchestrating scanners, GitHub
retrieval, and the approval-gated runtime executor together.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from inspector_app.backend import sandbox
from inspector_app.backend.real_backend import RealBackend
from inspector_app.models import ApprovalDecision, CheckOutcome, SourceKind

FIXTURES = Path(__file__).parent / "fixtures"
VULNERABLE = FIXTURES / "vulnerable_project"
CLEAN = FIXTURES / "clean_project"


@pytest.fixture()
def backend():
    b = RealBackend()
    yield b
    b._cleanup_workspace_root()


def test_scan_local_project_reports_findings_and_scanner_outcomes(backend):
    result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert not result.failed
    assert not result.cancelled
    assert result.source_kind is SourceKind.LOCAL_FOLDER
    assert len(result.findings) > 0
    assert {r.scanner_name for r in result.scanners_run} == {
        "ruff", "bandit", "pip-audit", "detect-secrets", "repo-config-checker",
    }
    assert all(r.outcome == CheckOutcome.RAN for r in result.scanners_run)


def test_scan_nonexistent_local_folder_fails_clearly(backend):
    result = backend.scan_local_project(
        str(Path.cwd() / "this-folder-does-not-exist-abc123"),
        on_progress=lambda l, f: None, is_cancelled=lambda: False,
    )
    assert result.failed
    assert result.failure_reason


def test_scan_respects_cancellation_immediately(backend):
    progress_calls = []
    result = backend.scan_local_project(
        str(VULNERABLE),
        on_progress=lambda l, f: progress_calls.append((l, f)),
        is_cancelled=lambda: True,
    )
    assert result.cancelled
    assert result.findings == ()


def test_clean_project_has_no_findings_and_is_empty(backend):
    result = backend.scan_local_project(str(CLEAN), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert result.is_empty


def test_runtime_check_offered_only_when_project_has_tests(backend):
    vuln_result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert all(not f.runtime_check_available for f in vuln_result.findings)  # no tests/ in this fixture

    clean_result = backend.scan_local_project(str(CLEAN), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert clean_result.is_empty  # nothing to offer a runtime check for, but has_tests is tracked internally
    assert backend._current_has_tests is True


def test_source_project_is_byte_for_byte_unchanged_after_scan(backend, tmp_path):
    project = tmp_path / "project"
    shutil.copytree(VULNERABLE, project)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}

    backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)

    after = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert before == after
    assert set(before) == set(after)


def test_build_approval_request_is_refused_gracefully_when_no_tests_exist(backend):
    result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    confirmed = next(f for f in result.findings if f.status.value in ("Confirmed failure", "Strong finding"))
    request = backend.build_approval_request(result, confirmed.finding_id)
    assert "no automated tests" in request.command_display.lower() or "no automated tests" in request.purpose.lower()

    run_result = backend.run_approved_check(request)
    assert run_result.decision is ApprovalDecision.APPROVED
    assert run_result.exit_code is None
    assert "nothing was run" in run_result.stderr.lower() or "no automated test" in run_result.stderr.lower()


def test_scanning_alone_never_executes_the_project(backend, monkeypatch):
    """A read-only scan must never invoke the runtime executor at all."""
    called = {"count": 0}

    def spy(*a, **k):
        called["count"] += 1
        raise AssertionError("run_in_isolated_container must not be called during a scan")

    monkeypatch.setattr(sandbox, "run_in_isolated_container", spy)
    backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert called["count"] == 0


def test_run_approved_check_refuses_when_docker_unavailable(backend, monkeypatch, tmp_path):
    project = tmp_path / "has_tests"
    shutil.copytree(CLEAN, project)
    result = backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    request = backend.build_approval_request(result, result.findings[0].finding_id if result.findings else "N/A")
    # clean_project has no findings, so build a request against a dummy id via has_tests path directly instead
    assert backend._current_has_tests is True

    from inspector_app.models import ApprovalRequest
    request_id = "RUN-TEST-1"
    backend._pending_requests[request_id] = {"finding_id": "N/A", "source_label": result.source_label, "runnable": True}
    fake_request = ApprovalRequest(
        request_id=request_id, finding_id="N/A", command_display="pytest -q",
        purpose="test", safety_boundary="test", possible_risk="test",
    )

    monkeypatch.setattr(sandbox, "check_isolation_available", lambda: (False, "Docker is not running."))
    run_result = backend.run_approved_check(fake_request)
    assert run_result.exit_code is None
    assert "refused" in run_result.stderr.lower()
    assert "docker is not running" in run_result.stderr.lower()


def test_run_approved_check_never_modifies_the_original_project(backend, monkeypatch, tmp_path):
    project = tmp_path / "has_tests"
    shutil.copytree(CLEAN, project)
    result = backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}

    from inspector_app.models import ApprovalRequest
    request_id = "RUN-TEST-2"
    backend._pending_requests[request_id] = {"finding_id": "N/A", "source_label": result.source_label, "runnable": True}
    fake_request = ApprovalRequest(
        request_id=request_id, finding_id="N/A", command_display="pytest -q",
        purpose="test", safety_boundary="test", possible_risk="test",
    )
    monkeypatch.setattr(sandbox, "check_isolation_available", lambda: (True, ""))
    monkeypatch.setattr(sandbox, "ensure_runner_image", lambda: (True, ""))

    def fake_run(workspace, command, timeout=120):
        # simulate a test run that writes a stray file into the *disposable copy*
        (workspace / "side_effect.txt").write_text("ran", encoding="utf-8")
        return sandbox.ContainerRunOutcome(exit_code=0, stdout="1 passed", stderr="", timed_out=False)

    monkeypatch.setattr(sandbox, "run_in_isolated_container", fake_run)
    backend.run_approved_check(fake_request)

    after = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert before == after, "the original project must never be touched by a runtime check"


def test_github_workspace_is_cleaned_up_when_a_new_scan_starts(backend, monkeypatch):
    from inspector_app.backend import github_source

    def fake_clone(url, dest, *, is_cancelled):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        return github_source.CloneOutcome(ok=True)

    monkeypatch.setattr(github_source, "clone_repository", fake_clone)
    first = backend.scan_github_project(
        "https://github.com/example/demo", on_progress=lambda l, f: None, is_cancelled=lambda: False
    )
    first_workspace = backend._current_root_path
    assert first_workspace.exists()

    backend.scan_local_project(str(CLEAN), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert not first_workspace.exists(), "the previous GitHub clone must be removed once a new scan starts"


def test_local_folder_is_never_deleted_by_workspace_cleanup(backend, tmp_path):
    project = tmp_path / "local"
    shutil.copytree(CLEAN, project)
    backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert project.exists()
    assert (project / "app.py").exists()


def _network_available() -> bool:
    import socket

    try:
        socket.create_connection(("github.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _network_available(), reason="no network access to github.com in this environment")
def test_live_github_scan_completes_in_disposable_workspace_and_cleans_up(backend):
    result = backend.scan_github_project(
        "https://github.com/octocat/Hello-World",
        on_progress=lambda l, f: None,
        is_cancelled=lambda: False,
    )
    assert not result.failed, result.failure_reason
    assert not result.cancelled
    assert result.source_kind is SourceKind.GITHUB_URL
    assert all(r.outcome != CheckOutcome.FAILED for r in result.scanners_run)
    workspace = backend._current_root_path
    assert workspace is not None and workspace.exists()

    # A second scan retires the first GitHub workspace -- proving temporary
    # GitHub contents are removed rather than kept forever.
    backend.scan_local_project(str(CLEAN), on_progress=lambda l, f: None, is_cancelled=lambda: False)
    assert not workspace.exists()
