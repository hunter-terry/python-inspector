"""Builds the two-layer report from a ScanResult: a plain-English summary for
Hunter, and a detailed technical packet for a person or external AI doing
the repair. Pure string formatting -- no file I/O (the frontend owns saving).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import CheckOutcome, FindingStatus, ReportDocument, ScanResult

_CONFIRMED_STATUSES = {FindingStatus.CONFIRMED_FAILURE, FindingStatus.STRONG_FINDING}


def render_report(scan_result: ScanResult) -> ReportDocument:
    return ReportDocument(
        hunter_summary_markdown=_render_hunter_summary(scan_result),
        technical_packet_markdown=_render_technical_packet(scan_result),
        generated_at=datetime.now(timezone.utc),
        source_label=scan_result.source_label,
    )


def _render_hunter_summary(scan_result: ScanResult) -> str:
    lines = [f"# Inspection summary — {scan_result.source_label}", ""]

    if scan_result.cancelled:
        lines.append("This scan was cancelled before it finished. No findings are available.")
        lines += ["", ScanResult.GUARANTEE_DISCLAIMER]
        return "\n".join(lines)
    if scan_result.failed:
        lines.append(f"This scan failed to complete: {scan_result.failure_reason or 'unknown error'}")
        lines += ["", ScanResult.GUARANTEE_DISCLAIMER]
        return "\n".join(lines)

    failed_checks = [r for r in scan_result.scanners_run if r.outcome == CheckOutcome.FAILED]
    unavailable_checks = [r for r in scan_result.scanners_run if r.outcome == CheckOutcome.UNAVAILABLE]

    if scan_result.is_empty:
        lines.append("No findings were produced by this scan.")
    else:
        confirmed = sum(1 for f in scan_result.findings if f.status in _CONFIRMED_STATUSES)
        possible = len(scan_result.findings) - confirmed
        lines.append(f"**{confirmed} confirmed, {possible} possible** finding(s).")
        lines.append("")
        for f in sorted(scan_result.findings, key=_severity_sort_key):
            lines.append(f"- **[{f.severity.value} / {f.status.value}] {f.category}** — {f.summary}")
            lines.append(f"  What could happen: {f.what_could_happen}")

    if failed_checks or unavailable_checks:
        lines += ["", "**Some checks did not run:**"]
        for r in failed_checks:
            lines.append(f"- {r.scanner_name}: FAILED — {r.detail or 'no detail available'}")
        for r in unavailable_checks:
            lines.append(f"- {r.scanner_name}: not available — {r.detail or 'no detail available'}")
        lines.append("Findings from these checks could not be included, so this report is not a complete picture.")

    lines += ["", ScanResult.GUARANTEE_DISCLAIMER]
    return "\n".join(lines)


def _render_technical_packet(scan_result: ScanResult) -> str:
    lines = [f"# Technical repair packet — {scan_result.source_label}", ""]

    lines.append("## Checks attempted")
    for r in scan_result.scanners_run:
        detail = f" — {r.detail}" if r.detail else ""
        lines.append(f"- {r.scanner_name} {r.scanner_version}: {r.outcome.value}{detail}")
    lines.append("")

    if scan_result.is_empty:
        lines.append("No findings to report.")
        return "\n".join(lines)

    for f in sorted(scan_result.findings, key=_severity_sort_key):
        lines += [
            f"## {f.finding_id}: {f.category} ({f.status.value})",
            f"- Severity: {f.severity.value}  |  Confidence: {f.confidence.value}",
            f"- Location: {f.file_path or 'n/a'}:{f.line_number if f.line_number is not None else '?'}",
            f"- Summary: {f.summary}",
            f"- What could happen: {f.what_could_happen}",
            f"- Evidence: `{f.evidence}`",
            f"- Suggested repair: {f.suggested_repair}",
            "- Verification steps:",
            *[f"  {i}. {step}" for i, step in enumerate(f.verification_steps, start=1)],
            f"- Scanner: {f.scanner_name} {f.scanner_version}",
            "",
        ]

    return "\n".join(lines)


_SEVERITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Info": 4}


def _severity_sort_key(finding) -> tuple[int, str]:
    return (_SEVERITY_ORDER.get(finding.severity.value, 99), finding.finding_id)
