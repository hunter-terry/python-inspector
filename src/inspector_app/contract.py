"""The frontend-to-backend interface contract.

The backend work order ("Implement V1 Python Inspector backend and safety
controls") must supply an object that implements `InspectorBackend`. The
frontend depends only on this Protocol -- never on how a real backend
performs scanning, retrieval, or execution. `mock_data.MockBackend` is a
stand-in used only by this frontend work order, so the UI flow can be
demonstrated end-to-end before the real backend exists.

Threading contract: `scan_local_project` and `scan_github_project` are
called on a background thread by the frontend. `on_progress` and
`is_cancelled` may be called frequently and must be cheap and thread-safe.
`on_progress` receives (current_check_label, fraction_complete in [0, 1]).
"""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from .models import ApprovalRequest, ReportDocument, RunResult, ScanResult

ProgressCallback = Callable[[str, float], None]
CancelledCheck = Callable[[], bool]


@runtime_checkable
class InspectorBackend(Protocol):
    def scan_local_project(
        self,
        folder_path: str,
        *,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> ScanResult:
        """Read-only inspection of a local folder. Must never modify it."""
        ...

    def scan_github_project(
        self,
        repo_url: str,
        *,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> ScanResult:
        """Read-only inspection of a public GitHub repo in a disposable copy."""
        ...

    def build_approval_request(self, scan_result: ScanResult, finding_id: str) -> ApprovalRequest:
        """Produce the exact command/test to show Hunter, not yet run."""
        ...

    def run_approved_check(self, request: ApprovalRequest, is_cancelled: CancelledCheck | None = None) -> RunResult:
        """Only called after Hunter presses Approve and run.

        `is_cancelled` is optional so a backend without a real cancellable
        subprocess (e.g. a demo/mock stand-in) can ignore it, but every
        implementation must accept the parameter -- the frontend always
        passes it.
        """
        ...

    def render_report(self, scan_result: ScanResult) -> ReportDocument:
        """Build the Hunter summary + technical packet for preview/saving."""
        ...
