"""Reusable CustomTkinter UI components for the reader app."""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from main import PERIOD_NAMES

from ui_theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    BG,
    BORDER,
    DANGER,
    MUTED,
    RADIUS_CARD,
    RADIUS_DIALOG,
    RADIUS_PILL,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    WARNING,
    body_font,
    caption_font,
    card_title_font,
    font,
    small_font,
)


CARD_WIDTH = 340
CARD_HEIGHT = 200


class Pill(ctk.CTkFrame):
    """Rounded capsule used for tags, statuses, and metadata."""

    def __init__(self, master, text: str, fg_color: str = SURFACE_ALT, text_color: str = TEXT, **kwargs):
        super().__init__(master, corner_radius=RADIUS_PILL, fg_color=fg_color, **kwargs)
        self.label = ctk.CTkLabel(
            self,
            text=text,
            text_color=text_color,
            font=kwargs.get("font") or caption_font(),
        )
        self.label.pack(padx=10, pady=3)

    def set_text(self, text: str):
        self.label.configure(text=text)


class PillNav(ctk.CTkFrame):
    """Pill-style category navigation with a callback for selection changes."""

    def __init__(self, master, options: list[tuple[str, str]], initial: str, command: Callable[[str], None]):
        super().__init__(master, fg_color="transparent")
        self.options = options
        self.command = command
        self.selected = initial
        self.buttons: dict[str, ctk.CTkButton] = {}

        for index, (value, label) in enumerate(options):
            button = ctk.CTkButton(
                self,
                text=label,
                command=lambda v=value: self.select(v),
                corner_radius=RADIUS_PILL,
                height=36,
                width=80,
                fg_color="transparent",
                hover_color=ACCENT_SOFT,
                text_color=TEXT,
                font=small_font(),
                border_width=0,
            )
            button.grid(row=0, column=index, padx=(0, 8), pady=4)
            self.buttons[value] = button
        self.select(initial, notify=False)

    def select(self, value: str, notify: bool = True):
        self.selected = value
        for key, button in self.buttons.items():
            if key == value:
                button.configure(fg_color=ACCENT_SOFT, text_color=ACCENT, hover_color=ACCENT_SOFT)
            else:
                button.configure(fg_color="transparent", text_color=MUTED, hover_color=SURFACE_ALT)
        if notify and self.command:
            self.command(value)


