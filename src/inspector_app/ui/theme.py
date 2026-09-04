"""Shared visual constants so every screen looks like one product."""
import customtkinter as ctk

APP_TITLE = "Python Inspector (V1)"
WINDOW_SIZE = "1000x680"

SEVERITY_COLORS = {
    "Critical": "#c0392b",
    "High": "#e67e22",
    "Medium": "#d4ac0d",
    "Low": "#2e86c1",
    "Info": "#7f8c8d",
}

FONT_TITLE = ("Segoe UI", 22, "bold")
FONT_SUBTITLE = ("Segoe UI", 14)
FONT_SECTION = ("Segoe UI", 16, "bold")
FONT_BODY = ("Segoe UI", 13)
FONT_MONO = ("Consolas", 12)


def configure_appearance() -> None:
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
