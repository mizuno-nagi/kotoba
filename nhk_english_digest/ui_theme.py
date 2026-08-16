"""Central design system for the Japanese news study desktop app."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk


BG = "#F6F5F2"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F1EEE9"
TEXT = "#2B2925"
MUTED = "#7D786F"
BORDER = "#E6E1D8"
ACCENT = "#C05B45"
ACCENT_HOVER = "#A94A37"
ACCENT_SOFT = "#F4E3DC"
SUCCESS = "#5E7D64"
WARNING = "#A67B3F"
DANGER = "#9A4B48"
LINK = "#4E6E7A"

RADIUS_PAGE = 18
RADIUS_CARD = 16
RADIUS_CONTROL = 12
RADIUS_DIALOG = 20
RADIUS_PILL = 999

SPACE_XS = 8
SPACE_SM = 16
SPACE_MD = 24
SPACE_LG = 32
SPACE_XL = 40
SPACE_2XL = 48
SPACE_3XL = 64

FONT_CANDIDATES = (
    "Noto Sans SC",
    "Source Han Sans SC",
    "Microsoft YaHei UI",
    "Segoe UI",
)

_FONT_FAMILY = "Microsoft YaHei UI"


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=_FONT_FAMILY, size=size, weight=weight)


def init_theme(root: tk.Misc | None = None) -> None:
    """Apply the light appearance and pick the first available font family."""
    global _FONT_FAMILY
    ctk.set_appearance_mode("light")

    if root is not None:
        try:
            available = {name.lower() for name in tkfont.families(root)}
        except Exception:
            available = set()
        for candidate in FONT_CANDIDATES:
            if candidate.lower() in available:
                _FONT_FAMILY = candidate
                break


def font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return _font(size, weight)


def title_font() -> ctk.CTkFont:
    return _font(24, "bold")


def hero_font() -> ctk.CTkFont:
    return _font(28, "bold")


def section_font() -> ctk.CTkFont:
    return _font(15, "bold")


def body_font() -> ctk.CTkFont:
    return _font(13, "normal")


def small_font() -> ctk.CTkFont:
    return _font(12, "normal")


def caption_font() -> ctk.CTkFont:
    return _font(11, "normal")


def card_title_font() -> ctk.CTkFont:
    return _font(14, "bold")
