from __future__ import annotations

import customtkinter as ctk

from . import theme


class RunApprovalScreen(ctk.CTkFrame):
    """Screen 6: exact command, why, safety boundary, risk. No preselected approval."""

    def __init__(self, master, controller):
        super().__init__(master, fg_color="transparent")
        self.controller = controller

        ctk.CTkLabel(self, text="Approve runtime check?", font=theme.FONT_TITLE).pack(pady=(50, 4))
        ctk.CTkLabel(
            self, text="Nothing runs until you press Approve and run.",
            font=theme.FONT_SUBTITLE, text_color="#c0392b",
        ).pack(pady=(0, 20))

        card = ctk.CTkFrame(self, corner_radius=12)
        card.pack(padx=100, fill="x")

        self.command_label = ctk.CTkLabel(
            card, text="", font=theme.FONT_MONO, wraplength=760, justify="left", anchor="w"
        )
        self.command_label.pack(fill="x", padx=20, pady=(18, 10))

        self.purpose_label = self._field(card, "Why this is useful")
        self.boundary_label = self._field(card, "Safety boundary")
        self.risk_label = self._field(card, "Possible risk")

        self.status_label = ctk.CTkLabel(self, text="", font=theme.FONT_BODY, text_color="#7f8c8d")
        self.status_label.pack(pady=(0, 4))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=30)
        # Neither button is given keyboard focus on entry, so neither action is preselected.
        self.cancel_button = ctk.CTkButton(
            button_row, text="Cancel", fg_color="transparent", border_width=2, width=160,
            command=self.controller.cancel_run_approval,
        )
        self.cancel_button.grid(row=0, column=0, padx=12)
        self.approve_button = ctk.CTkButton(
            button_row, text="Approve and run", fg_color="#27ae60", width=200, height=42,
            command=self.controller.approve_and_run,
        )
        self.approve_button.grid(row=0, column=1, padx=12)

    def _field(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=20)
        value_label = ctk.CTkLabel(parent, text="", font=theme.FONT_BODY, wraplength=760, justify="left", anchor="w")
        value_label.pack(anchor="w", padx=20, pady=(0, 14))
        return value_label

    def refresh(self) -> None:
        request = self.controller.state.pending_approval
        if request is None:
            return
        self.command_label.configure(text=f"$ {request.command_display}")
        self.purpose_label.configure(text=request.purpose)
        self.boundary_label.configure(text=request.safety_boundary)
        self.risk_label.configure(text=request.possible_risk)
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        self.approve_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="disabled" if busy else "normal")
        self.status_label.configure(
            text="Running the approved check... this can take up to two minutes." if busy else ""
        )
