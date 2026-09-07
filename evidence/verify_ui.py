r"""Display-required regression checks using real CTk widgets and clipboard.

Run: .venv\Scripts\python -m pytest evidence/verify_ui.py -q -s
Synthetic findings isolate rendering; separate tests exercise the real backend.
"""
import dataclasses
import time
import threading
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timezone

import customtkinter as ctk
import pytest

from inspector_app.mock_data import MockBackend, _MOCK_FINDINGS
from inspector_app.models import ApprovalDecision, RunResult, ScanResult, SourceKind
from inspector_app.state import Screen
from inspector_app.ui.app_window import AppController
from inspector_app.ui.screen_results import PAGE_SIZE


def pump(root, seconds=0.1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.005)


def widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from widgets(child)


def click(frame, label):
    button = next(w for w in widgets(frame) if isinstance(w, ctk.CTkButton) and w.cget("text") == label)
    # Exercise Tk's button event binding, not the controller method directly.
    button._canvas.event_generate("<Enter>", x=10, y=10)
    button._canvas.event_generate("<Button-1>", x=10, y=10)
    button._canvas.event_generate("<ButtonRelease-1>", x=10, y=10)
    return button


@pytest.fixture(scope="module")
def root():
    root = ctk.CTk()
    root.title("Python Inspector GUI regression checks")
    root.geometry("1000x680")
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    yield root
    root.destroy()
    assert not errors, errors


@pytest.fixture
def app(root):
    app = AppController(root, MockBackend())
    yield app
    app._end_session()
    if app._run_window is not None and app._run_window.winfo_exists():
        app._run_window.destroy()
    app.container.destroy()
    pump(root)


def load(app, count=400):
    result = ScanResult("UI fixture", SourceKind.LOCAL_FOLDER, datetime.now(timezone.utc),
                        datetime.now(timezone.utc), tuple(dataclasses.replace(_MOCK_FINDINGS[0],
                        finding_id=f"F-{i}") for i in range(count)))
    app.state.choose_local_folder("UI fixture")
    app.state.begin_scan()
    app.state.scan_completed(result)
    app.render()
    pump(app.root)
    return result


def test_400_findings_page_bounds_and_repeated_navigation(app):
    load(app)
    screen = app.screens[Screen.RESULTS]
    cards = screen.scroll.winfo_children()
    assert len(cards) == PAGE_SIZE
    start = time.monotonic()
    for _ in range(12):
        click(screen, "Repair details")
        pump(app.root, 0.02)
        click(app.screens[Screen.REPAIR_DETAILS], "< Back to results")
        pump(app.root, 0.02)
        assert screen.scroll.winfo_children() == cards
        assert sum(bool(s.winfo_ismapped()) for s in app.screens.values()) == 1
    elapsed = time.monotonic() - start
    assert elapsed < 8, elapsed
    for page in range(1, 40):
        screen.next_button.invoke()
        pump(app.root, 0.01)
        assert len(screen.scroll.winfo_children()) == PAGE_SIZE
    assert screen.page_label.cget("text") == "391–400 of 400 findings"
    assert screen.next_button.cget("state") == "disabled"
    click(screen, "Repair details")
    assert app.state.selected_finding_id == "F-390"
    print(f"12 detail/return cycles: {elapsed:.3f}s; all 40 pages reachable")


@pytest.mark.parametrize("count", [1, 400])
def test_header_save_navigation_and_real_file_write(app, monkeypatch, tmp_path, count):
    load(app, count)
    click(app.screens[Screen.RESULTS], "Save report")
    pump(app.root)
    assert app.state.screen == Screen.SAVE_REPORT
    destination = tmp_path / f"report-{count}.md"
    monkeypatch.setattr("inspector_app.ui.app_window.filedialog.asksaveasfilename", lambda **kw: str(destination))
    click(app.screens[Screen.SAVE_REPORT], "Save report")
    assert destination.read_text(encoding="utf-8")
    assert app.state.report_saved_to == str(destination)
    click(app.screens[Screen.SAVE_REPORT], "< Back to results")
    pump(app.root)
    click(app.screens[Screen.RESULTS], "Scan something else")
    assert app.state.screen == Screen.START
    assert app.state.scan_result is None
    assert app.state.report_saved_to is None


def test_clipboard_readback(app):
    load(app, 1)
    click(app.screens[Screen.RESULTS], "Repair details")
    pump(app.root)
    app.root.clipboard_clear()
    app.root.clipboard_append("sentinel")
    details = app.screens[Screen.REPAIR_DETAILS]
    click(details, "Copy for repair")
    pump(app.root)
    copied = app.root.clipboard_get()
    assert copied == details._clipboard_text
    assert "F-0" in copied and "Evidence:" in copied and "Verification steps:" in copied
    assert "untrusted data" in copied


