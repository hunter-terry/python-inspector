"""The real, deterministic `InspectorBackend` implementation.

Orchestrates the read-only scanners, GitHub retrieval, the approval-gated
sandboxed runtime executor, and report rendering. See
docs/INTERFACE_CONTRACT.md and contract.py for the Protocol this satisfies.
"""
from __future__ import annotations

import atexit
import time
import dataclasses
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..contract import CancelledCheck, ProgressCallback
from ..models import (
    ApprovalDecision,
    ApprovalRequest,
    CheckOutcome,
    Finding,
    FindingStatus,
    ReportDocument,
    RunResult,
    ScannerRunRecord,
    ScanResult,
    SourceKind,
)
from . import github_source, sandbox
from .fs_util import has_pytest_suite, safe_rmtree
from .report import render_report as _render_report
from .scanners import ALL_SCANNERS

_RUNTIME_ELIGIBLE_STATUSES = {FindingStatus.CONFIRMED_FAILURE, FindingStatus.STRONG_FINDING}


class RealBackend:
    def __init__(self) -> None:
        self._workspace_root = Path(tempfile.mkdtemp(prefix=f"python-inspector-{uuid.uuid4().hex[:8]}-"))
        atexit.register(self._cleanup_workspace_root)

        # State for the single "current" reviewed scan -- matches the
        # frontend's own state machine, which only ever holds one
        # ScanResult under review at a time.
        self._current_source_label: str | None = None
        self._current_root_path: Path | None = None
        self._current_has_tests: bool = False
        self._pending_requests: dict[str, dict] = {}

    # -- cleanup -------------------------------------------------------------
    def _cleanup_workspace_root(self) -> None:
        if not self._workspace_root.exists():
            return
        # Try up to 3 times to remove the workspace root
        for i in range(3):
            try:
                safe_rmtree(self._workspace_root)
                # Check if it's gone
                if not self._workspace_root.exists():
                    return
            except Exception:
                pass  # We'll try again
            # Wait a bit before retrying
            time.sleep(0.1 * (2 ** i))  # 0.1, 0.2, 0.4 seconds
        # If we still haven't removed it, try one more time without waiting
        try:
            safe_rmtree(self._workspace_root)
        except Exception:
            pass

    def end_session(self) -> None:
        """Release reviewed source when leaving Results or closing the app."""
        self._retire_previous_workspace()
        self._cleanup_workspace_root()

    def _retire_previous_workspace(self) -> None:
        """Remove the disposable clone from the *previous* scan, if any.

        Local folders are never removed here -- they are Hunter's own
        project, never a disposable copy. Only a GitHub clone lives under
        `self._workspace_root` and needs explicit cleanup.
        """
        if self._current_root_path is not None and self._workspace_root in self._current_root_path.parents:
            safe_rmtree(self._current_root_path)
        self._current_source_label = None
        self._current_root_path = None
        self._current_has_tests = False
        self._pending_requests.clear()

    # -- shared scan pipeline -------------------------------------------------
    def _run_all_scanners(
        self,
        project_dir: Path,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> tuple[tuple[ScannerRunRecord, ...], tuple[Finding, ...], bool]:
        records: list[ScannerRunRecord] = []
        findings: list[Finding] = []
        total = len(ALL_SCANNERS)

        for index, scanner_fn in enumerate(ALL_SCANNERS, start=1):
            if is_cancelled():
                return tuple(records), tuple(findings), True
            on_progress(f"Running {scanner_fn.__name__.removeprefix('run_')}...", (index - 1) / total)
            try:
                record, scanner_findings = scanner_fn(project_dir)
            except Exception as exc:
                # If a scanner raises an unexpected exception, record it as FAILED and continue
                record = ScannerRunRecord(scanner_fn.__name__.removeprefix('run_'), "unknown", CheckOutcome.FAILED, str(exc))
                scanner_findings = ()
            records.append(record)
            findings.extend(scanner_findings)
            on_progress(f"Finished {scanner_fn.__name__.removeprefix('run_')}", index / total)

        return tuple(records), tuple(findings), False

    def _finalize_findings(self, findings: tuple[Finding, ...], has_tests: bool) -> tuple[Finding, ...]:
        if not has_tests:
            return findings
        return tuple(
            dataclasses.replace(f, runtime_check_available=f.status in _RUNTIME_ELIGIBLE_STATUSES)
            for f in findings
        )

    # -- InspectorBackend: scanning -------------------------------------------
    def scan_local_project(
        self,
        folder_path: str,
        *,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> ScanResult:
        self._retire_previous_workspace()
        started_at = datetime.now(timezone.utc)
        project_dir = Path(folder_path)

        if not project_dir.is_dir():
            return ScanResult(
                source_label=folder_path,
                source_kind=SourceKind.LOCAL_FOLDER,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                failed=True,
                failure_reason=f"'{folder_path}' is not a folder that exists on this machine.",
            )

        records, findings, cancelled = self._run_all_scanners(project_dir, on_progress, is_cancelled)
        if cancelled:
            return ScanResult(
                source_label=folder_path,
                source_kind=SourceKind.LOCAL_FOLDER,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                cancelled=True,
            )

        has_tests = has_pytest_suite(project_dir)
        self._current_source_label = folder_path
        self._current_root_path = project_dir
        self._current_has_tests = has_tests

        return ScanResult(
            source_label=folder_path,
            source_kind=SourceKind.LOCAL_FOLDER,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            findings=self._finalize_findings(findings, has_tests),
            scanners_run=records,
        )

    def scan_github_project(
        self,
        repo_url: str,
        *,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> ScanResult:
        self._retire_previous_workspace()
        started_at = datetime.now(timezone.utc)

        is_valid, message = github_source.validate_github_url(repo_url)
        if not is_valid:
            return ScanResult(
                source_label=repo_url,
                source_kind=SourceKind.GITHUB_URL,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                failed=True,
                failure_reason=message,
            )

        on_progress("Cloning repository into a disposable workspace...", 0.02)
        clone_dir = self._workspace_root / f"clone-{uuid.uuid4().hex[:12]}"
        outcome = github_source.clone_repository(repo_url, clone_dir, is_cancelled=is_cancelled)

        if outcome.cancelled:
            return ScanResult(
                source_label=repo_url,
                source_kind=SourceKind.GITHUB_URL,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                cancelled=True,
            )
        if not outcome.ok:
            return ScanResult(
                source_label=repo_url,
                source_kind=SourceKind.GITHUB_URL,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                failed=True,
                failure_reason=outcome.error,
            )

        records, findings, cancelled = self._run_all_scanners(clone_dir, on_progress, is_cancelled)
        if cancelled:
            safe_rmtree(clone_dir)
            return ScanResult(
                source_label=repo_url,
                source_kind=SourceKind.GITHUB_URL,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                cancelled=True,
            )

        has_tests = has_pytest_suite(clone_dir)
        # Kept around (not deleted here) so an approved runtime check can
        # still find the code -- removed on the next scan, or at app exit.
        self._current_source_label = repo_url
        self._current_root_path = clone_dir
        self._current_has_tests = has_tests

        return ScanResult(
            source_label=repo_url,
            source_kind=SourceKind.GITHUB_URL,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            findings=self._finalize_findings(findings, has_tests),
            scanners_run=records,
        )

    # -- InspectorBackend: approval-gated runtime checks ----------------------
    def build_approval_request(self, scan_result: ScanResult, finding_id: str) -> ApprovalRequest:
        request_id = f"RUN-{finding_id}-{uuid.uuid4().hex[:8]}"
        can_run = (
            self._current_has_tests
            and self._current_source_label == scan_result.source_label
            and self._current_root_path is not None
        )
        self._pending_requests[request_id] = {
            "finding_id": finding_id,
            "source_label": scan_result.source_label,
            "runnable": can_run,
        }

        if not can_run:
            return ApprovalRequest(
                request_id=request_id,
                finding_id=finding_id,
                command_display="(no automated tests were found in this project)",
                purpose="There is no discoverable automated test suite in this project, so there is nothing safe and specific to execute.",
                safety_boundary="Nothing will be executed.",
                possible_risk="None -- nothing runs.",
            )

        return ApprovalRequest(
            request_id=request_id,
            finding_id=finding_id,
            command_display="pytest -q",
            purpose=(
                "Runs this project's own automated test suite to see whether it currently passes. "
                "This does not verify a fix for any specific finding (V1 does not generate custom "
                "regression tests), but the result is real, current evidence you can weigh alongside "
                "the finding above."
            ),
            safety_boundary=(
                f"Runs in a disposable copy of the project, inside an isolated Docker container with "
                f"no network access (--network none), capped at {sandbox.MEMORY_LIMIT} memory / "
                f"{sandbox.CPU_LIMIT} CPU / {sandbox.PIDS_LIMIT} processes, a "
                f"{int(sandbox.DEFAULT_RUN_TIMEOUT)}-second timeout, and no access to this machine's "
                "environment variables or credentials. If isolation cannot be verified at run time, "
                "nothing is executed."
            ),
            possible_risk=(
                "If the test suite has side effects, those effects stay inside the disposable, "
                "network-disabled copy, which is deleted afterward regardless of outcome."
            ),
        )

    def run_approved_check(self, request: ApprovalRequest, is_cancelled: CancelledCheck | None = None) -> RunResult:
        started = datetime.now(timezone.utc)
        meta = self._pending_requests.get(request.request_id)

        if meta is None or not meta.get("runnable"):
            return RunResult(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVED,
                exit_code=None,
                stdout="",
                stderr="No automated test suite was available for this project, so nothing was run.",
                duration_seconds=0.0,
                timed_out=False,
            )

        available, reason = sandbox.check_isolation_available()
        if not available:
            return RunResult(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVED,
                exit_code=None,
                stdout="",
                stderr=(
                    "Refused: real, provable isolation could not be established on this machine, so "
                    f"nothing was executed. Reason: {reason}"
                ),
                duration_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                timed_out=False,
            )

        image_ready, image_error = sandbox.ensure_runner_image()
        if not image_ready:
            return RunResult(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVED,
                exit_code=None,
                stdout="",
                stderr=f"Refused: could not prepare the isolated runner image, so nothing was executed. Reason: {image_error}",
                duration_seconds=(datetime.now(timezone.utc) - started).total_seconds(),
                timed_out=False,
            )

        self._workspace_root.mkdir(parents=True, exist_ok=True)
        disposable_copy = self._workspace_root / f"run-{uuid.uuid4().hex[:12]}"
        try:
            shutil.copytree(
                self._current_root_path,
                disposable_copy,
                ignore=shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", "*.pyc"),
            )
            outcome = sandbox.run_in_isolated_container(disposable_copy, ["pytest", "-q"], is_cancelled=is_cancelled)
        finally:
            safe_rmtree(disposable_copy)

        duration = (datetime.now(timezone.utc) - started).total_seconds()
        if outcome.launch_failed:
            return RunResult(
                request_id=request.request_id,
                decision=ApprovalDecision.APPROVED,
                exit_code=None,
                stdout="",
                stderr=f"Refused: could not launch the isolated container. Reason: {outcome.launch_error}",
                duration_seconds=duration,
                timed_out=False,
            )

        return RunResult(
            request_id=request.request_id,
            decision=ApprovalDecision.APPROVED,
            exit_code=outcome.exit_code,
            stdout=outcome.stdout[-20000:],
            stderr=outcome.stderr[-20000:],
            duration_seconds=duration,
            timed_out=outcome.timed_out,
        )

    # -- InspectorBackend: report ----------------------------------------------
    def render_report(self, scan_result: ScanResult) -> ReportDocument:
        return _render_report(scan_result)
