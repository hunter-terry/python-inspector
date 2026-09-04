"""End-to-end test driving the real frontend state machine (`AppState`)
together with `RealBackend`, the same way `AppController` does, but without
opening a Tk window -- consistent with this project's existing test
philosophy (see tests/test_state.py): the state machine and contract layer
are fully exercised without a display.

This is the full path: pick a local folder -> review -> scan -> results ->
repair details -> request run approval -> approve and run -> save report.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from inspector_app.backend.real_backend import RealBackend
from inspector_app.backend import sandbox
from inspector_app.state import AppState, ScanPhase, Screen

FIXTURES = Path(__file__).parent / "fixtures"
VULNERABLE = FIXTURES / "vulnerable_project"
CLEAN = FIXTURES / "clean_project"


def test_full_flow_through_real_backend_with_findings(tmp_path):
    project = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, project)

    state = AppState()
    backend = RealBackend()
    try:
        state.choose_local_folder(str(project))
        assert state.screen is Screen.PROJECT_REVIEW

        state.begin_scan()
        assert state.screen is Screen.SCANNING

        result = backend.scan_local_project(
            str(project),
            on_progress=lambda label, frac: state.report_progress(label, frac),
            is_cancelled=lambda: False,
        )
        state.scan_completed(result)
        assert state.screen is Screen.RESULTS
        assert state.scan_phase is ScanPhase.COMPLETED
        assert len(state.scan_result.findings) > 0

        finding = state.scan_result.findings[0]
        state.open_repair_details(finding.finding_id)
        assert state.screen is Screen.REPAIR_DETAILS
        assert state.selected_finding.finding_id == finding.finding_id

        state.back_to_results()
        request = backend.build_approval_request(state.scan_result, finding.finding_id)
        state.request_run_approval(request)
        assert state.screen is Screen.RUN_APPROVAL
        assert state.pending_approval is request

        # This fixture has no test suite, so the honest, safe outcome is
        # "nothing was run" -- proven without needing Docker.
        run_result = backend.run_approved_check(request)
        state.record_run_result(run_result)
        assert state.screen is Screen.RESULTS
        assert run_result.exit_code is None
        assert "no automated test" in run_result.stderr.lower() or "nothing was run" in run_result.stderr.lower()

        report = backend.render_report(state.scan_result)
        state.open_save_report(report)
        assert state.screen is Screen.SAVE_REPORT

        destination = tmp_path / "report.md"
        content = report.hunter_summary_markdown + "\n\n---\n\n" + report.technical_packet_markdown
        destination.write_text(content, encoding="utf-8")
        state.report_saved(str(destination))
        assert state.report_saved_to == str(destination)
        assert destination.exists()
        assert "wJalrXUtnFEMI" not in destination.read_text(encoding="utf-8")
    finally:
        backend._cleanup_workspace_root()


def test_full_flow_with_mocked_isolated_runtime_check(tmp_path, monkeypatch):
    """Same flow, but against a project with a real test suite, with Docker
    mocked as available so the whole approval -> isolated run -> result path
    is exercised deterministically regardless of whether Docker is actually
    running on the machine executing this test suite."""
    project = tmp_path / "clean"
    shutil.copytree(CLEAN, project)

    monkeypatch.setattr(sandbox, "check_isolation_available", lambda: (True, ""))
    monkeypatch.setattr(sandbox, "ensure_runner_image", lambda: (True, ""))
    monkeypatch.setattr(
        sandbox, "run_in_isolated_container",
        lambda workspace, command, timeout=120: sandbox.ContainerRunOutcome(
            exit_code=0, stdout="1 passed in 0.01s", stderr="", timed_out=False,
        ),
    )

    state = AppState()
    backend = RealBackend()
    try:
        state.choose_local_folder(str(project))
        state.begin_scan()
        result = backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: False)
        state.scan_completed(result)
        assert state.screen is Screen.RESULTS
        assert result.is_empty  # clean_project has no findings

        # Even with no findings to attach it to, the runtime check itself is
        # exercised directly against the backend's current workspace.
        request = backend.build_approval_request(result, "N/A")
        assert "pytest" in request.command_display

        run_result = backend.run_approved_check(request)
        assert run_result.exit_code == 0
        assert "1 passed" in run_result.stdout
    finally:
        backend._cleanup_workspace_root()


def test_cancelling_a_scan_never_reaches_results(tmp_path):
    project = tmp_path / "vulnerable"
    shutil.copytree(VULNERABLE, project)

    state = AppState()
    backend = RealBackend()
    try:
        state.choose_local_folder(str(project))
        state.begin_scan()
        state.cancel_scan()

        result = backend.scan_local_project(str(project), on_progress=lambda l, f: None, is_cancelled=lambda: True)
        state.scan_completed(result)

        assert state.screen is Screen.SCANNING
        assert state.scan_phase is ScanPhase.CANCELLED
        assert result.findings == ()
    finally:
        backend._cleanup_workspace_root()
