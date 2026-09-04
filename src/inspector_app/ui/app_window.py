"""Controller: owns AppState + backend, wires the background scan thread to
the UI thread, and switches between screen frames. Screens never talk to
the backend or the state machine directly -- only through this controller.
"""
from __future__ import annotations

import queue
import threading
from datetime import datetime, timezone
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..contract import InspectorBackend
from ..mock_data import MockBackend
from ..models import ScanResult, SourceKind
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
        self._progress_queue: "queue.Queue[tuple]" = queue.Queue()
        self._cancel_flag = threading.Event()
        self._scan_thread: threading.Thread | None = None

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
        for frame in self.screens.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self.render()

    # -- rendering ---------------------------------------------------------
    def render(self) -> None:
        frame = self.screens[self.state.screen]
        frame.refresh()
        frame.tkraise()

    # -- Start screen --------------------------------------------------------
    def pick_local_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a Python project folder")
        if not path:
            return
        self.state.choose_local_folder(path)
        self.render()

    def submit_github_url(self, url: str) -> None:
        url = url.strip()
        if not url:
            messagebox.showwarning(theme.APP_TITLE, "Enter a GitHub URL first.")
            return
        if not (url.startswith("https://github.com/") or url.startswith("http://github.com/")):
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
        self.state.back_to_start()
        self.render()

    def begin_scan(self) -> None:
        self.state.begin_scan()
        self._cancel_flag.clear()
        self.render()

        source_kind = self.state.source_kind
        source_label = self.state.source_label

        def on_progress(label: str, fraction: float) -> None:
            self._progress_queue.put(("progress", label, fraction))

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
                self._progress_queue.put(("done", result))
            except Exception as exc:  # a backend crash must not take the UI down with it
                self._progress_queue.put(("error", str(exc)))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()
        self.root.after(50, self._poll_scan_queue)

    def _poll_scan_queue(self) -> None:
        try:
            while True:
                item = self._progress_queue.get_nowait()
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
            self.root.after(50, self._poll_scan_queue)

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
        self.state.cancel_run_approval()
        self.render()

    def approve_and_run(self) -> None:
        request = self.state.pending_approval
        assert request is not None
        result = self.backend.run_approved_check(request)
        self.state.record_run_result(result)
        self.render()
        messagebox.showinfo(
            theme.APP_TITLE,
            f"Finished.\nExit code: {result.exit_code}\n\n{result.stdout or result.stderr}",
        )

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
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        self.state.report_saved(path)
        self.render()
        messagebox.showinfo(theme.APP_TITLE, f"Report saved to:\n{path}")


def launch() -> None:
    from ..backend import RealBackend

    theme.configure_appearance()
    root = ctk.CTk()
    root.title(theme.APP_TITLE)
    root.geometry(theme.WINDOW_SIZE)
    root.minsize(860, 560)
    AppController(root, backend=RealBackend())
    root.mainloop()