class ArticleCard(ctk.CTkFrame):
    """A modern reading card that preserves the existing callback interface."""

    def __init__(self, master, article, on_open, on_delete, on_rebuild=None):
        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
        )
        self.grid_propagate(False)
        self.article = article
        self.on_open = on_open
        self.on_delete = on_delete
        self.on_rebuild = on_rebuild

        self.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(self, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        top_row.grid_columnconfigure(0, weight=1)

        meta = ctk.CTkFrame(top_row, fg_color="transparent")
        meta.grid(row=0, column=0, sticky="w")
        self._add_meta_pills(meta)

        actions = ctk.CTkFrame(top_row, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.rebuild_button = ctk.CTkButton(
            actions,
            text="重新抓取",
            width=72,
            height=26,
            corner_radius=RADIUS_PILL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=caption_font(),
            command=lambda: self.on_rebuild(self.article) if self.on_rebuild else None,
        )
        self.rebuild_button.pack(side="left", padx=(0, 6))
        self.delete_button = ctk.CTkButton(
            actions,
            text="删除",
            width=48,
            height=26,
            corner_radius=RADIUS_PILL,
            fg_color="transparent",
            hover_color="#F7E1DC",
            text_color=DANGER,
            font=caption_font(),
            command=lambda: self.on_delete(self.article),
        )
        self.delete_button.pack(side="left")

        self.title_label = ctk.CTkLabel(
            self,
            text=article["title"],
            text_color=TEXT,
            font=card_title_font(),
            justify="left",
            anchor="w",
            wraplength=CARD_WIDTH - 28,
        )
        self.title_label.grid(row=1, column=0, sticky="ew", padx=14)

        self.summary_label = ctk.CTkLabel(
            self,
            text=article.get("summary", ""),
            text_color=MUTED,
            font=small_font(),
            justify="left",
            anchor="nw",
            wraplength=CARD_WIDTH - 28,
            height=44,
        )
        self.summary_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(6, 0))

        self.tag_row = ctk.CTkFrame(self, fg_color="transparent")
        self.tag_row.grid(row=3, column=0, sticky="w", padx=14, pady=(8, 12))
        self._add_tags()

        self._wire_events()

    def _add_meta_pills(self, parent: ctk.CTkFrame):
        article = self.article
        date_pill = Pill(parent, article["date"], fg_color=ACCENT_SOFT, text_color=ACCENT)
        date_pill.pack(side="left")

        source_name = article.get("source_name") or "来源"
        source_pill = Pill(parent, source_name, fg_color=SURFACE_ALT, text_color=MUTED)
        source_pill.pack(side="left", padx=(6, 0))

        period = article.get("period", "")
        if period and period != "custom":
            period_name = PERIOD_NAMES.get(period, period)
            Pill(parent, period_name, fg_color=SURFACE_ALT, text_color=MUTED).pack(side="left", padx=(6, 0))

    def _add_tags(self):
        tags = self.article.get("tags") or []
        if self.article.get("status") == "error":
            Pill(self.tag_row, "生成失败", fg_color="#F7E1DC", text_color=DANGER).pack(side="left", padx=(0, 6))
        for tag in tags[:4]:
            fg_color, text_color = _tag_colors(tag)
            Pill(self.tag_row, tag, fg_color=fg_color, text_color=text_color).pack(side="left", padx=(0, 6))
        if not tags and self.article.get("status") != "error":
            Pill(self.tag_row, "待生成", fg_color=SURFACE_ALT, text_color=MUTED).pack(side="left")

    def _wire_events(self):
        widgets = [self, self.title_label, self.summary_label, self.tag_row]
        for widget in widgets:
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            widget.bind("<Button-1>", self._on_click)

    def _on_click(self, _event):
        self.on_open(self.article)

    def _on_enter(self, _event):
        self.configure(border_color=ACCENT, fg_color="#FDFCFA")

    def _on_leave(self, _event):
        self.configure(border_color=BORDER, fg_color=SURFACE)


class EmptyState(ctk.CTkFrame):
    """Centered empty state used by region pages."""

    def __init__(self, master, title: str, subtitle: str):
        super().__init__(master, fg_color="transparent")
        ctk.CTkLabel(self, text=title, text_color=TEXT, font=card_title_font()).pack(pady=(24, 4))
        ctk.CTkLabel(self, text=subtitle, text_color=MUTED, font=small_font()).pack()


class SkeletonCard(ctk.CTkFrame):
    """Soft placeholder card shown while a region is loading."""

    def __init__(self, master):
        super().__init__(
            master,
            corner_radius=RADIUS_CARD,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
        )
        self.grid_propagate(False)
        self.after(0, self._draw)

    def _draw(self):
        for row, width in ((0, 90), (1, 250), (2, 300), (3, 180)):
            block = ctk.CTkFrame(self, fg_color=SURFACE_ALT, corner_radius=8, height=14, width=width)
            block.place(x=14, y=24 + row * 34, anchor="w")


def _tag_colors(tag: str) -> tuple[str, str]:
    return {
        "翻译": ("#E6EEF2", "#4E6E7A"),
        "词汇": ("#F3EBDD", "#A67B3F"),
        "难句": ("#F7E1DC", "#9A4B48"),
        "背景": ("#EEE9F2", "#7C688A"),
    }.get(tag, (SURFACE_ALT, MUTED))


def _modal(parent, title: str, message: str, kind: str, confirm: bool = False) -> bool | None:
    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.minsize(380, 200)
    dialog.configure(fg_color=BG)
    dialog.transient(parent)
    dialog.grab_set()

    body = ctk.CTkFrame(dialog, fg_color=SURFACE, corner_radius=RADIUS_DIALOG, border_width=1, border_color=BORDER)
    body.pack(fill="both", expand=True, padx=20, pady=20)

    accent = ACCENT
    if kind == "warning":
        accent = WARNING
    elif kind == "error":
        accent = DANGER

    ctk.CTkLabel(body, text=title, text_color=TEXT, font=font(16, "bold")).pack(anchor="w", padx=20, pady=(20, 6))
    ctk.CTkLabel(body, text=message, text_color=MUTED, font=body_font(), wraplength=340, justify="left").pack(
        anchor="w", padx=20, pady=(0, 16)
    )

    result = tk.BooleanVar(value=False)
    button_row = ctk.CTkFrame(body, fg_color="transparent")
    button_row.pack(fill="x", padx=20, pady=(0, 20))
    if confirm:
        def cancel():
            result.set(False)
            dialog.destroy()

        def ok():
            result.set(True)
            dialog.destroy()

        ctk.CTkButton(button_row, text="取消", command=cancel, fg_color="transparent", border_width=1, border_color=BORDER, text_color=MUTED).pack(side="right")
        ctk.CTkButton(button_row, text="确认", command=ok, fg_color=accent, hover_color=ACCENT_HOVER).pack(side="right", padx=(0, 8))
    else:
        ctk.CTkButton(button_row, text="知道了", command=dialog.destroy, fg_color=accent, hover_color=ACCENT_HOVER).pack(side="right")

    dialog.update_idletasks()
    width = max(420, body.winfo_reqwidth() + 40)
    height = max(220, body.winfo_reqheight() + 40)
    dialog.geometry(f"{width}x{height}")
    _center_over_parent(dialog, parent)
    dialog.wait_window()
    return result.get() if confirm else None


def _center_over_parent(dialog: ctk.CTkToplevel, parent) -> None:
    if parent is None:
        return
    try:
        parent.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        dialog.geometry(f"+{parent_x + max((parent_w - width) // 2, 0)}+{parent_y + max((parent_h - height) // 2, 0)}")
    except Exception:
        pass


def modal_info(parent, title: str, message: str) -> None:
    _modal(parent, title, message, "info")


def modal_warning(parent, title: str, message: str) -> None:
    _modal(parent, title, message, "warning")


def modal_error(parent, title: str, message: str) -> None:
    _modal(parent, title, message, "error")


def modal_confirm(parent, title: str, message: str) -> bool:
    return bool(_modal(parent, title, message, "confirm", confirm=True))
