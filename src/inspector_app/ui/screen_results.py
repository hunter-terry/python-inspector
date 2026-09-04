from __future__ import annotations

import customtkinter as ctk

from ..models import FindingStatus
from . import theme

CONFIRMED_STATUSES = {FindingStatus.CONFIRMED_FAILURE, FindingStatus.STRONG_FINDING}


class ResultsScreen(ctk.CTkFrame):
    """Screen 4: plain-English summary + severity, distinguishing confirmed vs possible."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

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

        for finding in result.findings:
            self._build_row(finding)

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
