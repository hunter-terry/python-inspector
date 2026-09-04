from __future__ import annotations

import customtkinter as ctk

from ..models import SourceKind
from . import theme


class ProjectReviewScreen(ctk.CTkFrame):
    """Screen 2: confirm what will be inspected before anything happens."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

        ctk.CTkLabel(self, text="Review before scanning", font=theme.FONT_TITLE).pack(pady=(50, 6))

        self.source_card = ctk.CTkFrame(self, corner_radius=12)
        self.source_card.pack(pady=10, padx=80, fill="x")

        self.kind_label = ctk.CTkLabel(self.source_card, text="", font=theme.FONT_SECTION)
        self.kind_label.pack(anchor="w", padx=20, pady=(16, 2))
        self.path_label = ctk.CTkLabel(
            self.source_card, text="", font=theme.FONT_MONO, wraplength=760, justify="left"
        )
        self.path_label.pack(anchor="w", padx=20, pady=(0, 16))

        ctk.CTkLabel(
            self,
            text=(
                "This scan is read-only. Python Inspector does not copy your project files\n"
                "into permanent storage, upload them anywhere, or change any source file."
            ),
            font=theme.FONT_BODY, justify="center",
        ).pack(pady=18)

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=20)
        ctk.CTkButton(
            button_row, text="Back", fg_color="transparent", border_width=2, width=140,
            command=self.controller.back_to_start,
        ).grid(row=0, column=0, padx=10)
        ctk.CTkButton(
            button_row, text="Start read-only scan", width=200, height=42,
            command=self.controller.begin_scan,
        ).grid(row=0, column=1, padx=10)

    def refresh(self) -> None:
        state = self.controller.state
        if state.source_kind is SourceKind.LOCAL_FOLDER:
            self.kind_label.configure(text="Local folder")
        else:
            self.kind_label.configure(text="Public GitHub repository")
        self.path_label.configure(text=state.source_label or "")
