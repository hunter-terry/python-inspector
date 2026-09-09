"""A fake backend implementing `InspectorBackend` with realistic mock data.

This exists ONLY so the frontend work order can demonstrate its complete
flow before the real backend is built. It performs no file I/O, no network
access, and no code execution -- everything here is fabricated or, for the
run step, simulated with a sleep. It must never be mistaken for the real
scanner; `MockBackend` is not exported from `contract`.
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timezone

from .contract import CancelledCheck, ProgressCallback
from .models import (
    ApprovalRequest,
    ApprovalDecision,
    CheckOutcome,
    Confidence,
    Finding,
    FindingStatus,
    ReportDocument,
    RunResult,
    ScanResult,
    ScannerRunRecord,
    Severity,
    SourceKind,
)

_MOCK_CHECK_STEPS = (
    "Parsing project structure...",
    "Running syntax and import checks...",
    "Scanning for security-sensitive patterns...",
    "Checking declared dependencies for known vulnerabilities...",
    "Reviewing repository configuration...",
    "Compiling findings...",
)

_MOCK_FINDINGS: tuple[Finding, ...] = (
    Finding(
        finding_id="FIND-001",
        category="Security: Injection",
        severity=Severity.CRITICAL,
        confidence=Confidence.HIGH,
        status=FindingStatus.CONFIRMED_FAILURE,
        summary="A database query is built by pasting user input directly into SQL text.",
        what_could_happen=(
            "Someone could enter text that changes what the query does, letting them read, "
            "change, or delete data they should not have access to."
        ),
        file_path="app/db/queries.py",
        line_number=42,
        evidence='cursor.execute("SELECT * FROM users WHERE name = \'" + user_name + "\'")',
        suggested_repair="Use a parameterized query, e.g. cursor.execute(\"SELECT * FROM users WHERE name = ?\", (user_name,)).",
        verification_steps=(
            "Re-run the security scan and confirm FIND-001 no longer appears.",
            "Add a test that passes a name like \"a' OR '1'='1\" and assert it is treated as a literal value.",
        ),
        scanner_name="bandit",
        scanner_version="1.7.9",
        runtime_check_available=True,
    ),
    Finding(
        finding_id="FIND-002",
        category="Dependency vulnerability",
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        status=FindingStatus.CONFIRMED_FAILURE,
        summary="A required package has a publicly known security vulnerability in the version pinned here.",
        what_could_happen="An attacker could exploit the known flaw in that package version if it is reachable.",
        file_path="requirements.txt",
        line_number=7,
        evidence="requests==2.25.0 (advisory: GHSA-example, fixed in 2.31.0+)",
        suggested_repair="Upgrade the pin to requests>=2.31.0 and re-test.",
        verification_steps=(
            "Update the pin and reinstall dependencies.",
            "Re-run the dependency scan and confirm the advisory is gone.",
        ),
        scanner_name="pip-audit",
        scanner_version="2.7.3",
        runtime_check_available=False,
    ),
    Finding(
        finding_id="FIND-003",
        category="Code quality",
        severity=Severity.MEDIUM,
        confidence=Confidence.MEDIUM,
        status=FindingStatus.STRONG_FINDING,
        summary="A function is over 150 lines long and handles several unrelated jobs.",
        what_could_happen="Bugs are more likely to hide in it, and future changes are more likely to break something else.",
        file_path="app/services/report_builder.py",
        line_number=18,
        evidence="def build_report(...): ... (162 lines, cyclomatic complexity 24)",
        suggested_repair="Split it into smaller functions, one job each, and add focused tests for each.",
        verification_steps=("Re-run the quality scan and confirm the complexity warning is resolved.",),
        scanner_name="ruff",
        scanner_version="0.6.9",
        runtime_check_available=False,
    ),
    Finding(
        finding_id="FIND-004",
        category="Security: Secrets",
        severity=Severity.HIGH,
        confidence=Confidence.MEDIUM,
        status=FindingStatus.POSSIBLE_FINDING,
        summary="A string that looks like an API key was found in a source file.",
        what_could_happen="If this is a real, active key, anyone with the source code could use it.",
        file_path="app/config/defaults.py",
        line_number=9,
        evidence='DEFAULT_API_KEY = "sk-********************"  (value redacted)',
        suggested_repair="Move the value to an environment variable or secret manager, and rotate the key if it was ever real.",
        verification_steps=(
            "Confirm with the project owner whether the key is/was live and rotate it if so.",
            "Re-run the secret scan and confirm no literal key remains in source.",
        ),
        scanner_name="detect-secrets",
        scanner_version="1.5.0",
        runtime_check_available=False,
    ),
    Finding(
        finding_id="FIND-005",
        category="Reliability",
        severity=Severity.LOW,
        confidence=Confidence.HIGH,
        status=FindingStatus.INFORMATIONAL,
        summary="A broad except clause silently swallows every error in a file-loading routine.",
        what_could_happen="Real failures could pass unnoticed instead of being logged or handled.",
        file_path="app/io/loader.py",
        line_number=55,
        evidence="except Exception:\n    pass",
        suggested_repair="Catch the specific exception types you expect, and log or re-raise anything unexpected.",
        verification_steps=("Re-run the quality scan and confirm the bare-except warning is gone.",),
        scanner_name="ruff",
        scanner_version="0.6.9",
        runtime_check_available=False,
    ),
)


class MockBackend:
    """Demo-only stand-in for the real backend. See module docstring."""

    def __init__(self, *, simulate_failure: bool = False, step_seconds: float = 0.35) -> None:
        self._simulate_failure = simulate_failure
        self._step_seconds = step_seconds

    def _run_mock_scan(
        self,
        source_label: str,
        source_kind: SourceKind,
        on_progress: ProgressCallback,
        is_cancelled: CancelledCheck,
    ) -> ScanResult:
        started_at = datetime.now(timezone.utc)
        total_steps = len(_MOCK_CHECK_STEPS)
        for index, label in enumerate(_MOCK_CHECK_STEPS, start=1):
            if is_cancelled():
                return ScanResult(
                    source_label=source_label,
                    source_kind=source_kind,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    cancelled=True,
                )
            on_progress(label, index / total_steps)
            time.sleep(self._step_seconds)

            if self._simulate_failure and index == 3:
                return ScanResult(
                    source_label=source_label,
                    source_kind=source_kind,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    failed=True,
                    failure_reason="Mock failure: the dependency scanner could not be reached (demo of the failed state).",
                )

        scanners_run = (
            ScannerRunRecord("bandit", "1.7.9", CheckOutcome.RAN),
            ScannerRunRecord("ruff", "0.6.9", CheckOutcome.RAN),
            ScannerRunRecord("pip-audit", "2.7.3", CheckOutcome.RAN),
            ScannerRunRecord("detect-secrets", "1.5.0", CheckOutcome.RAN),
            ScannerRunRecord("safety", "3.2.0", CheckOutcome.UNAVAILABLE, "Not installed in this demo environment."),
        )
        findings = tuple(random.sample(_MOCK_FINDINGS, k=len(_MOCK_FINDINGS)))
        return ScanResult(
            source_label=source_label,
            source_kind=source_kind,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            findings=findings,
            scanners_run=scanners_run,
        )

    def scan_local_project(self, folder_path, *, on_progress, is_cancelled) -> ScanResult:
        return self._run_mock_scan(folder_path, SourceKind.LOCAL_FOLDER, on_progress, is_cancelled)

    def scan_github_project(self, repo_url, *, on_progress, is_cancelled) -> ScanResult:
        return self._run_mock_scan(repo_url, SourceKind.GITHUB_URL, on_progress, is_cancelled)

    def build_approval_request(self, scan_result: ScanResult, finding_id: str) -> ApprovalRequest:
        finding = next(f for f in scan_result.findings if f.finding_id == finding_id)
        return ApprovalRequest(
            request_id=f"RUN-{finding_id}",
            finding_id=finding_id,
            command_display=f"pytest tests/test_regression_{finding_id.lower()}.py -q",
            purpose="Confirm the suggested repair actually fixes the finding, using the project's own tests.",
            safety_boundary=(
                "Runs in a disposable copy of the project, network disabled, 60-second timeout, "
                "no inherited secrets."
            ),
            possible_risk="If the project's test suite has side effects, those effects stay inside the disposable copy only.",
        )

    def run_approved_check(self, request: ApprovalRequest, is_cancelled: CancelledCheck | None = None) -> RunResult:
        time.sleep(0.6)
        return RunResult(
            request_id=request.request_id,
            decision=ApprovalDecision.APPROVED,
            exit_code=0,
            stdout="1 passed in 0.42s (mock output for demo purposes)",
            stderr="",
            duration_seconds=0.6,
        )

    def render_report(self, scan_result: ScanResult) -> ReportDocument:
        lines_summary = [f"# Inspection summary — {scan_result.source_label}", ""]
        if scan_result.is_empty:
            lines_summary.append("No findings were produced by this mock scan.")
        else:
            for f in scan_result.findings:
                lines_summary.append(f"- **[{f.severity.value}] {f.category}** — {f.summary}")
        lines_summary += ["", ScanResult.GUARANTEE_DISCLAIMER]

        lines_tech = [f"# Technical repair packet — {scan_result.source_label}", ""]
        for f in scan_result.findings:
            lines_tech += [
                f"## {f.finding_id}: {f.category} ({f.status.value})",
                f"- Severity: {f.severity.value}  |  Confidence: {f.confidence.value}",
                f"- Location: {f.file_path or 'n/a'}:{f.line_number or '?'}",
                f"- Evidence: `{f.evidence}`",
                f"- Suggested repair: {f.suggested_repair}",
                "- Verification steps:",
                *[f"  1. {step}" for step in f.verification_steps],
                f"- Scanner: {f.scanner_name} {f.scanner_version}",
                "",
            ]

        return ReportDocument(
            hunter_summary_markdown="\n".join(lines_summary),
            technical_packet_markdown="\n".join(lines_tech),
            generated_at=datetime.now(timezone.utc),
            source_label=scan_result.source_label,
        )
