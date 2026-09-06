from __future__ import annotations

import customtkinter as ctk

from ..models import REPAIR_REVIEW_GUIDANCE
from . import theme


class RepairDetailsScreen(ctk.CTkFrame):
    """Screen 5: exact file/line, evidence, suggested fix, verification steps."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        self._clipboard_text = ""

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=30, pady=(24, 10))
        ctk.CTkButton(
            header, text="< Back to results", fg_color="transparent", border_width=2, width=160,
            command=self.controller.back_to_results,
        ).pack(side="left")
        self.copy_button = ctk.CTkButton(header, text="Copy for repair", width=150, command=self._copy_to_clipboard)
        self.copy_button.pack(
            side="right"
        )

        self.title_label = ctk.CTkLabel(self, text="", font=theme.FONT_TITLE, anchor="w", justify="left")
        self.title_label.pack(anchor="w", padx=30)
        self.location_label = ctk.CTkLabel(self, text="", font=theme.FONT_MONO, anchor="w")
        self.location_label.pack(anchor="w", padx=30, pady=(4, 16))

        self.text = ctk.CTkTextbox(self, font=theme.FONT_MONO, wrap="word")
        self.text.pack(fill="both", expand=True, padx=30, pady=(0, 24))
        self.text.configure(state="disabled")

    def refresh(self) -> None:
        finding = self.controller.state.selected_finding
        if finding is None:
            return
        self.copy_button.configure(text="Copy for repair")
        self.title_label.configure(text=f"{finding.finding_id} — {finding.category}")
        location_text = (
            f"{finding.file_path or 'n/a'}:{finding.line_number or '?'}  "
            f"({finding.severity.value}, {finding.confidence.value} confidence, {finding.status.value})"
        )
        self.location_label.configure(text=location_text)

        body_lines = [
            "Finding:", "  " + finding.summary, "",
            "What could happen:", "  " + finding.what_could_happen, "",
            "Evidence:", "  " + finding.evidence, "",
            "Suggested repair:", "  " + finding.suggested_repair, "",
            "Verification steps:",
        ]
        for i, step in enumerate(finding.verification_steps, start=1):
            body_lines.append(f"  {i}. {step}")
        body_lines += ["", f"Scanner: {finding.scanner_name} {finding.scanner_version}", "",
                       "Repair review instructions:",
                       *REPAIR_REVIEW_GUIDANCE,
                       self.controller.state.scan_result.GUARANTEE_DISCLAIMER]

        header_lines = [f"{finding.finding_id} — {finding.category}", location_text, ""]
        self._clipboard_text = "\n".join(header_lines + body_lines)

        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(body_lines))
        self.text.configure(state="disabled")

    def _copy_to_clipboard(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._clipboard_text)
        self.copy_button.configure(text="Copied")
