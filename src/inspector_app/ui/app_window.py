"""Controller: owns AppState + backend, wires the background scan thread to
the UI thread, and switches between screen frames. Screens never talk to
the backend or the state machine directly -- only through this controller.
"""
from __future__ import annotations

import os
import queue
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..contract import InspectorBackend
from ..mock_data import MockBackend
from ..models import ApprovalDecision, RunResult, ScanResult, SourceKind
from ..state import AppState, ScanPhase, Screen
from . import theme
from .screen_project_review import ProjectReviewScreen
from .screen_repair_details import RepairDetailsScreen
from .screen_results import ResultsScreen
from .screen_run_approval import RunApprovalScreen
from .screen_save_report import SaveReportScreen
from .screen_scanning import ScanningScreen
from .screen_start import StartScreen


class AppController:
    def __init__(self, root: ctk.CTk, backend: InspectorBackend | None = None) -> None:
        self.root = root
        self.state = AppState()
        self.backend: InspectorBackend = backend or MockBackend()
        self._progress_queue: queue.Queue[tuple] = queue.Queue()
        self._cancel_flag = threading.Event()
        self._scan_thread: threading.Thread | None = None
        self._run_thread: threading.Thread | None = None
        self._run_busy = False
        self._run_window = None
        self._last_run_command = ""
        self._closing = False

        self.container = ctk.CTkFrame(root, fg_color="transparent")
        self.container.pack(fill="both", expand=True)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        self.screens: dict[Screen, ctk.CTkFrame] = {
            Screen.START: StartScreen(self.container, self),
            Screen.PROJECT_REVIEW: ProjectReviewScreen(self.container, self),
            Screen.SCANNING: ScanningScreen(self.container, self),
            Screen.RESULTS: ResultsScreen(self.container, self),
            Screen.REPAIR_DETAILS: RepairDetailsScreen(self.container, self),
            Screen.RUN_APPROVAL: RunApprovalScreen(self.container, self),
            Screen.SAVE_REPORT: SaveReportScreen(self.container, self),
        }
        self._visible_frame = None
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Map>", self._on_window_mapped)
        self.render()

    def _on_window_mapped(self, _event) -> None:
        # On Windows, restoring this window from minimized sometimes leaves
        # already-drawn widgets showing stale pixels until something forces a
        # repaint (seen on the Results screen, but not limited to it). An
        # alpha nudge forces DWM to recompose the whole window without
        # touching size or maximized/normal state the way a geometry change
        # would.
        self.root.after(30, self._force_repaint)

    def _force_repaint(self) -> None:
        self.root.attributes("-alpha", 0.999)
        self.root.after(1, lambda: self.root.attributes("-alpha", 1.0))

    # -- rendering ---------------------------------------------------------
    def render(self) -> None:
        frame = self.screens[self.state.screen]
        if self._visible_frame is not frame:
            if self._visible_frame is not None:
                self._visible_frame.grid_remove()
            frame.grid(row=0, column=0, sticky="nsew")
            self._visible_frame = frame
        frame.refresh()
        frame.tkraise()

    def _end_session(self) -> None:
        cleanup = getattr(self.backend, "end_session", None)
        if cleanup is not None:
            cleanup()

    def close(self) -> None:
        self._closing = True
        self._cancel_flag.set()
        # Let the worker finish its container/clone cleanup before ending Python.
        if any(t is not None and t.is_alive() for t in (self._scan_thread, self._run_thread)):
            self.root.after(100, self.close)
            return
        self._end_session()
        self.root.destroy()

    # -- Start screen --------------------------------------------------------
    def pick_local_folder(self) -> None:
        path = filedialog.askdirectory(parent=self.root, title="Choose a Python project folder", mustexist=True)
        if not path:
            return
        self.state.choose_local_folder(path)
        self.render()

    def submit_github_url(self, url: str) -> None:
        url = url.strip()
        if not url:
            messagebox.showwarning(theme.APP_TITLE, "Enter a GitHub URL first.")
            return
        if not url.startswith(("https://github.com/", "http://github.com/")):
            messagebox.showwarning(
                theme.APP_TITLE,
                "That does not look like a GitHub URL. Expected something like "
                "https://github.com/owner/repo",
            )
            return
        self.state.choose_github_url(url)
        self.render()

    # -- Project review -----------------------------------------------------
    def back_to_start(self) -> None:
        if self._run_busy:
            return
        if self._scan_thread is not None and self._scan_thread.is_alive():
            self._cancel_flag.set()
        else:
            self._end_session()
        if self._run_window is not None and self._run_window.winfo_exists():
            self._run_window.destroy()
        self.state.back_to_start()
        self.screens[Screen.RESULTS].refresh()
        self.render()

    def begin_scan(self) -> None:
        if self._closing or self.state.screen != Screen.PROJECT_REVIEW:
            return
        if self._scan_thread is not None and self._scan_thread.is_alive():
            self.root.after(50, self.begin_scan)
            return
        self.state.begin_scan()
        self._cancel_flag.clear()
        self._progress_queue = queue.Queue()
        scan_queue = self._progress_queue
        self.render()

        source_kind = self.state.source_kind
        source_label = self.state.source_label

        def on_progress(label: str, fraction: float) -> None:
            scan_queue.put(("progress", label, fraction))

        def is_cancelled() -> bool:
            return self._cancel_flag.is_set()

        def worker() -> None:
            try:
                if source_kind is SourceKind.LOCAL_FOLDER:
                    result = self.backend.scan_local_project(
                        source_label, on_progress=on_progress, is_cancelled=is_cancelled
                    )
                else:
                    result = self.backend.scan_github_project(
                        source_label, on_progress=on_progress, is_cancelled=is_cancelled
                    )
                if is_cancelled():
                    self._end_session()
                scan_queue.put(("done", result))
            except Exception as exc:  # noqa: BLE001 -- deliver worker failure to the UI
                try:
                    self._end_session()
                finally:
                    scan_queue.put(("error", str(exc)))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()
        self.root.after(50, self._poll_scan_queue, scan_queue)

    def _poll_scan_queue(self, scan_queue=None) -> None:
        scan_queue = scan_queue if scan_queue is not None else self._progress_queue
        if scan_queue is not self._progress_queue or self._closing:
            return
        try:
            while True:
                item = scan_queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, label, fraction = item
                    self.state.report_progress(label, fraction)
                    self.render()
                elif kind == "done":
                    _, result = item
                    self.state.scan_completed(result)
                    self.render()
                    return
                elif kind == "error":
                    _, message = item
                    failed_result = ScanResult(
                        source_label=self.state.source_label or "",
                        source_kind=self.state.source_kind or SourceKind.LOCAL_FOLDER,
                        started_at=datetime.now(timezone.utc),
                        completed_at=None,
                        failed=True,
                        failure_reason=message,
                    )
                    self.state.scan_completed(failed_result)
                    self.render()
                    return
        except queue.Empty:
            pass
        if self.state.scan_phase == ScanPhase.RUNNING:
            self.root.after(50, self._poll_scan_queue, scan_queue)

    def cancel_scan(self) -> None:
        self._cancel_flag.set()
        self.state.cancel_scan()
        self.render()

    def retry_scan(self) -> None:
        self.state.retry_scan()
        self.render()

    # -- Results / repair details -------------------------------------------
    def open_repair_details(self, finding_id: str) -> None:
        self.state.open_repair_details(finding_id)
        self.render()

    def back_to_results(self) -> None:
        self.state.back_to_results()
        self.render()

    # -- Run approval ------------------------------------------------------------
    def request_run_approval(self, finding_id: str) -> None:
        assert self.state.scan_result is not None
        request = self.backend.build_approval_request(self.state.scan_result, finding_id)
        self.state.request_run_approval(request)
        self.render()

    def cancel_run_approval(self) -> None:
        if self._run_busy:
            return
        self.state.cancel_run_approval()
        self.render()

    def approve_and_run(self) -> None:
        if self._run_busy or self._closing:
            return
        request = self.state.pending_approval
        assert request is not None
        self._run_busy = True
        self._last_run_command = request.command_display
        self.screens[Screen.RUN_APPROVAL].set_busy(True)

        result_queue: queue.Queue = queue.Queue()

        def worker() -> None:
            started = time.monotonic()
            try:
                result = self.backend.run_approved_check(request, is_cancelled=self._cancel_flag.is_set)
            except Exception as exc:  # noqa: BLE001 -- never strand approval on a crashed worker
                result = RunResult(request.request_id, ApprovalDecision.APPROVED, None, "",
                                   f"Runtime check failed: {exc}", time.monotonic() - started)
            result_queue.put(result)

        self._run_thread = threading.Thread(target=worker, daemon=True)
        self._run_thread.start()
        self._poll_run_result_queue(result_queue)

    def _poll_run_result_queue(self, result_queue: queue.Queue) -> None:
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            self.root.after(50, self._poll_run_result_queue, result_queue)
            return
        self._run_busy = False
        if self._closing:
            return
        self.screens[Screen.RUN_APPROVAL].set_busy(False)
        self.state.record_run_result(result)
        self.render()
        self._show_run_result_window(result)

    def show_last_run_result(self) -> None:
        if self.state.last_run_result is not None:
            self._show_run_result_window(self.state.last_run_result)

    def _show_run_result_window(self, result) -> None:
        # A plain tkinter messagebox proved unreliable in manual testing on
        # this machine (no error, but no dialog ever appeared) -- a CTkToplevel
        # uses the same widget stack as the rest of the app and is also
        # non-modal, so Hunter can keep working while it's open.
        if self._run_window is not None and self._run_window.winfo_exists():
            self._run_window.destroy()
        window = self._run_window = ctk.CTkToplevel(self.root)
        window.transient(self.root)
        window.title(f"{theme.APP_TITLE} — run result")
        window.geometry("640x420")
        window.minsize(480, 320)

        if result.timed_out:
            status = "Timed out"
        elif result.exit_code == 0:
            status = "Passed"
        elif result.exit_code is not None:
            status = "Did not pass"
        else:
            status = "No completed result"
        ctk.CTkLabel(
            window,
            text=f"{status} — exit code: {result.exit_code if result.exit_code is not None else 'n/a'}",
            font=theme.FONT_SUBTITLE, anchor="w",
        ).pack(fill="x", padx=16, pady=(16, 8))

        text = ctk.CTkTextbox(window, font=theme.FONT_MONO, wrap="word")
        text.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        text.insert("1.0", self.format_run_output(result))
        text.configure(state="disabled")

        ctk.CTkButton(window, text="Close", command=window.destroy, width=120).pack(pady=(0, 16))
        window.lift()
        window.focus_force()

    def format_run_output(self, result) -> str:
        return (f"Command: {self._last_run_command}\nRequest: {result.request_id}\n"
                f"Duration: {result.duration_seconds:.2f} seconds\nTimed out: {result.timed_out}\n\n"
                "This runs the project's existing tests; a pass does not prove a finding is fixed.\n\n"
                f"STDOUT\n{result.stdout or '(no stdout captured)'}\n\n"
                f"STDERR\n{result.stderr or '(no stderr captured)'}")

    # -- Save report -------------------------------------------------------------
    def open_save_report(self) -> None:
        assert self.state.scan_result is not None
        report = self.backend.render_report(self.state.scan_result)
        self.state.open_save_report(report)
        self.render()

    def close_save_report(self) -> None:
        self.state.close_save_report()
        self.render()

    def save_report_to_disk(self) -> None:
        assert self.state.report is not None
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save report",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return  # user cancelled; nothing is written
        content = (
            self.state.report.hunter_summary_markdown
            + "\n\n---\n\n"
            + self.state.report.technical_packet_markdown
        )
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as exc:
            self.screens[Screen.SAVE_REPORT].set_status(f"Could not save report: {exc}", is_error=True)
            return
        self.state.report_saved(path)
        self.render()


def _install_exception_logger(root: ctk.CTk) -> None:
    """Tkinter callback exceptions are printed to stderr by default, which is
    lost when the app is launched without an attached console. Log them to
    a file instead so a silent failure always leaves evidence.
    """
    log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PythonInspector"
    log_path = log_dir / "errors.log"

    def _log_callback_exception(exc_type, exc_value, exc_tb) -> None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n--- {datetime.now(timezone.utc).isoformat()} ---\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=fh)
        except OSError:
            pass  # logging must never itself crash the callback handler

    root.report_callback_exception = _log_callback_exception


def launch() -> None:
    from ..backend import RealBackend

    theme.configure_appearance()
    root = ctk.CTk()
    root.title(theme.APP_TITLE)
    root.geometry(theme.WINDOW_SIZE)
    root.minsize(860, 560)
    _install_exception_logger(root)
    AppController(root, backend=RealBackend())
    root.mainloop()