@pytest.mark.parametrize("crash", [False, True])
def test_async_run_output_and_worker_failure(app, crash):
    load(app, 1)
    calls = []
    def run(request):
        calls.append(request.request_id)
        time.sleep(0.2)
        if crash:
            raise RuntimeError("fixture worker failure")
        return RunResult(request.request_id, ApprovalDecision.APPROVED, 1,
                         "stdout evidence", "stderr evidence", 0.2)
    app.backend.run_approved_check = run
    click(app.screens[Screen.RESULTS], "Request run approval")
    pump(app.root)
    assert not calls
    click(app.screens[Screen.RUN_APPROVAL], "Approve and run")
    app.approve_and_run()  # repeat dispatch must not launch a second run
    assert app._run_busy
    assert app.screens[Screen.RUN_APPROVAL].cancel_button.cget("state") == "disabled"
    deadline = time.monotonic() + 5
    while app._run_busy and time.monotonic() < deadline:
        pump(app.root, 0.05)
    assert not app._run_busy
    assert len(calls) == 1
    assert app.state.screen == Screen.RESULTS
    textbox = next(w for w in widgets(app._run_window) if isinstance(w, ctk.CTkTextbox))
    text = textbox.get("1.0", "end")
    if crash:
        assert "fixture worker failure" in text
    else:
        assert "stdout evidence" in text and "stderr evidence" in text
    app._run_window.destroy()
    app.screens[Screen.RESULTS].run_button.invoke()
    assert app._run_window.winfo_exists()


def test_timeout_is_not_labelled_passed(app):
    load(app, 1)
    result = RunResult("timed-out", ApprovalDecision.APPROVED, 0, "partial", "", 120, True)
    app._show_run_result_window(result)
    labels = [w.cget("text") for w in widgets(app._run_window) if isinstance(w, ctk.CTkLabel)]
    assert any("Timed out" in text for text in labels)


def test_cancelled_save_and_write_error_remain_reviewable(app, monkeypatch, tmp_path):
    load(app, 1)
    click(app.screens[Screen.RESULTS], "Save report")
    monkeypatch.setattr("inspector_app.ui.app_window.filedialog.asksaveasfilename", lambda **kw: "")
    app.save_report_to_disk()
    assert app.state.report_saved_to is None
    monkeypatch.setattr("inspector_app.ui.app_window.filedialog.asksaveasfilename", lambda **kw: str(tmp_path))
    app.save_report_to_disk()
    assert "Could not save" in app.screens[Screen.SAVE_REPORT].status_label.cget("text")
    assert app.state.report_saved_to is None


@pytest.mark.parametrize("count", [1, 400])
def test_real_native_save_dialog(app, tmp_path, count):
    from native_dialog_probe import inspect
    load(app, count)
    click(app.screens[Screen.RESULTS], "Save report")
    pump(app.root)
    destination = tmp_path / f"native-report-{count}.md"
    threading.Thread(target=inspect, args=(destination,), daemon=True).start()
    click(app.screens[Screen.SAVE_REPORT], "Save report")
    assert destination.is_file()
    assert "F-0" in destination.read_text(encoding="utf-8")
    print(f"Native Save dialog wrote {destination.stat().st_size} bytes for {count} findings")


def test_minimize_restore_forces_repaint(app):
    load(app, 20)
    app.root.attributes("-alpha", 1.0)
    app.root.iconify()
    pump(app.root, 0.2)
    app.root.deiconify()
    pump(app.root, 0.2)
    # The <Map> handler schedules the alpha nudge 30ms out; pumping past that
    # window must observe it actually fire and then settle back to opaque,
    # not just that the window is visible again.
    deadline = time.monotonic() + 1.0
    saw_nudge = False
    while time.monotonic() < deadline:
        if app.root.attributes("-alpha") != 1.0:
            saw_nudge = True
        pump(app.root, 0.02)
    assert saw_nudge, "restoring from minimized never triggered the repaint nudge"
    assert app.root.attributes("-alpha") == 1.0, "window was left partially transparent"


def test_repeated_native_folder_selection(app, tmp_path):
    from native_dialog_probe import inspect
    for _ in range(5):
        threading.Thread(target=inspect, args=(tmp_path,), daemon=True).start()
        app.pick_local_folder()
        assert Path(app.state.source_label).resolve() == tmp_path.resolve()
        assert app.state.screen == Screen.PROJECT_REVIEW
        app.back_to_start()
        pump(app.root)


def snapshot(project):
    return {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in project.rglob("*") if p.is_file()}


