from dataclasses import replace
from datetime import datetime, timezone

import pytest

from inspector_app.backend import RealBackend, github_source
from inspector_app.models import (
    ApprovalDecision,
    ApprovalRequest,
    RunResult,
    ScanResult,
    SourceKind,
)
from inspector_app.state import AppState


def test_report_preserves_evidence_strength_and_repair_review_guidance():
    from inspector_app.backend.report import render_report
    from inspector_app.mock_data import _MOCK_FINDINGS
    from inspector_app.models import REPAIR_REVIEW_GUIDANCE, FindingStatus
    result = ScanResult("fixture", SourceKind.LOCAL_FOLDER, datetime.now(timezone.utc), None,
                        (replace(_MOCK_FINDINGS[0], status=FindingStatus.STRONG_FINDING),))
    report = render_report(result)
    assert "0 confirmed failures, 1 strong findings" in report.hunter_summary_markdown
    assert all(line in report.technical_packet_markdown for line in REPAIR_REVIEW_GUIDANCE)


@pytest.mark.parametrize("action", ["back_to_start", "begin_scan"])
def test_old_report_approval_and_run_do_not_leak_into_next_session(action):
    state = AppState()
    state.choose_local_folder("fixture")
    state.scan_result = ScanResult("old", SourceKind.LOCAL_FOLDER, datetime.now(timezone.utc), None)
    state.pending_approval = ApprovalRequest("old", None, "pytest -q", "", "", "")
    state.last_run_result = RunResult("old", ApprovalDecision.APPROVED, 0, "old output", "", 1)
    state.report_saved_to = "old-report.md"
    state.selected_finding_id = "old"
    getattr(state, action)()
    assert state.last_run_result is None
    assert state.pending_approval is None
    assert state.report_saved_to is None
    assert state.selected_finding_id is None
    assert state.scan_result is None


def test_end_session_removes_clone_and_parent_then_backend_can_scan_again(monkeypatch):
    backend = RealBackend()
    def clone(url, dest, *, is_cancelled):
        dest.mkdir(parents=True)
        (dest / "app.py").write_text("pass\n", encoding="utf-8")
        return github_source.CloneOutcome(ok=True)
    monkeypatch.setattr(github_source, "clone_repository", clone)
    monkeypatch.setattr(backend, "_run_all_scanners", lambda *args: ((), (), False))
    try:
        for _ in range(2):
            result = backend.scan_github_project("https://github.com/example/demo",
                                                 on_progress=lambda *args: None, is_cancelled=lambda: False)
            assert not result.failed
            clone_path = backend._current_root_path
            assert clone_path.exists()
            backend.end_session()
            assert not clone_path.exists()
            assert not backend._workspace_root.exists()
            assert backend._current_root_path is None
            assert not backend._pending_requests
    finally:
        backend.end_session()


def test_end_session_preserves_local_source(monkeypatch, tmp_path):
    source = tmp_path / "app.py"
    source.write_bytes(b"print('local source')\n")
    backend = RealBackend()
    monkeypatch.setattr(backend, "_run_all_scanners", lambda *args: ((), (), False))
    try:
        backend.scan_local_project(str(tmp_path), on_progress=lambda *args: None, is_cancelled=lambda: False)
        backend.end_session()
        assert source.read_bytes() == b"print('local source')\n"
        assert not backend._workspace_root.exists()
    finally:
        backend.end_session()
