from datetime import datetime, timezone

from inspector_app.models import ScanResult, SourceKind


def test_scan_result_is_empty_only_when_no_findings_and_not_cancelled_or_failed():
    now = datetime.now(timezone.utc)
    empty = ScanResult("x", SourceKind.LOCAL_FOLDER, now, now)
    assert empty.is_empty

    cancelled = ScanResult("x", SourceKind.LOCAL_FOLDER, now, now, cancelled=True)
    assert not cancelled.is_empty

    failed = ScanResult("x", SourceKind.LOCAL_FOLDER, now, now, failed=True)
    assert not failed.is_empty


def test_guarantee_disclaimer_is_present_and_honest():
    disclaimer = ScanResult.GUARANTEE_DISCLAIMER.lower()
    assert "cannot guarantee" in disclaimer
