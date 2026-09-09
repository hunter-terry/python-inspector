from inspector_app.contract import InspectorBackend
from inspector_app.mock_data import MockBackend
from inspector_app.models import ApprovalDecision, ScanResult, SourceKind


def test_mock_backend_satisfies_contract_shape():
    # Structural check: every contract method must exist and be callable.
    backend = MockBackend(step_seconds=0)
    assert isinstance(backend, InspectorBackend)
    for name in (
        "scan_local_project",
        "scan_github_project",
        "build_approval_request",
        "run_approved_check",
        "render_report",
    ):
        assert callable(getattr(backend, name))


def test_scan_local_project_returns_completed_result():
    backend = MockBackend(step_seconds=0)
    progress_calls = []
    result = backend.scan_local_project(
        "C:/projects/demo",
        on_progress=lambda label, frac: progress_calls.append((label, frac)),
        is_cancelled=lambda: False,
    )
    assert isinstance(result, ScanResult)
    assert result.source_kind is SourceKind.LOCAL_FOLDER
    assert not result.cancelled
    assert not result.failed
    assert len(result.findings) > 0
    assert progress_calls, "on_progress must be called at least once"
    assert progress_calls[-1][1] == 1.0


def test_scan_respects_cancellation():
    backend = MockBackend(step_seconds=0)
    result = backend.scan_local_project(
        "C:/projects/demo",
        on_progress=lambda label, frac: None,
        is_cancelled=lambda: True,
    )
    assert result.cancelled
    assert result.findings == ()


def test_scan_can_simulate_failure():
    backend = MockBackend(step_seconds=0, simulate_failure=True)
    result = backend.scan_local_project(
        "C:/projects/demo",
        on_progress=lambda label, frac: None,
        is_cancelled=lambda: False,
    )
    assert result.failed
    assert result.failure_reason


def test_build_approval_request_and_run_are_gated_by_caller():
    backend = MockBackend(step_seconds=0)
    scan_result = backend.scan_local_project(
        "C:/projects/demo", on_progress=lambda l, f: None, is_cancelled=lambda: False
    )
    finding_id = scan_result.findings[0].finding_id
    request = backend.build_approval_request(scan_result, finding_id)
    assert request.finding_id == finding_id
    assert request.command_display

    run_result = backend.run_approved_check(request)
    assert run_result.request_id == request.request_id
    assert run_result.decision is ApprovalDecision.APPROVED


def test_run_approved_check_accepts_is_cancelled_like_the_real_caller():
    """AppController.approve_and_run() always calls
    backend.run_approved_check(request, is_cancelled=self._cancel_flag.is_set) --
    it does not know or care whether the backend is real or mocked. A backend
    that only accepts `request` breaks that call with a TypeError the instant
    Hunter presses Approve and run in the demo app. Call it exactly the way
    the real frontend does."""
    backend = MockBackend(step_seconds=0)
    scan_result = backend.scan_local_project(
        "C:/projects/demo", on_progress=lambda l, f: None, is_cancelled=lambda: False
    )
    finding_id = scan_result.findings[0].finding_id
    request = backend.build_approval_request(scan_result, finding_id)

    run_result = backend.run_approved_check(request, is_cancelled=lambda: False)
    assert run_result.request_id == request.request_id
    assert run_result.decision is ApprovalDecision.APPROVED


def test_render_report_includes_disclaimer_and_findings():
    backend = MockBackend(step_seconds=0)
    scan_result = backend.scan_local_project(
        "C:/projects/demo", on_progress=lambda l, f: None, is_cancelled=lambda: False
    )
    report = backend.render_report(scan_result)
    assert ScanResult.GUARANTEE_DISCLAIMER in report.hunter_summary_markdown
    for finding in scan_result.findings:
        assert finding.finding_id in report.technical_packet_markdown
