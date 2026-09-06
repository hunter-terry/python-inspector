from __future__ import annotations

import customtkinter as ctk

from ..models import CheckOutcome, FindingStatus
from . import theme

# Bound both native window resources and layout cost, regardless of scan size.
PAGE_SIZE = 10


class ResultsScreen(ctk.CTkFrame):
    """Screen 4: plain-English summary + severity, distinguishing confirmed vs possible."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller
        self._result = None
        self._page = 0

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

        self.coverage_label = ctk.CTkLabel(self, text="", font=theme.FONT_BODY, anchor="w",
                                          justify="left", wraplength=760)
        self.coverage_label.pack(fill="x", padx=30)
        self.run_button = ctk.CTkButton(
            self, text="View last run output", command=self.controller.show_last_run_result,
        )

        pager = ctk.CTkFrame(self, fg_color="transparent")
        pager.pack(fill="x", padx=30, pady=(8, 0))
        self.previous_button = ctk.CTkButton(pager, text="Previous", width=100,
                                           command=lambda: self._change_page(-1))
        self.previous_button.pack(side="left")
        self.page_label = ctk.CTkLabel(pager, text="", font=theme.FONT_BODY)
        self.page_label.pack(side="left", padx=14)
        self.next_button = ctk.CTkButton(pager, text="Next", width=100,
                                       command=lambda: self._change_page(1))
        self.next_button.pack(side="left")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True, padx=20, pady=10)

        self.disclaimer = ctk.CTkLabel(self, text="", font=theme.FONT_BODY, text_color="#7f8c8d", wraplength=900)
        self.disclaimer.pack(padx=30, pady=(0, 14), anchor="w")

    def refresh(self) -> None:
        state = self.controller.state
        result = state.scan_result
        if state.last_run_result is not None:
            self.run_button.pack(after=self.coverage_label, anchor="w", padx=30, pady=6)
        else:
            self.run_button.pack_forget()
        if result is self._result:
            return  # Returning from details/report must not recreate native widgets.
        self._result = result
        self._page = 0
        self._show_page()
        if result is None:
            return

        self.disclaimer.configure(text=result.GUARANTEE_DISCLAIMER)

        incomplete = [r for r in result.scanners_run if r.outcome != CheckOutcome.RAN]
        self.coverage_label.configure(text=(
            "Incomplete coverage: " + "; ".join(f"{r.scanner_name}: {r.outcome.value}" for r in incomplete)
            if incomplete else "Checks completed. Review evidence before applying a repair."
        ))
        if result.is_empty:
            self.summary_label.configure(text=f"No findings for {result.source_label}.")
            ctk.CTkLabel(
                self.scroll,
                text="No findings from the checks that ran. Review check coverage in Save report.",
                font=theme.FONT_BODY,
            ).pack(pady=40)
            return

        counts = {status: sum(f.status == status for f in result.findings) for status in FindingStatus}
        self.summary_label.configure(
            text=(f"{len(result.findings)} findings — "
                  f"{counts[FindingStatus.CONFIRMED_FAILURE]} confirmed failures, "
                  f"{counts[FindingStatus.STRONG_FINDING]} strong, "
                  f"{counts[FindingStatus.POSSIBLE_FINDING]} possible, "
                  f"{counts[FindingStatus.INFORMATIONAL]} informational")
        )

    def _change_page(self, direction: int) -> None:
        if self._result is None:
            return
        last = max(0, (len(self._result.findings) - 1) // PAGE_SIZE)
        self._page = max(0, min(last, self._page + direction))
        self._show_page()

    def _show_page(self) -> None:
        for child in self.scroll.winfo_children():
            child.destroy()
        findings = self._result.findings if self._result else ()
        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(findings))
        self.page_label.configure(text=f"{start + 1 if findings else 0}–{end} of {len(findings)} findings")
        self.previous_button.configure(state="normal" if self._page else "disabled")
        self.next_button.configure(state="normal" if end < len(findings) else "disabled")
        for finding in findings[start:end]:
            self._build_row(finding)
        self.scroll._parent_canvas.yview_moveto(0)

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
