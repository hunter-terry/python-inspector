from datetime import datetime, timezone

import pytest

from inspector_app.models import (
    ApprovalDecision,
    ApprovalRequest,
    Confidence,
    Finding,
    FindingStatus,
    ReportDocument,
    RunResult,
    ScanResult,
    Severity,
    SourceKind,
)
from inspector_app.state import AppState, InvalidTransition, ScanPhase, Screen


def _finding(finding_id: str = "FIND-001") -> Finding:
    return Finding(
        finding_id=finding_id,
        category="Security",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        status=FindingStatus.STRONG_FINDING,
        summary="summary",
        what_could_happen="bad things",
        file_path="a.py",
        line_number=1,
        evidence="evidence",
        suggested_repair="fix it",
        verification_steps=("step 1",),
        scanner_name="bandit",
        scanner_version="1.0",
    )


def _completed_scan(findings=()) -> ScanResult:
    now = datetime.now(timezone.utc)
    return ScanResult(
        source_label="C:/projects/demo",
        source_kind=SourceKind.LOCAL_FOLDER,
        started_at=now,
        completed_at=now,
        findings=findings,
    )


def test_starts_on_start_screen():
    state = AppState()
    assert state.screen is Screen.START


def test_choose_local_folder_moves_to_project_review():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    assert state.screen is Screen.PROJECT_REVIEW
    assert state.source_kind is SourceKind.LOCAL_FOLDER
    assert state.source_label == "C:/projects/demo"


def test_choose_local_folder_rejects_empty_path():
    state = AppState()
    with pytest.raises(InvalidTransition):
        state.choose_local_folder("")


def test_choose_github_url_moves_to_project_review():
    state = AppState()
    state.choose_github_url("https://github.com/example/demo")
    assert state.screen is Screen.PROJECT_REVIEW
    assert state.source_kind is SourceKind.GITHUB_URL


def test_cannot_begin_scan_without_reviewing_a_source():
    state = AppState()
    with pytest.raises(InvalidTransition):
        state.begin_scan()


def test_full_happy_path_reaches_results():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    assert state.screen is Screen.SCANNING
    assert state.scan_phase is ScanPhase.RUNNING

    state.report_progress("Scanning...", 0.5)
    assert state.scan_progress_fraction == 0.5

    result = _completed_scan(findings=(_finding(),))
    state.scan_completed(result)
    assert state.scan_phase is ScanPhase.COMPLETED
    assert state.screen is Screen.RESULTS
    assert state.scan_result is result


def test_cancel_scan_sets_cancelled_phase_and_result():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.cancel_scan()
    assert state.scan_phase is ScanPhase.CANCELLED

    now = datetime.now(timezone.utc)
    cancelled_result = ScanResult(
        source_label="C:/projects/demo",
        source_kind=SourceKind.LOCAL_FOLDER,
        started_at=now,
        completed_at=now,
        cancelled=True,
    )
    state.scan_completed(cancelled_result)
    # Cancelling must never land on Results.
    assert state.screen is Screen.SCANNING
    assert state.scan_phase is ScanPhase.CANCELLED


def test_cannot_cancel_a_scan_that_is_not_running():
    state = AppState()
    with pytest.raises(InvalidTransition):
        state.cancel_scan()


def test_failed_scan_records_reason_and_stays_off_results():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    now = datetime.now(timezone.utc)
    failed_result = ScanResult(
        source_label="C:/projects/demo",
        source_kind=SourceKind.LOCAL_FOLDER,
        started_at=now,
        completed_at=now,
        failed=True,
        failure_reason="disk error",
    )
    state.scan_completed(failed_result)
    assert state.scan_phase is ScanPhase.FAILED
    assert state.scan_failure_reason == "disk error"
    assert state.screen is Screen.SCANNING


def test_retry_scan_only_after_failure_or_cancel():
    state = AppState()
    with pytest.raises(InvalidTransition):
        state.retry_scan()

    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.cancel_scan()
    state.retry_scan()
    assert state.screen is Screen.PROJECT_REVIEW
    assert state.scan_phase is ScanPhase.IDLE


def test_open_repair_details_requires_known_finding():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.scan_completed(_completed_scan(findings=(_finding("FIND-001"),)))

    with pytest.raises(InvalidTransition):
        state.open_repair_details("FIND-999")

    state.open_repair_details("FIND-001")
    assert state.screen is Screen.REPAIR_DETAILS
    assert state.selected_finding.finding_id == "FIND-001"

    state.back_to_results()
    assert state.screen is Screen.RESULTS
    assert state.selected_finding_id is None


def test_run_approval_requires_no_preselected_decision():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.scan_completed(_completed_scan(findings=(_finding(),)))

    request = ApprovalRequest(
        request_id="RUN-1",
        finding_id="FIND-001",
        command_display="pytest -q",
        purpose="verify fix",
        safety_boundary="isolated copy",
        possible_risk="none expected",
    )
    state.request_run_approval(request)
    assert state.screen is Screen.RUN_APPROVAL
    assert state.pending_approval is request
    assert state.last_run_result is None  # nothing has run yet


def test_cancel_run_approval_leaves_no_run_result():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.scan_completed(_completed_scan(findings=(_finding(),)))
    request = ApprovalRequest("RUN-1", "FIND-001", "cmd", "purpose", "boundary", "risk")
    state.request_run_approval(request)

    state.cancel_run_approval()
    assert state.screen is Screen.RESULTS
    assert state.pending_approval is None
    assert state.last_run_result is None


def test_record_run_result_must_match_pending_request():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.scan_completed(_completed_scan(findings=(_finding(),)))
    request = ApprovalRequest("RUN-1", "FIND-001", "cmd", "purpose", "boundary", "risk")
    state.request_run_approval(request)

    mismatched = RunResult("RUN-OTHER", ApprovalDecision.APPROVED, 0, "", "", 0.1)
    with pytest.raises(InvalidTransition):
        state.record_run_result(mismatched)

    matching = RunResult("RUN-1", ApprovalDecision.APPROVED, 0, "ok", "", 0.1)
    state.record_run_result(matching)
    assert state.last_run_result is matching
    assert state.pending_approval is None
    # Hunter must always have somewhere to go after a run completes.
    assert state.screen is Screen.RESULTS


def test_save_report_requires_completed_scan_and_destination():
    state = AppState()
    report = ReportDocument("summary", "packet", datetime.now(timezone.utc), "C:/projects/demo")
    with pytest.raises(InvalidTransition):
        state.open_save_report(report)

    state.choose_local_folder("C:/projects/demo")
    state.begin_scan()
    state.scan_completed(_completed_scan())
    state.open_save_report(report)
    assert state.screen is Screen.SAVE_REPORT

    with pytest.raises(InvalidTransition):
        state.report_saved("")

    state.report_saved("C:/reports/out.md")
    assert state.report_saved_to == "C:/reports/out.md"


def test_back_to_start_clears_source():
    state = AppState()
    state.choose_local_folder("C:/projects/demo")
    state.back_to_start()
    assert state.screen is Screen.START
    assert state.source_label is None
    assert state.source_kind is None
