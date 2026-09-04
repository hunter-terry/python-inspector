"""UI-independent application state machine.

Kept separate from any Tkinter/customtkinter code so the screen-flow rules
(what is allowed to happen next) can be unit tested without opening a
window. The `ui` package only reads from and calls methods on `AppState`;
it never encodes flow rules itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from .models import ApprovalRequest, Finding, ReportDocument, RunResult, ScanResult, SourceKind


class Screen(Enum):
    START = auto()
    PROJECT_REVIEW = auto()
    SCANNING = auto()
    RESULTS = auto()
    REPAIR_DETAILS = auto()
    RUN_APPROVAL = auto()
    SAVE_REPORT = auto()


class ScanPhase(Enum):
    IDLE = auto()
    RUNNING = auto()
    CANCELLED = auto()
    FAILED = auto()
    COMPLETED = auto()


class InvalidTransition(RuntimeError):
    """Raised when a screen/action is requested out of the approved order."""


@dataclass
class AppState:
    screen: Screen = Screen.START

    source_kind: SourceKind | None = None
    source_label: str | None = None

    scan_phase: ScanPhase = ScanPhase.IDLE
    scan_progress_label: str = ""
    scan_progress_fraction: float = 0.0
    scan_failure_reason: str | None = None
    scan_result: ScanResult | None = None

    selected_finding_id: str | None = None

    pending_approval: ApprovalRequest | None = None
    last_run_result: RunResult | None = None

    report: ReportDocument | None = None
    report_saved_to: str | None = None

    # -- Start / source selection -----------------------------------------
    def choose_local_folder(self, folder_path: str) -> None:
        if not folder_path:
            raise InvalidTransition("A folder path is required.")
        self.source_kind = SourceKind.LOCAL_FOLDER
        self.source_label = folder_path
        self.screen = Screen.PROJECT_REVIEW

    def choose_github_url(self, repo_url: str) -> None:
        if not repo_url:
            raise InvalidTransition("A GitHub URL is required.")
        self.source_kind = SourceKind.GITHUB_URL
        self.source_label = repo_url
        self.screen = Screen.PROJECT_REVIEW

    # -- Project review ------------------------------------------------------
    def back_to_start(self) -> None:
        self.screen = Screen.START
        self.source_kind = None
        self.source_label = None

    def begin_scan(self) -> None:
        if self.screen != Screen.PROJECT_REVIEW or self.source_label is None:
            raise InvalidTransition("A source must be reviewed before scanning.")
        self.screen = Screen.SCANNING
        self.scan_phase = ScanPhase.RUNNING
        self.scan_progress_label = "Starting scan..."
        self.scan_progress_fraction = 0.0
        self.scan_failure_reason = None
        self.scan_result = None

    # -- Scanning ------------------------------------------------------------
    def report_progress(self, label: str, fraction: float) -> None:
        if self.scan_phase != ScanPhase.RUNNING:
            return
        self.scan_progress_label = label
        self.scan_progress_fraction = max(0.0, min(1.0, fraction))

    def cancel_scan(self) -> None:
        if self.scan_phase != ScanPhase.RUNNING:
            raise InvalidTransition("Only a running scan can be cancelled.")
        self.scan_phase = ScanPhase.CANCELLED

    def scan_completed(self, result: ScanResult) -> None:
        if self.scan_phase != ScanPhase.RUNNING:
            return
        self.scan_result = result
        if result.cancelled:
            self.scan_phase = ScanPhase.CANCELLED
        elif result.failed:
            self.scan_phase = ScanPhase.FAILED
            self.scan_failure_reason = result.failure_reason
        else:
            self.scan_phase = ScanPhase.COMPLETED
            self.screen = Screen.RESULTS

    def retry_scan(self) -> None:
        if self.scan_phase not in (ScanPhase.FAILED, ScanPhase.CANCELLED):
            raise InvalidTransition("Retry is only available after a failed or cancelled scan.")
        self.screen = Screen.PROJECT_REVIEW
        self.scan_phase = ScanPhase.IDLE
        self.scan_result = None
        self.scan_failure_reason = None

    # -- Results / repair details ---------------------------------------------
    def open_repair_details(self, finding_id: str) -> None:
        if self.scan_result is None:
            raise InvalidTransition("No scan result is loaded.")
        if not any(f.finding_id == finding_id for f in self.scan_result.findings):
            raise InvalidTransition(f"Unknown finding id: {finding_id}")
        self.selected_finding_id = finding_id
        self.screen = Screen.REPAIR_DETAILS

    def back_to_results(self) -> None:
        self.screen = Screen.RESULTS
        self.selected_finding_id = None

    @property
    def selected_finding(self) -> Finding | None:
        if self.scan_result is None or self.selected_finding_id is None:
            return None
        for f in self.scan_result.findings:
            if f.finding_id == self.selected_finding_id:
                return f
        return None

    # -- Run approval ----------------------------------------------------------
    def request_run_approval(self, request: ApprovalRequest) -> None:
        if self.scan_result is None:
            raise InvalidTransition("A completed scan is required before requesting a run.")
        self.pending_approval = request
        self.last_run_result = None
        self.screen = Screen.RUN_APPROVAL

    def cancel_run_approval(self) -> None:
        if self.pending_approval is None:
            raise InvalidTransition("No approval request is pending.")
        self.pending_approval = None
        self.screen = Screen.RESULTS

    def record_run_result(self, result: RunResult) -> None:
        if self.pending_approval is None:
            raise InvalidTransition("No approval request is pending.")
        if result.request_id != self.pending_approval.request_id:
            raise InvalidTransition("Run result does not match the pending approval request.")
        self.last_run_result = result
        self.pending_approval = None
        # The approval screen has no further action once a result exists;
        # send Hunter back to Results rather than stranding him there.
        self.screen = Screen.RESULTS

    # -- Save report -------------------------------------------------------------
    def open_save_report(self, report: ReportDocument) -> None:
        if self.scan_result is None:
            raise InvalidTransition("A completed scan is required before a report can exist.")
        self.report = report
        self.screen = Screen.SAVE_REPORT

    def report_saved(self, destination_path: str) -> None:
        if self.report is None:
            raise InvalidTransition("No report is loaded to save.")
        if not destination_path:
            raise InvalidTransition("A destination is required to save.")
        self.report_saved_to = destination_path

    def close_save_report(self) -> None:
        self.screen = Screen.RESULTS
