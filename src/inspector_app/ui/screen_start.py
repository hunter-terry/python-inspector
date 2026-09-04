from __future__ import annotations

import customtkinter as ctk

from . import theme


class StartScreen(ctk.CTkFrame):
    """Screen 1: choose a local folder or paste a GitHub link."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

        ctk.CTkLabel(self, text="Python Inspector", font=theme.FONT_TITLE).pack(pady=(60, 4))
        ctk.CTkLabel(
            self,
            text=(
                "Find likely bugs and vulnerabilities in a Python project, then hand the\n"
                "report to yourself or an AI to fix. No AI runs inside this program."
            ),
            font=theme.FONT_SUBTITLE,
            justify="center",
        ).pack(pady=(0, 30))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack()

        ctk.CTkButton(
            button_row, text="Choose a project folder", width=230, height=44,
            command=self.controller.pick_local_folder,
        ).grid(row=0, column=0, padx=12)

        ctk.CTkButton(
            button_row, text="Paste a GitHub link", width=230, height=44,
            fg_color="transparent", border_width=2,
            command=self._show_github_entry,
        ).grid(row=0, column=1, padx=12)

        self.github_row = ctk.CTkFrame(self, fg_color="transparent")
        self.github_entry = ctk.CTkEntry(
            self.github_row, width=380, placeholder_text="https://github.com/owner/repo"
        )
        self.github_entry.grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(self.github_row, text="Continue", width=100, command=self._submit_github).grid(
            row=0, column=1
        )

        ctk.CTkLabel(
            self,
            text="The first scan is always read-only. Nothing runs until you explicitly approve it.",
            font=theme.FONT_BODY, text_color="#2e86c1",
        ).pack(pady=(36, 0))

    def _show_github_entry(self) -> None:
        self.github_row.pack(pady=(24, 0))
        self.github_entry.focus_set()

    def _submit_github(self) -> None:
        self.controller.submit_github_url(self.github_entry.get())

    def refresh(self) -> None:
        self.github_row.pack_forget()
        self.github_entry.delete(0, "end")
