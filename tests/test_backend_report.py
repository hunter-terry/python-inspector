"""Tests for report rendering: honesty about partial failures, and that
secrets/credentials never make it into the saved report text.
"""
from __future__ import annotations

from pathlib import Path

from inspector_app.backend.real_backend import RealBackend
from inspector_app.backend.report import render_report
from inspector_app.models import CheckOutcome, ScanResult, ScannerRunRecord

FIXTURES = Path(__file__).parent / "fixtures"
VULNERABLE = FIXTURES / "vulnerable_project"


def test_report_never_contains_the_raw_secret_value():
    backend = RealBackend()
    try:
        result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
        report = backend.render_report(result)
        combined = report.hunter_summary_markdown + "\n" + report.technical_packet_markdown
        assert "wJalrXUtnFEMI" not in combined
        assert "FAKEFAKEFAKEFAKE" not in combined
    finally:
        backend._cleanup_workspace_root()


def test_report_includes_the_guarantee_disclaimer():
    backend = RealBackend()
    try:
        result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
        report = backend.render_report(result)
        assert ScanResult.GUARANTEE_DISCLAIMER in report.hunter_summary_markdown
    finally:
        backend._cleanup_workspace_root()


def test_report_honestly_discloses_a_failed_scanner():
    from datetime import datetime, timezone

    from inspector_app.models import Confidence, Finding, FindingStatus, Severity, SourceKind

    finding = Finding(
        finding_id="RUFF-1", category="Code quality", severity=Severity.LOW, confidence=Confidence.HIGH,
        status=FindingStatus.INFORMATIONAL, summary="unused import", what_could_happen="minor",
        file_path="a.py", line_number=1, evidence="F401", suggested_repair="remove it",
        verification_steps=("re-run",), scanner_name="ruff", scanner_version="0.16.6",
    )
    scan_result = ScanResult(
        source_label="C:/some/project",
        source_kind=SourceKind.LOCAL_FOLDER,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        findings=(finding,),
        scanners_run=(
            ScannerRunRecord("ruff", "0.16.6", CheckOutcome.RAN),
            ScannerRunRecord("pip-audit", "2.10.1", CheckOutcome.FAILED, "network unreachable"),
        ),
    )
    report = render_report(scan_result)
    assert "FAILED" in report.hunter_summary_markdown
    assert "pip-audit" in report.hunter_summary_markdown
    assert "not a complete picture" in report.hunter_summary_markdown.lower()
    assert "FAILED" in report.technical_packet_markdown or "Failed" in report.technical_packet_markdown


def test_technical_packet_includes_repair_and_verification_content():
    backend = RealBackend()
    try:
        result = backend.scan_local_project(str(VULNERABLE), on_progress=lambda l, f: None, is_cancelled=lambda: False)
        report = backend.render_report(result)
        packet = report.technical_packet_markdown
        for finding in result.findings:
            assert finding.finding_id in packet
            assert finding.suggested_repair in packet
            for step in finding.verification_steps:
                assert step in packet
            assert finding.evidence in packet
    finally:
        backend._cleanup_workspace_root()


def test_report_for_cancelled_scan_has_no_findings_claim():
    from datetime import datetime, timezone

    from inspector_app.models import SourceKind

    scan_result = ScanResult(
        source_label="C:/some/project", source_kind=SourceKind.LOCAL_FOLDER,
        started_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc), cancelled=True,
    )
    report = render_report(scan_result)
    assert "cancelled" in report.hunter_summary_markdown.lower()
