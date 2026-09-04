from __future__ import annotations

import customtkinter as ctk

from ..state import ScanPhase
from . import theme


class ScanningScreen(ctk.CTkFrame):
    """Screen 3: progress + current check, with cancel/failed/cancelled states."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

        self.title_label = ctk.CTkLabel(self, text="Scanning", font=theme.FONT_TITLE)
        self.title_label.pack(pady=(70, 10))

        self.status_label = ctk.CTkLabel(self, text="", font=theme.FONT_SUBTITLE)
        self.status_label.pack(pady=(0, 20))

        self.progress_bar = ctk.CTkProgressBar(self, width=480)
        self.progress_bar.pack(pady=10)

        self.action_row = ctk.CTkFrame(self, fg_color="transparent")
        self.action_row.pack(pady=30)

        self.cancel_button = ctk.CTkButton(
            self.action_row, text="Cancel", fg_color="#c0392b", command=self.controller.cancel_scan
        )
        self.retry_button = ctk.CTkButton(
            self.action_row, text="Try again", command=self.controller.retry_scan
        )
        self.back_button = ctk.CTkButton(
            self.action_row, text="Back to start", fg_color="transparent", border_width=2,
            command=self.controller.back_to_start,
        )

    def refresh(self) -> None:
        state = self.controller.state
        for w in self.action_row.winfo_children():
            w.grid_forget()

        if state.scan_phase == ScanPhase.RUNNING:
            self.title_label.configure(text="Scanning (read-only)")
            self.status_label.configure(text=state.scan_progress_label)
            self.progress_bar.pack(pady=10)
            self.progress_bar.set(state.scan_progress_fraction)
            self.cancel_button.grid(row=0, column=0, padx=10)
        elif state.scan_phase == ScanPhase.CANCELLED:
            self.title_label.configure(text="Scan cancelled")
            self.status_label.configure(text="No findings were kept. Nothing on disk was changed.")
            self.progress_bar.pack_forget()
            self.retry_button.grid(row=0, column=0, padx=10)
            self.back_button.grid(row=0, column=1, padx=10)
        elif state.scan_phase == ScanPhase.FAILED:
            self.title_label.configure(text="Scan failed")
            self.status_label.configure(text=state.scan_failure_reason or "An unknown error occurred.")
            self.progress_bar.pack_forget()
            self.retry_button.grid(row=0, column=0, padx=10)
            self.back_button.grid(row=0, column=1, padx=10)
        else:
            self.title_label.configure(text="Scanning")
            self.status_label.configure(text="")
