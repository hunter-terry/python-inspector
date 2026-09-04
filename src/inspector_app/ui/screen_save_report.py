from __future__ import annotations

import customtkinter as ctk

from . import theme


class SaveReportScreen(ctk.CTkFrame):
    """Screen 7: preview, then explicit Save report + destination picker."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(24, 10))
        ctk.CTkButton(
            header, text="< Back to results", fg_color="transparent", border_width=2, width=160,
            command=self.controller.close_save_report,
        ).pack(side="left")
        ctk.CTkButton(header, text="Save report", width=160, command=self.controller.save_report_to_disk).pack(
            side="right"
        )

        ctk.CTkLabel(
            self, text="Preview — nothing is saved until you press Save report", font=theme.FONT_SUBTITLE
        ).pack(anchor="w", padx=30)

        self.status_label = ctk.CTkLabel(self, text="", font=theme.FONT_BODY, text_color="#27ae60")
        self.status_label.pack(anchor="w", padx=30, pady=(2, 8))

        self.text = ctk.CTkTextbox(self, font=theme.FONT_MONO, wrap="word")
        self.text.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        self.text.configure(state="disabled")

    def refresh(self) -> None:
        state = self.controller.state
        report = state.report
        if report is None:
            return
        content = report.hunter_summary_markdown + "\n\n---\n\n" + report.technical_packet_markdown
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.configure(state="disabled")

        if state.report_saved_to:
            self.status_label.configure(text=f"Saved to {state.report_saved_to}")
        else:
            self.status_label.configure(text="Not saved yet.")