def capture(app, name):
    app.root.lift()
    app.root.focus_force()
    pump(app.root, 0.3)
    width, height = app.root.winfo_width(), app.root.winfo_height()
    destination = str(Path(__file__).parent / name).replace("'", "''")
    script = ("Add-Type -AssemblyName System.Drawing; "
              "Add-Type -Name Capture -Namespace Inspector -MemberDefinition "
              "'[System.Runtime.InteropServices.DllImport(\"user32.dll\")] "
              "public static extern bool PrintWindow(System.IntPtr hwnd, System.IntPtr hdc, uint flags);'; "
              f"$bitmap = New-Object System.Drawing.Bitmap({width},{height}); "
              "$graphics = [System.Drawing.Graphics]::FromImage($bitmap); "
              "$hdc = $graphics.GetHdc(); "
              f"[Inspector.Capture]::PrintWindow([IntPtr]{app.root.winfo_id()},$hdc,1) | Out-Null; "
              "$graphics.ReleaseHdc($hdc); "
              f"$bitmap.Save('{destination}'); $graphics.Dispose(); $bitmap.Dispose()")
    process = subprocess.Popen(["powershell", "-NoProfile", "-Command", script],
                               creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 20
    while process.poll() is None and time.monotonic() < deadline:
        pump(app.root, 0.05)  # PrintWindow sends a paint message to this Tk thread.
    if process.poll() is None:
        process.kill()
        pytest.fail("Window capture timed out")
    assert process.returncode == 0


def test_real_scan_large_report_clipboard_and_docker_output(app, tmp_path):
    from inspector_app.backend import RealBackend
    from native_dialog_probe import inspect
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("\n".join(f"import os as unused_{i}" for i in range(320))
                                    + "\n\ndef broken():\n    return undefined_name\n", encoding="utf-8")
    (project / "test_app.py").write_text("def test_safe_fixture():\n    assert 2 + 2 == 4\n", encoding="utf-8")
    before = snapshot(project)
    app.backend = RealBackend()
    app.state.choose_local_folder(str(project))
    app.begin_scan()
    deadline = time.monotonic() + 120
    while app.state.screen == Screen.SCANNING and time.monotonic() < deadline:
        pump(app.root, 0.05)
    result = app.state.scan_result
    assert result is not None and not result.failed
    assert len(result.findings) >= 300
    capture(app, "verified-results.png")
    screen = app.screens[Screen.RESULTS]
    click(screen, "Repair details")
    pump(app.root)
    click(app.screens[Screen.REPAIR_DETAILS], "Copy for repair")
    assert "ruff" in app.root.clipboard_get()
    app.back_to_results()
    pump(app.root)
    click(screen, "Save report")
    pump(app.root)
    destination = tmp_path / "real-report.md"
    threading.Thread(target=inspect, args=(destination,), daemon=True).start()
    click(app.screens[Screen.SAVE_REPORT], "Save report")
    saved = destination.read_text(encoding="utf-8")
    assert result.findings[-1].finding_id in saved
    app.close_save_report()
    pump(app.root)
    eligible = next(i for i, finding in enumerate(result.findings) if finding.runtime_check_available)
    screen._page = eligible // PAGE_SIZE
    screen._show_page()
    pump(app.root)
    click(screen, "Request run approval")
    pump(app.root)
    assert app.state.pending_approval.command_display == "pytest -q"
    click(app.screens[Screen.RUN_APPROVAL], "Approve and run")
    deadline = time.monotonic() + 180
    while app._run_busy and time.monotonic() < deadline:
        pump(app.root, 0.05)
    assert not app._run_busy
    run = app.state.last_run_result
    assert run.exit_code == 0, run
    assert "1 passed" in run.stdout
    text = next(w for w in widgets(app._run_window) if isinstance(w, ctk.CTkTextbox)).get("1.0", "end")
    assert "1 passed" in text and "STDERR" in text
    assert snapshot(project) == before
    workspace = app.backend._workspace_root
    app.back_to_start()
    assert not workspace.exists()
    print(f"Real scan: {len(result.findings)} findings; report {len(saved)} chars; Docker: {run.stdout.strip()}")


def test_real_github_review_session_cleanup(app):
    from inspector_app.backend import RealBackend
    app.backend = RealBackend()
    app.state.choose_github_url("https://github.com/octocat/Hello-World")
    app.begin_scan()
    deadline = time.monotonic() + 120
    while app.state.screen == Screen.SCANNING and time.monotonic() < deadline:
        pump(app.root, 0.05)
    assert app.state.screen == Screen.RESULTS
    clone = app.backend._current_root_path
    workspace = app.backend._workspace_root
    assert clone.exists()
    click(app.screens[Screen.RESULTS], "Scan something else")
    assert not clone.exists() and not workspace.exists()
    print("Live public GitHub clone removed when leaving review session")
