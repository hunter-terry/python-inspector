from __future__ import annotations

import customtkinter as ctk

from ..models import FindingStatus
from . import theme

CONFIRMED_STATUSES = {FindingStatus.CONFIRMED_FAILURE, FindingStatus.STRONG_FINDING}

# Building one card is several widget constructions; doing all ~hundreds of
# them in one synchronous call is what made the app report "Not Responding"
# for large scans. Building a small batch per `after()` tick instead keeps
# yielding control back to the Tk event loop so Windows never sees the app
# go unresponsive, at the cost of the list filling in over a second or two
# instead of appearing all at once.
_ROWS_PER_BATCH = 5


class ResultsScreen(ctk.CTkFrame):
    """Screen 4: plain-English summary + severity, distinguishing confirmed vs possible."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        self._build_token = 0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(24, 10))
        ctk.CTkLabel(header, text="Results", font=theme.FONT_TITLE).pack(side="left")
        ctk.CTkButton(header, text="Save report", width=150, command=self.controller.open_save_report).pack(
            side="right"
        )
        ctk.CTkButton(
            header, text="Scan something else", fg_color="transparent", border_width=2, width=170,
            command=self.controller.back_to_start,
        ).pack(side="right", padx=10)

        self.summary_label = ctk.CTkLabel(self, text="", font=theme.FONT_SUBTITLE, justify="left")
        self.summary_label.pack(anchor="w", padx=30)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=10)

        self.disclaimer = ctk.CTkLabel(self, text="", font=theme.FONT_BODY, text_color="#7f8c8d", wraplength=900)
        self.disclaimer.pack(padx=30, pady=(0, 14), anchor="w")

    def refresh(self) -> None:
        # Invalidate any still-running incremental build from a previous
        # refresh (e.g. the user navigated away and back before it finished).
        self._build_token += 1
        token = self._build_token

        for child in self.scroll.winfo_children():
            child.destroy()

        state = self.controller.state
        result = state.scan_result
        if result is None:
            return

        self.disclaimer.configure(text=result.GUARANTEE_DISCLAIMER)

        if result.is_empty:
            self.summary_label.configure(text=f"No findings for {result.source_label}.")
            ctk.CTkLabel(
                self.scroll,
                text="Nothing to review — no likely bugs or vulnerabilities were found.",
                font=theme.FONT_BODY,
            ).pack(pady=40)
            return

        confirmed = sum(1 for f in result.findings if f.status in CONFIRMED_STATUSES)
        possible = len(result.findings) - confirmed
        self.summary_label.configure(
            text=f"{result.source_label}  —  {confirmed} confirmed, {possible} possible"
        )

        self._build_rows_incrementally(result.findings, 0, token)

    def _build_rows_incrementally(self, findings, start_index: int, token: int) -> None:
        if token != self._build_token:
            return  # superseded by a newer refresh() -- stop building
        end_index = min(start_index + _ROWS_PER_BATCH, len(findings))
        for finding in findings[start_index:end_index]:
            self._build_row(finding)
        if end_index < len(findings):
            self.after(1, self._build_rows_incrementally, findings, end_index, token)

    def _build_row(self, finding) -> None:
        card = ctk.CTkFrame(self.scroll, corner_radius=10)
        card.pack(fill="x", pady=6, padx=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))

        color = theme.SEVERITY_COLORS.get(finding.severity.value, "#7f8c8d")
        ctk.CTkLabel(
            top, text=finding.severity.value, font=("Segoe UI", 12, "bold"),
            text_color="white", fg_color=color, corner_radius=6, width=70,
        ).pack(side="left")
        ctk.CTkLabel(top, text=finding.status.value, font=theme.FONT_BODY, text_color="#7f8c8d").pack(
            side="left", padx=10
        )
        ctk.CTkLabel(top, text=finding.category, font=("Segoe UI", 13, "bold")).pack(side="left", padx=10)

        ctk.CTkLabel(
            card, text=finding.summary, font=theme.FONT_BODY, wraplength=820, justify="left", anchor="w"
        ).pack(fill="x", padx=16, pady=(0, 2))
        ctk.CTkLabel(
            card, text=f"What could happen: {finding.what_could_happen}", font=theme.FONT_BODY,
            text_color="#7f8c8d", wraplength=820, justify="left", anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 10))

        button_row = ctk.CTkFrame(card, fg_color="transparent")
        button_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            button_row, text="Repair details", width=150,
            command=lambda fid=finding.finding_id: self.controller.open_repair_details(fid),
        ).pack(side="left")
        if finding.runtime_check_available:
            ctk.CTkButton(
                button_row, text="Request run approval", width=190, fg_color="transparent", border_width=2,
                command=lambda fid=finding.finding_id: self.controller.request_run_approval(fid),
            ).pack(side="left", padx=10)
