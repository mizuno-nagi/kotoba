import os
import re
import secrets
import shutil
import subprocess
import sys
import logging
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image, ImageTk, ImageOps
except ImportError:
    Image = None
    ImageTk = None
    ImageOps = None

from article_index import ArticleIndex
from logging_setup import configure_logging
from task_scheduler import (
    create_or_update_task,
    delete_task,
    task_exists,
    validate_schedule_time,
)


def _resource_path(relative: str) -> Path:
    """Return a bundled asset path that works in source and PyInstaller runs."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    return base / relative


def _ensure_tk_runtime():
    """Frozen builds need Tcl/Tk data on an ASCII path (see CPython/Tcl issue with
    non-ASCII install paths), so copy the bundled data to C:\\Users\\Public."""
    if not getattr(sys, "frozen", False):
        return
    meipass = Path(getattr(sys, "_MEIPASS", ""))
    src_tcl = meipass / "_tcl_data"
    src_tk = meipass / "_tk_data"
    if not src_tcl.is_dir() or not src_tk.is_dir():
        return

    public_root = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    candidates = [
        public_root / "JapanNewsStudy",
        Path("C:/ProgramData/JapanNewsStudy"),
    ]
    temp_root = Path(os.environ.get("TEMP", r"C:\Windows\Temp")) / "JapanNewsStudy"
    candidates.append(temp_root)

    def copy_tree(source, target, marker):
        if target.is_dir() and (target / marker).is_file():
            source_marker = source / marker
            target_marker = target / marker
            if (
                source_marker.is_file()
                and source_marker.stat().st_size == target_marker.stat().st_size
            ):
                return target
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source, target)
        return target

    for root in candidates:
        try:
            if not str(root).isascii():
                continue
            root.mkdir(parents=True, exist_ok=True)
            tcl_dir = copy_tree(src_tcl, root / "tcl8.6", "init.tcl")
            tk_dir = copy_tree(src_tk, root / "tk8.6", "tk.tcl")
        except OSError:
            continue
        os.environ["TCL_LIBRARY"] = str(tcl_dir)
        os.environ["TK_LIBRARY"] = str(tk_dir)
        return
    raise RuntimeError("Tkinter runtime cannot be initialized from a non-ASCII path")


_ensure_tk_runtime()

import tkinter as tk
import customtkinter as ctk

from ui_components import ArticleCard, EmptyState, Pill, PillNav, SkeletonCard, modal_confirm, modal_error, modal_info, modal_warning
from ui_theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_SOFT,
    BG,
    BORDER,
    DANGER,
    LINK,
    MUTED,
    RADIUS_CARD,
    RADIUS_CONTROL,
    RADIUS_DIALOG,
    RADIUS_PAGE,
    RADIUS_PILL,
    SPACE_LG,
    SPACE_MD,
    SPACE_SM,
    SPACE_XL,
    SPACE_XS,
    SPACE_2XL,
    SURFACE,
    SURFACE_ALT,
    SUCCESS,
    TEXT,
    WARNING,
    body_font,
    caption_font,
    card_title_font,
    font,
    hero_font,
    init_theme,
    section_font,
    small_font,
    title_font,
)

from main import (
    ARTICLE_INDEX_PATH,
    CONFIG_PATH,
    OUTPUT_DIR,
    PERIOD_NAMES,
    REGION_NAMES,
    ensure_config,
    load_config,
    migrate_legacy_output,
    rebuild_day_index,
    run_image_backfill,
    run_rebuild_article,
    run_refresh_job,
    run_url_job,
    save_config,
)


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HEADING_PATTERN = re.compile(r"^#+\s+")


def _load_app_version() -> str:
    if getattr(sys, "frozen", False):
        version_path = Path(sys.executable).resolve().parent / "VERSION"
    else:
        version_path = Path(__file__).resolve().parent / "VERSION"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
        return version or "4.9.0"
    except OSError:
        return "4.9.0"


APP_VERSION = _load_app_version()
APP_NAME = "言叶"
APP_ROMANJI = "KOTOBA"
GITHUB_URL = "https://github.com/mizuno-nagi"
X_URL = "https://x.com/xinren_114514"
DISCLAIMER = "内容仅供学习参考，请自行辨别信息真实度，作者不为爬取内容负责"
SOURCE_URL_PATTERN = re.compile(r"\[原文链接\]\(([^)]+)\)")
REGIONS = (("news", "新闻"), ("food", "美食"), ("culture", "文化"))
LOCAL_PERIOD_NAMES = dict(PERIOD_NAMES)
LOCAL_PERIOD_NAMES["custom"] = "自定义"

WHITE = SURFACE
TEXT_COLOR = TEXT
LINK_BLUE = LINK

BODY_FONT = ("Microsoft YaHei UI", 12)
BODY_FONT_BOLD = ("Microsoft YaHei UI", 12, "bold")
MONO_FONT = ("Consolas", 11)

CARD_WIDTH = 340
CARD_HEIGHT = 200


class _LegacyArticleCard(tk.Frame):
    def __init__(self, master, article, on_open, on_delete, on_rebuild=None):
        super().__init__(
            master,
            bg=WHITE,
            highlightbackground=BORDER,
            highlightthickness=1,
            cursor="hand2",
            width=CARD_WIDTH,
            height=CARD_HEIGHT,
        )
        self.pack_propagate(False)
        self.article = article
        self.on_open = on_open
        self.on_delete = on_delete
        self.on_rebuild = on_rebuild

        top_bar = tk.Frame(self, bg=WHITE)
        top_bar.pack(fill="x", padx=14, pady=(12, 5))

        date_badge = tk.Label(
            top_bar,
            text=article["date"],
            bg=ACCENT_SOFT,
            fg=ACCENT,
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=8,
            pady=2,
        )
        date_badge.pack(side="left")

        source_name = article.get("source_name") or "来源"
        tk.Label(
            top_bar,
            text=source_name,
            bg="#EEF2FF",
            fg="#3730A3",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=8,
            pady=2,
            width=12,
            anchor="w",
        ).pack(side="left", padx=(6, 0))

        period_name = ""
        if article.get("source") != "custom":
            period_name = LOCAL_PERIOD_NAMES.get(
                article.get("period", ""), article.get("period", "")
            )
        if period_name:
            tk.Label(
                top_bar,
                text=period_name,
                bg="#ECFDF5",
                fg="#047857",
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=8,
                pady=2,
            ).pack(side="left", padx=(6, 0))

        self.rebuild_button = tk.Label(
            top_bar,
            text="重新抓取",
            bg="#DBEAFE",
            fg="#1D4ED8",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.rebuild_button.pack(side="right", padx=(0, 6))

        self.delete_button = tk.Label(
            top_bar,
            text="删除",
            bg="#FEE2E2",
            fg="#B91C1C",
            font=("Microsoft YaHei UI", 9, "bold"),
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self.delete_button.pack(side="right")

        title_label = tk.Label(
            self,
            text=article["title"],
            bg=WHITE,
            fg=TEXT_COLOR,
            font=("Microsoft YaHei UI", 12, "bold"),
            justify="left",
            anchor="w",
            wraplength=CARD_WIDTH - 28,
        )
        title_label.pack(fill="x", padx=14)

        summary_label = tk.Label(
            self,
            text=article["summary"],
            bg=WHITE,
            fg=MUTED,
            font=BODY_FONT,
            justify="left",
            anchor="nw",
            wraplength=CARD_WIDTH - 28,
            height=3,
        )
        summary_label.pack(fill="x", padx=14, pady=(6, 4))

        tag_row = tk.Frame(self, bg=WHITE)
        tag_row.pack(fill="x", padx=14, pady=(4, 12), anchor="w")
        if article.get("status") == "error":
            tk.Label(
                tag_row,
                text="生成失败",
                bg="#7F1D1D",
                fg="#FFFFFF",
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        for tag in article["tags"][:4]:
            bg_color, fg_color = TAG_STYLES.get(tag, ("#EEF2FF", "#3730A3"))
            tk.Label(
                tag_row,
                text=tag,
                bg=bg_color,
                fg=fg_color,
                font=("Microsoft YaHei UI", 9),
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 6))
        if not article["tags"]:
            tk.Label(
                tag_row,
                text="待生成",
                bg="#F3F4F6",
                fg=MUTED,
                font=("Microsoft YaHei UI", 9),
                padx=7,
                pady=2,
            ).pack(side="left")

        self._wire_events()

    def _wire_events(self):
        def wire(widget):
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
            if widget is not self.delete_button and widget is not self.rebuild_button:
                widget.bind("<Button-1>", self._on_click)
            for child in widget.winfo_children():
                wire(child)

        wire(self)
        self.rebuild_button.bind("<Button-1>", self._on_rebuild_click)
        self.rebuild_button.bind(
            "<Enter>", lambda _event: self.rebuild_button.configure(bg="#BFDBFE")
        )
        self.rebuild_button.bind(
            "<Leave>", lambda _event: self.rebuild_button.configure(bg="#DBEAFE")
        )
        self.delete_button.bind("<Button-1>", self._on_delete_click)
        self.delete_button.bind(
            "<Enter>", lambda _event: self.delete_button.configure(bg="#FECACA")
        )
        self.delete_button.bind(
            "<Leave>", lambda _event: self.delete_button.configure(bg="#FEE2E2")
        )

    def _on_rebuild_click(self, _event):
        if self.on_rebuild:
            self.on_rebuild(self.article)

    def _on_delete_click(self, _event):
        self.on_delete(self.article)

    def _on_click(self, _event):
        self.on_open(self.article)

    def _on_enter(self, _event):
        self.configure(highlightbackground=ACCENT)

    def _on_leave(self, _event):
        self.configure(highlightbackground=BORDER)


class _LegacyRegionPage(tk.Frame):
    def __init__(
        self,
        master,
        region,
        region_name,
        on_refresh,
        on_open,
        on_delete,
        on_rebuild=None,
        on_backfill=None,
        on_delete_region=None,
    ):
        super().__init__(master, bg=BG)
        self.region_page = self
        self.region = region
        self.sections = []
        self.source_filter = None
        self.articles = []
        self.on_open = on_open
        self.on_rebuild = on_rebuild
        self.on_delete = on_delete
        self.on_delete_region = on_delete_region

        header_row = tk.Frame(self, bg=BG)
        header_row.pack(fill="x", padx=14, pady=(10, 4))

        tk.Label(
            header_row,
            text=f"{region_name}区域",
            bg=BG,
            fg=TEXT_COLOR,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(side="left")

        self.refresh_button = ttk.Button(
            header_row,
            text=f"仅刷新{region_name}",
            style="Accent.TButton",
            command=lambda: on_refresh(region),
        )
        self.refresh_button.pack(side="right")

        if on_delete_region:
            self.delete_region_button = ttk.Button(
                header_row,
                text="删除该分区",
                style="Danger.TButton",
                command=lambda: on_delete_region(region),
            )
            self.delete_region_button.pack(side="right", padx=(0, 8))

        if region == "food" and on_backfill:
            self.backfill_button = ttk.Button(
                header_row,
                text="补全已有图片",
                style="TButton",
                command=on_backfill,
            )
            self.backfill_button.pack(side="right", padx=(0, 8))

        self.filter_bar = tk.Frame(self, bg=BG)
        self.filter_bar.pack(fill="x", padx=14, pady=(0, 4))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, pady=(0, 8))

        self.canvas = tk.Canvas(
            body, bg=BG, highlightthickness=0, borderwidth=0
        )
        self.canvas.pack(side="left", fill="both", expand=True, padx=(8, 0))
        scroll = ttk.Scrollbar(
            body,
            orient="vertical",
            command=self.canvas.yview,
            style="Vertical.TScrollbar",
        )
        scroll.pack(side="right", fill="y", padx=(0, 8))
        self.canvas.configure(yscrollcommand=scroll.set)

        self.inner = tk.Frame(self.canvas, bg=BG)
        self.window = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")
            ),
        )
        self.canvas.bind(
            "<Configure>",
            lambda _event: self.canvas.itemconfigure(self.window, width=_event.width),
        )
        self.canvas.bind("<Configure>", lambda _event: self.after_idle(self.reflow))

    def populate(self, articles, source_order, query):
        self.articles = list(articles)
        self.source_order = list(source_order)
        self.query = bool(query)
        self._rebuild_source_filter()
        self._render_cards()

    def _rebuild_source_filter(self):
        for child in self.filter_bar.winfo_children():
            child.destroy()

        ordered_ids = list(self.source_order)
        for article in self.articles:
            source_id = article.get("source", "")
            if source_id and source_id not in ordered_ids:
                ordered_ids.append(source_id)

        if self.source_filter not in ordered_ids:
            self.source_filter = None

        def make_button(label, source_id):
            active = self.source_filter == source_id
            button = tk.Label(
                self.filter_bar,
                text=label,
                bg=ACCENT if active else WHITE,
                fg=WHITE if active else TEXT_COLOR,
                font=("Microsoft YaHei UI", 9, "bold"),
                padx=10,
                pady=4,
                cursor="hand2",
                highlightbackground=ACCENT if active else BORDER,
                highlightthickness=1,
            )
            button.bind(
                "<Button-1>",
                lambda _event, sid=source_id: self._set_source_filter(sid),
            )
            button.pack(side="left", padx=(0, 6))

        make_button(f"全部 ({len(self.articles)})", None)
        for source_id in ordered_ids:
            source_articles = [
                article
                for article in self.articles
                if article.get("source", "") == source_id
            ]
            if not source_articles:
                continue
            source_name = source_articles[0].get("source_name") or source_id
            make_button(f"{source_name} ({len(source_articles)})", source_id)

    def _set_source_filter(self, source_id):
        self.source_filter = source_id
        self._rebuild_source_filter()
        self._render_cards()

    def _render_cards(self):
        for child in self.inner.winfo_children():
            child.destroy()
        self.sections = []

        filtered = [
            article
            for article in self.articles
            if self.source_filter is None
            or article.get("source", "") == self.source_filter
        ]
        filtered.sort(
            key=lambda article: (
                article.get("updated_at") or "",
                str(article.get("path") or ""),
            ),
            reverse=True,
        )

        if not filtered:
            empty = tk.Frame(self.inner, bg=BG)
            empty.pack(fill="both", expand=True, pady=70)
            if self.query:
                text = "没有找到相关新闻"
            elif self.source_filter:
                text = "该报刊暂无新闻"
            elif self.region == "culture":
                text = "文化区域暂无内容"
            else:
                text = "暂无新闻"
            tk.Label(
                empty,
                text=text,
                bg=BG,
                fg=TEXT_COLOR,
                font=("Microsoft YaHei UI", 15, "bold"),
            ).pack()
            tk.Label(
                empty,
                text="刷新后新内容会显示在这里",
                bg=BG,
                fg=MUTED,
                font=BODY_FONT,
            ).pack(pady=(8, 0))
            self.after_idle(self.reflow)
            return

        cards_frame = tk.Frame(self.inner, bg=BG)
        cards_frame.pack(fill="x", padx=6, pady=(8, 8))
        cards = []
        for article in filtered:
            cards.append(
                ArticleCard(
                    cards_frame,
                    article,
                    self.on_open,
                    self.on_delete,
                    self.on_rebuild,
                )
            )
        self.sections.append((cards_frame, cards))
        self.after_idle(self.reflow)

    def reflow(self):
        for cards_frame, cards in self.sections:
            if not cards:
                continue
            width = cards_frame.winfo_width() or self.canvas.winfo_width()
            if width >= 1050:
                columns = 3
            elif width >= 700:
                columns = 2
            else:
                columns = 1
            columns = min(columns, len(cards))
            for index, card in enumerate(cards):
                card.grid_forget()
                card.grid(
                    row=index // columns,
                    column=index % columns,
                    padx=8,
                    pady=8,
                    sticky="nw",
                )
            for column in range(columns):
                cards_frame.grid_columnconfigure(column, weight=1, uniform="cards")

    def set_refresh_button_state(self, state):
        self.refresh_button.configure(state=state)

    def remember_rebuild_buttons(self, targets):
        for _frame, cards in self.sections:
            for card in cards:
                targets.append(card.rebuild_button)


class RegionPage(ctk.CTkFrame):
    def __init__(
        self,
        master,
        region,
        region_name,
        on_refresh,
        on_open,
        on_delete,
        on_rebuild=None,
        on_backfill=None,
        on_delete_region=None,
    ):
        super().__init__(master, fg_color="transparent", corner_radius=0)
        self.region_page = self
        self.region = region
        self.sections = []
        self.source_filter = None
        self.articles = []
        self.on_open = on_open
        self.on_rebuild = on_rebuild
        self.on_delete = on_delete
        self.on_delete_region = on_delete_region
        self.loading = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header_row = ctk.CTkFrame(self, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=SPACE_MD, pady=(SPACE_SM, SPACE_XS))
        header_row.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header_row,
            text=region_name,
            text_color=TEXT,
            font=section_font(),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        if on_delete_region:
            self.delete_region_button = ctk.CTkButton(
                header_row,
                text="删除该分区",
                height=34,
                corner_radius=RADIUS_PILL,
                fg_color="transparent",
                hover_color="#F7E1DC",
                text_color=DANGER,
                font=small_font(),
                command=lambda: on_delete_region(region),
            )
            self.delete_region_button.grid(row=0, column=2, padx=(0, SPACE_XS))

        if region == "food" and on_backfill:
            self.backfill_button = ctk.CTkButton(
                header_row,
                text="补全已有图片",
                height=34,
                corner_radius=RADIUS_PILL,
                fg_color="transparent",
                hover_color=SURFACE_ALT,
                text_color=MUTED,
                font=small_font(),
                command=on_backfill,
            )
            self.backfill_button.grid(row=0, column=3, padx=(0, SPACE_XS))

        self.refresh_button = ctk.CTkButton(
            header_row,
            text=f"刷新{region_name}",
            height=34,
            corner_radius=RADIUS_PILL,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=SURFACE,
            font=small_font(),
            command=lambda: on_refresh(region),
        )
        self.refresh_button.grid(row=0, column=4)

        self.filter_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.filter_bar.grid(row=1, column=0, sticky="ew", padx=SPACE_MD, pady=(0, SPACE_XS))

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=0)
        self.scroll.grid(row=2, column=0, sticky="nsew", padx=SPACE_XS, pady=SPACE_XS)
        self.scroll.grid_columnconfigure(0, weight=1)
        self.scroll._parent_canvas.configure(yscrollincrement=4)

        self.cards_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.cards_frame.grid(row=0, column=0, sticky="nsew", padx=SPACE_XS, pady=SPACE_XS)
        self.cards_frame.grid_columnconfigure(0, weight=1)

        self.bind("<Configure>", lambda _event: self.after_idle(self.reflow))
        self.scroll.bind("<Configure>", lambda _event: self.after_idle(self.reflow), add="+")

    def populate(self, articles, source_order, query):
        self.articles = list(articles)
        self.source_order = list(source_order)
        self.query = bool(query)
        self._rebuild_source_filter()
        self._render_cards()

    def set_loading(self, loading):
        self.loading = bool(loading)
        self._render_cards()

    def _rebuild_source_filter(self):
        for child in self.filter_bar.winfo_children():
            child.destroy()

        ordered_ids = list(self.source_order)
        for article in self.articles:
            source_id = article.get("source", "")
            if source_id and source_id not in ordered_ids:
                ordered_ids.append(source_id)

        if self.source_filter not in ordered_ids:
            self.source_filter = None

        def make_button(label, source_id):
            active = self.source_filter == source_id
            button = ctk.CTkButton(
                self.filter_bar,
                text=label,
                width=120,
                height=32,
                corner_radius=RADIUS_PILL,
                fg_color=ACCENT_SOFT if active else SURFACE,
                hover_color=ACCENT_SOFT if active else SURFACE_ALT,
                text_color=ACCENT if active else MUTED,
                font=caption_font(),
                border_width=1 if not active else 0,
                border_color=BORDER if not active else ACCENT_SOFT,
                command=lambda sid=source_id: self._set_source_filter(sid),
            )
            button.pack(side="left", padx=(0, SPACE_XS))

        make_button(f"全部 ({len(self.articles)})", None)
        for source_id in ordered_ids:
            source_articles = [article for article in self.articles if article.get("source", "") == source_id]
            if not source_articles:
                continue
            source_name = source_articles[0].get("source_name") or source_id
            make_button(f"{source_name} ({len(source_articles)})", source_id)

    def _set_source_filter(self, source_id):
        self.source_filter = source_id
        self._rebuild_source_filter()
        self._render_cards()

    def _render_cards(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()
        self.sections = []

        filtered = [
            article
            for article in self.articles
            if self.source_filter is None or article.get("source", "") == self.source_filter
        ]
        filtered.sort(
            key=lambda article: (article.get("updated_at") or "", str(article.get("path") or "")),
            reverse=True,
        )

        if self.loading and not filtered:
            cards = [SkeletonCard(self.cards_frame) for _ in range(6)]
            self.sections.append((self.cards_frame, cards))
            self.after_idle(self.reflow)
            return

        if not filtered:
            if self.query:
                title, subtitle = "没有找到相关新闻", "试试更换搜索关键词或日期筛选"
            elif self.source_filter:
                title, subtitle = "该报刊暂无新闻", "刷新后新内容会显示在这里"
            elif self.region == "culture":
                title, subtitle = "文化区域暂无内容", "刷新后新内容会显示在这里"
            else:
                title, subtitle = "暂无新闻", "刷新后新内容会显示在这里"
            empty = EmptyState(self.cards_frame, title, subtitle)
            empty.grid(row=0, column=0, pady=SPACE_XL)
            self.after_idle(self.reflow)
            return

        cards = [
            ArticleCard(self.cards_frame, article, self.on_open, self.on_delete, self.on_rebuild)
            for article in filtered
        ]
        self.sections.append((self.cards_frame, cards))
        self.after_idle(self.reflow)

    def reflow(self):
        for cards_frame, cards in self.sections:
            if not cards:
                continue
            width = cards_frame.winfo_width() or self.scroll.winfo_width() or self.winfo_width()
            if width >= 1180:
                columns = 3
            elif width >= 760:
                columns = 2
            else:
                columns = 1
            columns = min(columns, len(cards))
            for index, card in enumerate(cards):
                card.grid_forget()
                card.grid(row=index // columns, column=index % columns, padx=SPACE_XS, pady=SPACE_XS, sticky="nw")
            for column in range(columns):
                cards_frame.grid_columnconfigure(column, weight=1, uniform="cards")

    def set_refresh_button_state(self, state):
        self.refresh_button.configure(state=state)

    def remember_rebuild_buttons(self, targets):
        for _frame, cards in self.sections:
            for card in cards:
                if hasattr(card, "rebuild_button"):
                    targets.append(card.rebuild_button)


class DigestApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        init_theme(self)
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1280x820")
        self.minsize(980, 640)
        self.configure(fg_color=BG)
        self._apply_window_icon()

        configure_logging(Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent)
        migrate_legacy_output()
        self.config_data = ensure_config(CONFIG_PATH)
        self.article_index = ArticleIndex(ARTICLE_INDEX_PATH)
        self.article_index.sync_from_disk(
            OUTPUT_DIR, self.config_data.get("sources", [])
        )
        self.job_running = False
        self.scheduled_today = False
        self._scheduled_date = ""
        self.cancel_event = threading.Event()
        self.schedule_time = str(self.config_data.get("schedule_time", "07:00"))
        self.all_articles = []
        self.current_article = None
        self._link_targets = {}
        self._image_refs = []
        self.error_details_button = None

        self._build_ui()
        self._load_schedule_setting()
        self.after(100, self.refresh_dates)
        self.after(1000, self._schedule_tick)

    def _apply_window_icon(self):
        icon_path = _resource_path("assets/app.ico")
        if not icon_path.is_file():
            return
        try:
            self.iconbitmap(str(icon_path))
        except Exception:
            pass

    def _build_ui(self):
        self._build_header()

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.pack(fill="both", expand=True, padx=SPACE_MD, pady=(0, SPACE_SM))
        self.content.grid_rowconfigure(1, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pill_nav = PillNav(
            self.content,
            [(region, label) for region, label in REGIONS],
            initial="news",
            command=self._show_region,
        )
        self.pill_nav.grid(row=0, column=0, sticky="w", pady=(0, SPACE_SM))

        self.region_stack = ctk.CTkFrame(self.content, fg_color="transparent", corner_radius=0)
        self.region_stack.grid(row=1, column=0, sticky="nsew")
        self.region_stack.grid_rowconfigure(0, weight=1)
        self.region_stack.grid_columnconfigure(0, weight=1)

        self.region_pages = {}
        for region, region_name in REGIONS:
            page = RegionPage(
                self.region_stack,
                region,
                region_name,
                self._start_job,
                self._open_article,
                self._delete_article,
                self._rebuild_article,
                self._start_image_backfill if region == "food" else None,
                self._delete_region,
            )
            self.region_pages[region] = page
            page.grid(row=0, column=0, sticky="nsew")
        self._show_region("news")

        self.detail_view = ctk.CTkFrame(self.content, fg_color=BG, corner_radius=0)
        self.detail_view.grid(row=1, column=0, sticky="nsew")
        self._build_detail()
        self.rebuild_buttons = []

        disclaimer_bar = ctk.CTkFrame(self, fg_color=ACCENT_SOFT, corner_radius=0)
        disclaimer_bar.pack(fill="x", side="bottom")
        ctk.CTkLabel(
            disclaimer_bar,
            text=DISCLAIMER,
            text_color=ACCENT,
            font=caption_font(),
        ).pack()

        self.detail_view.grid_remove()

    def _configure_styles(self):
        self.style = ttk.Style(self)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        self.style.configure(".", font=BODY_FONT, background=BG, foreground=TEXT_COLOR)
        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=TEXT_COLOR)
        self.style.configure("White.TLabel", background=WHITE, foreground=TEXT_COLOR)
        self.style.configure("Muted.TLabel", background=WHITE, foreground=MUTED)
        self.style.configure(
            "DetailTitle.TLabel",
            background=WHITE,
            foreground=TEXT_COLOR,
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        self.style.configure(
            "Region.TNotebook",
            background=BG,
            borderwidth=0,
            tabmargins=(8, 8, 8, 0),
        )
        self.style.configure(
            "Region.TNotebook.Tab",
            background=WHITE,
            foreground=TEXT_COLOR,
            padding=(20, 9),
            font=("Microsoft YaHei UI", 11, "bold"),
            borderwidth=0,
        )
        self.style.map(
            "Region.TNotebook.Tab",
            background=[("selected", ACCENT), ("active", "#F3F4F6")],
            foreground=[("selected", WHITE), ("active", TEXT_COLOR)],
        )
        self.style.configure(
            "TButton",
            background=WHITE,
            foreground=TEXT_COLOR,
            bordercolor=BORDER,
            padding=(12, 6),
            font=BODY_FONT,
        )
        self.style.map(
            "TButton",
            background=[("active", "#F3F4F6"), ("disabled", "#F9FAFB")],
            foreground=[("disabled", MUTED)],
        )
        self.style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=WHITE,
            bordercolor=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            padding=(14, 7),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", "#B71C2F"), ("disabled", "#F2A3AC")],
            foreground=[("disabled", WHITE)],
        )
        self.style.configure(
            "Danger.TButton",
            background=ACCENT_SOFT,
            foreground=ACCENT,
            bordercolor="#FECACA",
            lightcolor=ACCENT_SOFT,
            darkcolor=ACCENT_SOFT,
            padding=(12, 6),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.style.map(
            "Danger.TButton",
            background=[("active", "#FDE8E8"), ("disabled", "#F9FAFB")],
            foreground=[("disabled", MUTED)],
        )
        self.style.configure(
            "TEntry",
            fieldbackground=WHITE,
            foreground=TEXT_COLOR,
            bordercolor=BORDER,
            insertcolor=TEXT_COLOR,
            padding=6,
        )
        self.style.map("TEntry", bordercolor=[("focus", ACCENT)])
        self.style.configure(
            "TCombobox",
            fieldbackground=WHITE,
            background=WHITE,
            foreground=TEXT_COLOR,
            arrowcolor=MUTED,
            bordercolor=BORDER,
            padding=4,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", WHITE)],
            bordercolor=[("focus", ACCENT)],
        )
        self.style.configure(
            "Digest.TCheckbutton",
            background=WHITE,
            foreground=TEXT_COLOR,
            font=BODY_FONT,
        )
        self.style.map(
            "Digest.TCheckbutton",
            background=[("active", WHITE)],
            indicatorcolor=[("selected", ACCENT)],
        )
        self.style.configure(
            "Vertical.TScrollbar",
            background="#D1D5DB",
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
        )

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0)
        header.pack(fill="x")

        top_row = ctk.CTkFrame(header, fg_color="transparent")
        top_row.pack(fill="x", padx=SPACE_MD, pady=(SPACE_SM, SPACE_XS))

        brand = ctk.CTkFrame(top_row, fg_color="transparent")
        brand.pack(side="left")
        self.logo_image = None
        logo_path = _resource_path("assets/logo.png")
        if logo_path.is_file() and Image is not None:
            try:
                self.logo_image = ctk.CTkImage(
                    light_image=Image.open(logo_path),
                    dark_image=None,
                    size=(34, 34),
                )
            except Exception:
                self.logo_image = None
        if self.logo_image is not None:
            ctk.CTkLabel(
                brand,
                image=self.logo_image,
                text="",
                width=34,
                height=34,
            ).pack(side="left")
        else:
            ctk.CTkLabel(
                brand,
                text="言",
                fg_color=ACCENT,
                text_color=SURFACE,
                corner_radius=RADIUS_CONTROL,
                width=34,
                height=34,
                font=font(16, "bold"),
            ).pack(side="left")
        ctk.CTkLabel(
            brand,
            text=APP_NAME,
            text_color=TEXT,
            font=section_font(),
        ).pack(side="left", padx=(10, 0))

        self.job_button = ctk.CTkButton(
            top_row,
            text="＋ 获取今日新闻",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=SURFACE,
            font=small_font(),
            command=self._start_job,
        )
        self.job_button.pack(side="left", padx=(20, 0))

        self.cancel_button = ctk.CTkButton(
            top_row,
            text="取消任务",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color="#F7E1DC",
            text_color=DANGER,
            font=small_font(),
            command=self._cancel_job,
            state="disabled",
        )
        self.cancel_button.pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            top_row,
            text="打开输出文件夹",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=small_font(),
            command=self._open_output_folder,
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            top_row,
            text="设置",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=small_font(),
            command=self._open_settings,
        ).pack(side="left", padx=(8, 0))

        self.auto_schedule_var = tk.BooleanVar(value=False)
        ctk.CTkSwitch(
            top_row,
            text="每日定时",
            variable=self.auto_schedule_var,
            fg_color=SURFACE_ALT,
            progress_color=ACCENT,
            button_color=SURFACE,
            text_color=MUTED,
            font=small_font(),
            command=self._save_auto_schedule,
        ).pack(side="left", padx=(18, 0))

        self.status_var = tk.StringVar(value="就绪")
        ctk.CTkLabel(
            top_row,
            textvariable=self.status_var,
            text_color=MUTED,
            font=small_font(),
            anchor="e",
            width=38,
        ).pack(side="right", fill="x", expand=True, padx=(12, 0))

        self.hero_area = ctk.CTkFrame(header, fg_color="transparent")
        self.hero_area.pack(fill="x", padx=SPACE_MD, pady=(SPACE_SM, SPACE_XS))
        self.greeting_label = ctk.CTkLabel(
            self.hero_area,
            text=self._greeting(),
            text_color=TEXT,
            font=title_font(),
            anchor="w",
        )
        self.greeting_label.pack(anchor="w")
        ctk.CTkLabel(
            self.hero_area,
            text="今天，读一点世界。",
            text_color=MUTED,
            font=body_font(),
            anchor="w",
        ).pack(anchor="w", pady=(4, 2))
        ctk.CTkLabel(
            self.hero_area,
            text=datetime.now().strftime("%Y年%m月%d日 %A"),
            text_color=ACCENT,
            font=small_font(),
            anchor="w",
        ).pack(anchor="w")

        self.search_tool_area = ctk.CTkFrame(header, fg_color="transparent")
        self.search_tool_area.pack(fill="x", padx=SPACE_MD, pady=(0, SPACE_SM))

        filter_row = ctk.CTkFrame(self.search_tool_area, fg_color="transparent")
        filter_row.pack(fill="x", pady=(0, SPACE_XS))

        ctk.CTkLabel(filter_row, text="搜索", text_color=MUTED, font=small_font()).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            filter_row,
            textvariable=self.search_var,
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color=SURFACE,
            border_color=BORDER,
            text_color=TEXT,
            font=body_font(),
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(SPACE_XS, SPACE_XS))
        self.search_entry.bind("<Return>", self._search)
        ctk.CTkButton(
            filter_row,
            text="搜索",
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=SURFACE,
            font=small_font(),
            command=self._search,
        ).pack(side="left")

        ctk.CTkLabel(filter_row, text="日期", text_color=MUTED, font=small_font()).pack(side="left", padx=(SPACE_SM, SPACE_XS))
        self.date_filter_var = tk.StringVar(value="全部日期")
        self.date_combo = ctk.CTkComboBox(
            filter_row,
            variable=self.date_filter_var,
            values=["全部日期"],
            state="readonly",
            width=150,
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color=SURFACE,
            border_color=BORDER,
            text_color=TEXT,
            dropdown_font=small_font(),
            font=small_font(),
            command=lambda _value: self._apply_filters(),
        )
        self.date_combo.pack(side="left", padx=(0, SPACE_XS))

        url_row = ctk.CTkFrame(self.search_tool_area, fg_color="transparent")
        url_row.pack(fill="x")
        ctk.CTkLabel(url_row, text="网址", text_color=MUTED, font=small_font()).pack(side="left")
        self.url_var = tk.StringVar()
        self.url_entry = ctk.CTkEntry(
            url_row,
            textvariable=self.url_var,
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color=SURFACE,
            border_color=BORDER,
            text_color=TEXT,
            font=body_font(),
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(SPACE_XS, SPACE_XS))
        self.url_entry.bind("<Return>", self._start_url_job)
        self.url_button = ctk.CTkButton(
            url_row,
            text="抓取并翻译 →",
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=SURFACE,
            font=small_font(),
            command=self._start_url_job,
        )
        self.url_button.pack(side="left")

    def _greeting(self):
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "早上好"
        if 12 <= hour < 18:
            return "下午好"
        return "晚上好"

    def _build_detail(self):
        detail_header = ctk.CTkFrame(
            self.detail_view,
            fg_color=SURFACE,
            corner_radius=RADIUS_CARD,
            border_width=1,
            border_color=BORDER,
        )
        detail_header.pack(fill="x", padx=SPACE_MD, pady=(SPACE_SM, SPACE_XS))

        ctk.CTkButton(
            detail_header,
            text="返回",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=SURFACE,
            font=small_font(),
            command=self._show_home,
        ).pack(side="left", padx=SPACE_SM, pady=SPACE_SM)

        title_column = ctk.CTkFrame(detail_header, fg_color="transparent")
        title_column.pack(side="left", fill="x", expand=True, padx=(SPACE_XS, SPACE_SM), pady=SPACE_XS)
        self.detail_title_var = tk.StringVar()
        ctk.CTkLabel(
            title_column,
            textvariable=self.detail_title_var,
            text_color=TEXT,
            font=title_font(),
            wraplength=760,
            justify="left",
        ).pack(fill="x", anchor="w")
        self.detail_meta_var = tk.StringVar()
        ctk.CTkLabel(
            title_column,
            textvariable=self.detail_meta_var,
            text_color=MUTED,
            font=small_font(),
            justify="left",
        ).pack(fill="x", anchor="w", pady=(4, 0))

        self.open_source_button = ctk.CTkButton(
            detail_header,
            text="打开原文",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=small_font(),
            command=self._open_source,
        )
        self.open_source_button.pack(side="right", padx=SPACE_SM, pady=SPACE_SM)
        self.rebuild_article_button = ctk.CTkButton(
            detail_header,
            text="重新抓取",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=small_font(),
            command=self._rebuild_current_article,
        )
        self.rebuild_article_button.pack(side="right", padx=(0, SPACE_XS), pady=SPACE_SM)
        self.delete_article_button = ctk.CTkButton(
            detail_header,
            text="删除",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color="#F7E1DC",
            text_color=DANGER,
            font=small_font(),
            command=self._delete_current_article,
        )
        self.delete_article_button.pack(side="right", padx=(0, SPACE_XS), pady=SPACE_SM)

        body = ctk.CTkFrame(self.detail_view, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=SPACE_MD, pady=(0, SPACE_SM))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.text = ctk.CTkTextbox(
            body,
            corner_radius=RADIUS_DIALOG,
            fg_color=SURFACE,
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            font=body_font(),
            wrap="word",
        )
        self.text.grid(row=0, column=0, sticky="nsew", padx=(0, 0), pady=(0, 0))
        self.textbox = self.text._textbox
        self.text.configure(state="disabled")

        self.textbox.tag_configure(
            "h1",
            font=("Microsoft YaHei UI", 24, "bold"),
            foreground=TEXT_COLOR,
            spacing1=4,
            spacing3=SPACE_SM,
        )
        self.textbox.tag_configure(
            "h2",
            font=("Microsoft YaHei UI", 16, "bold"),
            foreground=ACCENT,
            background=ACCENT_SOFT,
            spacing1=SPACE_SM,
            spacing3=SPACE_XS,
            lmargin1=SPACE_XS,
            lmargin2=SPACE_XS,
        )
        self.textbox.tag_configure(
            "h3",
            font=("Microsoft YaHei UI", 14, "bold"),
            foreground=TEXT_COLOR,
            spacing1=SPACE_XS,
            spacing3=SPACE_XS,
        )
        self.textbox.tag_configure(
            "body", font=BODY_FONT, foreground=TEXT_COLOR, spacing1=2, spacing3=6
        )
        self.textbox.tag_configure(
            "bold", font=BODY_FONT_BOLD, foreground=TEXT
        )
        self.textbox.tag_configure(
            "italic", font=("Microsoft YaHei UI", 12, "italic"), foreground=MUTED
        )
        self.textbox.tag_configure("link", foreground=LINK_BLUE, underline=True)
        self.textbox.tag_configure(
            "table", font=MONO_FONT, foreground=TEXT_COLOR, spacing1=2, spacing2=2
        )
        self.textbox.tag_configure(
            "table_header",
            font=("Consolas", 11, "bold"),
            foreground=SURFACE,
            background=ACCENT,
            spacing1=3,
            spacing2=3,
        )
        self.textbox.tag_configure(
            "table_alt",
            font=MONO_FONT,
            foreground=TEXT_COLOR,
            background=SURFACE_ALT,
            spacing1=2,
            spacing2=2,
        )
        self.text.bind("<Button-1>", self._on_text_click)

    def _on_global_mousewheel(self, event):
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None or widget.winfo_toplevel() is not self:
            return
        current = widget
        while current is not None:
            page = getattr(current, "region_page", None)
            if page is not None:
                page.canvas.yview_scroll(int(-event.delta / 120), "units")
                return "break"
            current = current.master

    def _load_schedule_setting(self):
        self.schedule_time = validate_schedule_time(
            self.config_data.get("schedule_time", "07:00")
        ) or "07:00"
        self.auto_schedule_var.set(bool(self.config_data.get("auto_schedule", False)))

    def _save_auto_schedule(self):
        self.config_data = load_config(CONFIG_PATH)
        enabled = bool(self.auto_schedule_var.get())
        self.config_data["auto_schedule"] = enabled
        if enabled:
            self.schedule_time = validate_schedule_time(
                self.config_data.get("schedule_time", "07:00")
            ) or "07:00"
            self.config_data["schedule_time"] = self.schedule_time
            try:
                create_or_update_task(self.schedule_time)
            except Exception as exc:
                self.auto_schedule_var.set(False)
                self.config_data["auto_schedule"] = False
                save_config(self.config_data, CONFIG_PATH)
                modal_error(self, "定时任务创建失败", str(exc))
                self._set_status("定时任务创建失败")
                return
        else:
            try:
                if task_exists():
                    delete_task()
            except Exception as exc:
                logging.getLogger(__name__).warning("删除定时任务失败：%s", exc)
        save_config(self.config_data, CONFIG_PATH)
        self._set_status(
            "定时设置已保存" if enabled else "已关闭自动定时"
        )

    def _set_status(self, text):
        self.status_var.set(text)

    def refresh_dates(self):
        self.config_data = ensure_config(CONFIG_PATH)
        self.all_articles = self._load_articles()
        dates = sorted({article["date"] for article in self.all_articles}, reverse=True)
        values = ["全部日期"] + dates
        self.date_combo.configure(values=values)
        if self.date_filter_var.get() not in values:
            self.date_filter_var.set("全部日期")
        self._apply_filters()
        self._collect_rebuild_buttons()

    def _collect_rebuild_buttons(self):
        buttons = [self.rebuild_article_button]
        for page in self.region_pages.values():
            page.remember_rebuild_buttons(buttons)
        self.rebuild_buttons = buttons

    def _source_order(self, region):
        order = ["custom"]
        for source in self.config_data.get("sources", []):
            if not isinstance(source, dict):
                continue
            if source.get("region") != region:
                continue
            source_id = source.get("id", "")
            if source_id and source_id not in order:
                order.append(source_id)
        return order

    def _load_articles(self):
        articles = self.article_index.list_articles(include_raw=False)
        for article in articles:
            article["search_text"] = " ".join(
                (
                    article.get("title", ""),
                    article.get("summary", ""),
                    article.get("source_name", ""),
                )
            ).lower()
        return articles

    def _parse_article(
        self, date, path, raw, source_info, region=None, period=None
    ):
        title = _first_title(raw)
        summary = _first_summary(raw)
        tags = []
        markers = (
            ("## 翻译", "翻译"),
            ("四级翻译", "翻译"),
            ("六级翻译", "翻译"),
            ("重点词汇", "词汇"),
            ("难句解析", "难句"),
            ("背景补充", "背景"),
        )
        for marker, label in markers:
            if marker in raw:
                tags.append(label)
        match = SOURCE_URL_PATTERN.search(raw)
        source_id = source_info.get("id", "custom")
        return {
            "date": date,
            "path": path,
            "title": title,
            "summary": summary,
            "tags": tags,
            "raw": raw,
            "source_url": match.group(1) if match else "",
            "source": source_id,
            "source_name": source_info.get("name") or source_id,
            "source_config": source_info,
            "region": region or source_info.get("region", "news"),
            "period": period or source_info.get("period", "daily"),
        }

    def _apply_filters(self, _event=None):
        query = self.search_var.get().strip().lower()
        selected_date = self.date_filter_var.get()
        shown = 0
        for region, page in self.region_pages.items():
            filtered = []
            for article in self.all_articles:
                if article.get("region", "news") != region:
                    continue
                if selected_date != "全部日期" and article["date"] != selected_date:
                    continue
                if query and query not in article.get("search_text", ""):
                    continue
                filtered.append(article)
            shown += len(filtered)
            page.populate(filtered, self._source_order(region), bool(query))
        if query:
            self._set_status(f"找到 {shown} 条搜索结果")
        elif not self.all_articles:
            self._set_status("暂无新闻")
        else:
            self._set_status(f"共显示 {shown} 篇新闻")

    def _search(self, _event=None):
        self._apply_filters()

    def _show_home(self):
        self.detail_view.grid_remove()
        self.pill_nav.grid()
        self.hero_area.pack(fill="x", padx=SPACE_MD, pady=(SPACE_SM, SPACE_XS))
        self.search_tool_area.pack(fill="x", padx=SPACE_MD, pady=(0, SPACE_SM))
        self.region_stack.grid()
        self.region_stack.tkraise()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self._image_refs.clear()
        self._link_targets.clear()
        self._apply_filters()

    def _show_region(self, region):
        for key, page in self.region_pages.items():
            if key == region:
                page.grid()
            else:
                page.grid_remove()
        self._set_status(f"正在浏览：{REGION_NAMES.get(region, region)}")

    def _open_article(self, article):
        if not article.get("raw"):
            raw = self.article_index.get_raw(article["path"])
            if not raw:
                raw = article["path"].read_text(encoding="utf-8", errors="replace")
            article["raw"] = raw
        self.current_article = article
        self.hero_area.pack_forget()
        self.search_tool_area.pack_forget()
        self.pill_nav.grid_remove()
        self.detail_title_var.set(article["title"])
        meta = [REGION_NAMES.get(article.get("region", ""), "新闻")]
        if article.get("source_name"):
            meta.append(article["source_name"])
        period = article.get("period", "")
        if period and period != "custom":
            meta.append(PERIOD_NAMES.get(period, period))
        meta.append(article["date"])
        meta.append(article["path"].name)
        self.detail_meta_var.set(" · ".join(meta))
        self.region_stack.grid_remove()
        self.detail_view.grid()
        self.detail_view.tkraise()
        if article["source_url"]:
            self.open_source_button.configure(state="normal")
        else:
            self.open_source_button.configure(state="disabled")
        self._render_markdown(article["raw"])
        self._set_status(f"阅读：{article['title'][:40]}")

    def _open_source(self):
        url = self.current_article.get("source_url", "") if self.current_article else ""
        if url:
            webbrowser.open(url)

    def _delete_current_article(self):
        if self.current_article:
            self._delete_article(self.current_article)

    def _rebuild_current_article(self):
        if self.current_article:
            self._rebuild_article(self.current_article)

    def _rebuild_article(self, article=None):
        if self.job_running:
            return
        article = article or self.current_article
        if not article:
            return
        confirmed = modal_confirm(
            self,
            "重新抓取文章",
            "将重新下载原文并调用 DeepSeek 翻译，消耗 API 额度。\n\n"
            f"{article['title']}\n\n{Path(article['path']).name}\n\n"
            "原文件会被覆盖，是否继续？",
        )
        if not confirmed:
            return
        self.job_running = True
        self._set_job_buttons_disabled(True)
        self._set_status("正在重新抓取并翻译文章...")
        threading.Thread(
            target=self._rebuild_worker,
            args=(article,),
            daemon=True,
        ).start()

    def _rebuild_worker(self, article):
        try:
            result = run_rebuild_article(article["path"])
            self.after(0, lambda: self._rebuild_finished(True, result, article))
        except SystemExit as exc:
            message = str(exc) or "API Key 未配置"
            self.after(0, lambda: self._rebuild_finished(False, message, article))
        except Exception as exc:
            self.after(0, lambda: self._rebuild_finished(False, str(exc), article))

    def _rebuild_finished(self, ok, result, old_article):
        self.job_running = False
        self._set_job_buttons_disabled(False)
        if ok:
            title = result.get("title", "") or old_article.get("title", "")
            self._set_status(f"重新抓取完成：{title[:40]}")
            self.refresh_dates()
            updated = next(
                (
                    item
                    for item in self.all_articles
                    if str(item.get("path", "")) == str(result.get("path", ""))
                ),
                None,
            )
            if updated:
                self.current_article = updated
                self._open_article(updated)
            else:
                self._show_home()
        else:
            self._set_status("重新抓取失败")
            modal_error(self, "重新抓取失败", f"{result}\n\n请检查 API Key 和网络。")

    def _delete_article(self, article=None):
        article = article or self.current_article
        if not article:
            return
        path = Path(article["path"])
        source_label = article.get("source_name") or "文章"
        confirmed = modal_confirm(
            self,
            "删除文章",
            f"确定删除这篇{source_label}吗？\n\n"
            f"{article['title']}\n\n{path.name}",
        )
        if not confirmed:
            return
        try:
            assets_dir = path.parent / "assets"
            if assets_dir.is_dir():
                stem = path.stem
                for asset in assets_dir.iterdir():
                    if asset.is_file() and asset.name.startswith(f"{stem}_"):
                        asset.unlink(missing_ok=True)
                if not any(assets_dir.iterdir()):
                    assets_dir.rmdir()
            path.unlink(missing_ok=True)
            self.article_index.remove(path)
            if (
                article.get("source") != "custom"
                and DATE_PATTERN.fullmatch(article["date"])
                and article.get("source_config")
            ):
                rebuild_day_index(
                    path.parent,
                    article["date"],
                    source=article["source_config"],
                )
            deleted_current = (
                self.current_article is not None
                and str(self.current_article.get("path", "")) == str(path)
            )
            self.refresh_dates()
            if deleted_current:
                self.current_article = None
                self._show_home()
            self._set_status(f"已删除：{article['title'][:40]}")
        except OSError as exc:
            modal_error(self, "删除失败", f"无法删除文件：\n{path}\n\n{exc}")

    def _delete_region(self, region):
        if region not in REGION_NAMES:
            return
        if self.job_running:
            modal_info(self, "无法删除", "抓取任务进行中，请先取消任务再删除分区。")
            return

        region_label = REGION_NAMES.get(region, region)
        output_root = OUTPUT_DIR.resolve()
        region_dir = (OUTPUT_DIR / region).resolve()
        if region_dir.parent != output_root:
            modal_error(self, "删除失败", f"分区路径无效：\n{region_dir}")
            return

        confirmed = modal_confirm(
            self,
            "删除分区文件",
            f"确定删除“{region_label}”分区下所有本地报刊文件吗？\n\n"
            f"将删除该分区内的全部 Markdown 文章和已下载图片，且无法恢复。\n\n"
            "之后需要重新刷新才会生成新文章。",
        )
        if not confirmed:
            return

        try:
            if region_dir.exists():
                shutil.rmtree(region_dir)
            self.article_index.remove_region(region)
            self.current_article = None
            self._show_home()
            self.refresh_dates()
            self._set_status(f"已删除{region_label}分区的本地报刊文件")
        except OSError as exc:
            modal_error(self, "删除失败", f"无法删除分区文件：\n{region_dir}\n\n{exc}")

    def _render_markdown(self, raw):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self._link_targets.clear()
        self._image_refs = []

        lines = raw.splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                heading = stripped.lstrip("#").strip()
                if level <= 1:
                    heading = re.sub(r"^\d+\.\s+", "", heading)
                    tag = "h1"
                elif level == 2:
                    tag = "h2"
                else:
                    tag = "h3"
                self.text.insert("end", heading + "\n", (tag,))
            elif stripped.startswith("|"):
                end_index = index
                while end_index < len(lines) and lines[end_index].strip().startswith("|"):
                    end_index += 1
                self._insert_table(lines[index:end_index])
                index = end_index
                continue
            elif stripped.startswith("!["):
                self._insert_image_line(stripped)
                index += 1
                continue
            elif stripped == "":
                self.text.insert("end", "\n")
            elif stripped.startswith("- ") or stripped.startswith("* "):
                content = stripped[2:].strip()
                if content.startswith("!["):
                    self._insert_image_line(content)
                else:
                    content = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", content).strip()
                    self._insert_inline(self.textbox, "• " + content, ("body",))
                self.text.insert("end", "\n")
            else:
                text_value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", line).strip()
                self._insert_inline(self.textbox, text_value, ("body",))
                self.text.insert("end", "\n")
            index += 1

        self.text.configure(state="disabled")

    def _insert_image_line(self, value):
        match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", value)
        if not match:
            self._insert_inline(self.textbox, value, ("body",))
            self.text.insert("end", "\n")
            return
        alt = match.group(1)
        source = match.group(2)
        base = Path(self.current_article["path"]).parent if self.current_article else Path.cwd()
        image_path = None
        if not source.startswith(("http://", "https://")):
            candidate = Path(source)
            image_path = candidate if candidate.is_absolute() else base / candidate
            image_path = image_path.resolve()
        if image_path and image_path.exists() and Image and ImageTk:
            try:
                image = Image.open(image_path)
                if ImageOps:
                    try:
                        image = ImageOps.exif_transpose(image)
                    except Exception:
                        pass
                resize_method = getattr(Image, "Resampling", None)
                resize_filter = (
                    resize_method.BILINEAR if resize_method else Image.BILINEAR
                )
                if (getattr(image, "format", "") or "").upper() == "JPEG":
                    try:
                        image.draft("RGB", (360, 270))
                    except Exception:
                        pass
                image.thumbnail((360, 270), resize_filter)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGB")
                photo = ImageTk.PhotoImage(image)
                self._image_refs.append(photo)
                self.text.insert("end", "\n")
                self.textbox.image_create("end", image=photo)
                self.text.insert("end", f"\n{alt}\n")
                return
            except Exception:
                pass
        link_text = f"查看图片：{alt}" if alt else "查看图片"
        self._insert_inline(self.textbox, f"[{link_text}]({source})", ("body",))
        self.text.insert("end", "\n")

    def _insert_table(self, lines):
        rows = []
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            rows.append(cells)
        if not rows:
            return

        data = []
        for row in rows:
            if all(re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in row):
                continue
            data.append(row)
        if not data:
            return

        column_count = max(len(row) for row in data)
        widths = [0] * column_count
        for row in data:
            for column in range(column_count):
                cell = row[column] if column < len(row) else ""
                widths[column] = max(widths[column], len(cell))

        for row_index, row in enumerate(data):
            padded = []
            for column in range(column_count):
                cell = row[column] if column < len(row) else ""
                padded.append(cell.ljust(widths[column]))
            line = "  ".join(padded).rstrip()
            if row_index == 0:
                tags = ("table_header",)
            elif row_index % 2 == 0:
                tags = ("table_alt",)
            else:
                tags = ("table",)
            self.textbox.insert("end", line + "\n", tags)

    def _insert_inline(self, text, value, base_tags=()):
        pos = 0
        pattern = re.compile(
            r"\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*"
        )
        for match in pattern.finditer(value):
            if match.start() > pos:
                text.insert("end", value[pos : match.start()], base_tags)
            if match.group(1) is not None:
                start = text.index("end-1c")
                text.insert("end", match.group(1), base_tags + ("link",))
                end = text.index("end-1c")
                self._link_targets[(start, end)] = match.group(2)
            elif match.group(3) is not None:
                text.insert("end", match.group(3), base_tags + ("bold",))
            else:
                text.insert("end", match.group(4), base_tags + ("italic",))
            pos = match.end()
        if pos < len(value):
            text.insert("end", value[pos:], base_tags)

    def _on_text_click(self, event):
        if not self.current_article:
            return
        index = self.textbox.index(f"@{event.x},{event.y}")
        for (start, end), url in self._link_targets.items():
            if self.textbox.compare(index, ">=", start) and self.textbox.compare(index, "<", end):
                webbrowser.open(url)
                break

    def _open_output_folder(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(OUTPUT_DIR))
        except AttributeError:
            subprocess.Popen(["explorer", str(OUTPUT_DIR)])

    def _set_job_buttons_disabled(self, disabled):
        state = "disabled" if disabled else "normal"
        self.job_button.configure(state=state)
        self.url_button.configure(state=state)
        self.cancel_button.configure(state="normal" if disabled else "disabled")
        for page in self.region_pages.values():
            page.set_refresh_button_state(state)
            if hasattr(page, "backfill_button"):
                page.backfill_button.configure(state=state)
        for button in getattr(self, "rebuild_buttons", []):
            try:
                button.configure(state=state)
            except tk.TclError:
                pass

    def _start_job(self, region=None):
        if self.job_running:
            return
        self.job_running = True
        self.cancel_event.clear()
        self._set_job_buttons_disabled(True)
        region_label = REGION_NAMES.get(region or "", "全部")
        self._set_status(f"正在刷新{region_label}并生成注释...")
        threading.Thread(
            target=self._job_worker,
            args=(region,),
            daemon=True,
        ).start()

    def _cancel_job(self):
        if not self.job_running:
            return
        self.cancel_event.set()
        self._set_status("正在取消，请等待当前文章完成...")

    def _job_worker(self, region):
        try:
            result = run_refresh_job(
                region=region,
                progress=self._job_progress,
                cancel_event=self.cancel_event,
            )
            self.after(0, lambda: self._job_finished(True, result))
        except SystemExit as exc:
            message = str(exc) or "API Key 未配置"
            self.after(0, lambda: self._job_finished(False, message))
        except Exception as exc:
            self.after(0, lambda: self._job_finished(False, str(exc)))

    def _job_progress(self, source_name, done, total, title):
        def update():
            if self.job_running:
                self._set_status(
                    f"正在翻译 {source_name} {done}/{total}：{title[:28]}"
                )

        self.after(0, update)

    def _job_finished(self, ok, result):
        self.job_running = False
        self._set_job_buttons_disabled(False)
        if ok:
            if result.get("cancelled"):
                self._set_status("刷新已取消")
                self.search_var.set("")
                self.refresh_dates()
                return
            count = result.get("count", 0)
            failed_sources = [
                (item.get("source_name", ""), item.get("error", ""))
                for item in result.get("sources", [])
                if item.get("error")
            ]
            errors = [error for _name, error in failed_sources]
            if count:
                base = f"完成：本次新增 {count} 篇"
            elif errors:
                base = f"刷新完成，没有新增文章（{len(errors)} 个来源失败）"
            else:
                base = "刷新完成，没有新增文章"
            if count and errors:
                base += f"，{len(errors)} 个来源失败"
            self._set_status(base)
            if failed_sources:
                detail = "\n".join(
                    f"{name}：{error}" for name, error in failed_sources
                )
                modal_warning(self, "部分来源刷新失败", detail)
            self.search_var.set("")
            self.refresh_dates()
            if count:
                self.date_filter_var.set(datetime.now().strftime("%Y-%m-%d"))
        else:
            self._set_status("刷新失败")
            modal_error(self, "刷新失败", f"{result}\n\n请检查“设置”中的 API Key 和网络。")

    def _start_image_backfill(self):
        if self.job_running:
            return
        self.job_running = True
        self.cancel_event.clear()
        self._set_job_buttons_disabled(True)
        self._set_status("正在补全美食区图片...")
        threading.Thread(
            target=self._image_backfill_worker,
            daemon=True,
        ).start()

    def _image_backfill_worker(self):
        try:
            result = run_image_backfill(
                region="food",
                progress=self._job_progress,
                cancel_event=self.cancel_event,
            )
            self.after(0, lambda: self._image_backfill_finished(True, result))
        except Exception as exc:
            self.after(0, lambda: self._image_backfill_finished(False, str(exc)))

    def _image_backfill_finished(self, ok, result):
        self.job_running = False
        self._set_job_buttons_disabled(False)
        if not ok:
            self._set_status("图片补全失败")
            modal_error(self, "图片补全失败", str(result))
            return
        if result.get("cancelled"):
            self._set_status("图片补全已取消")
            self.refresh_dates()
            return
        updated = result.get("updated", 0)
        total = result.get("total", 0)
        self._set_status(f"图片补全完成：更新 {updated}/{total} 篇")
        self.refresh_dates()

    def _start_url_job(self, _event=None):
        if self.job_running:
            return
        url = self.url_var.get().strip()
        if not url:
            modal_warning(self, "网址为空", "请先粘贴一个 http(s) 网址")
            return
        self.job_running = True
        self.cancel_event.clear()
        self._set_job_buttons_disabled(True)
        self._set_status("正在抓取网址并生成注释...")
        threading.Thread(
            target=self._url_job_worker,
            args=(url,),
            daemon=True,
        ).start()

    def _url_job_worker(self, url):
        try:
            result = run_url_job(url, cancel_event=self.cancel_event)
            self.after(0, lambda: self._url_job_finished(True, result))
        except SystemExit as exc:
            message = str(exc) or "API Key 未配置"
            self.after(0, lambda: self._url_job_finished(False, message))
        except Exception as exc:
            self.after(0, lambda: self._url_job_finished(False, str(exc)))

    def _url_job_finished(self, ok, result):
        self.job_running = False
        self._set_job_buttons_disabled(False)
        if ok:
            if result.get("cancelled"):
                self._set_status("网址任务已取消")
                self.url_var.set("")
                return
            if result.get("skipped"):
                self._set_status("该网址今天已抓取，跳过重复注释")
            else:
                title = result.get("title", "")
                self._set_status(
                    f"网址抓取完成：{title[:40]}" if title else "网址抓取完成"
                )
            self.url_var.set("")
            date = result.get("date", "")
            if date:
                self.date_filter_var.set(date)
            self.refresh_dates()
        else:
            if isinstance(result, dict) and result.get("cancelled"):
                self._set_status("网址任务已取消")
                self.url_var.set("")
                return
            self._set_status("网址任务失败")
            modal_error(self, "网址抓取失败", f"{result}\n\n请检查网址、API Key 和网络。")

    def _legacy_open_settings(self):
        dialog = tk.Toplevel(self, bg=WHITE)
        dialog.title("设置")
        dialog.geometry("680x760")
        dialog.minsize(580, 560)
        dialog.resizable(True, True)
        dialog.transient(self)
        dialog.grab_set()

        outer = tk.Frame(dialog, bg=WHITE)
        outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(outer, bg=WHITE, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        body = tk.Frame(canvas, bg=WHITE, padx=28, pady=20)
        body_window = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(body_window, width=event.width),
        )

        tk.Label(
            body,
            text="设置",
            bg=WHITE,
            fg=TEXT_COLOR,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w")
        tk.Label(
            body,
            text="AI、抓取与定时任务配置",
            bg=WHITE,
            fg=MUTED,
            font=BODY_FONT,
        ).pack(anchor="w", pady=(2, 16))

        config = ensure_config(CONFIG_PATH)
        entries = {}
        source_vars = []

        def section_title(text):
            tk.Label(
                body,
                text=text,
                bg=ACCENT_SOFT,
                fg=ACCENT,
                font=("Microsoft YaHei UI", 10, "bold"),
                padx=8,
                pady=4,
                anchor="w",
            ).pack(fill="x", pady=(10, 6))

        def add_entry(label, key, secret=False):
            row = tk.Frame(body, bg=WHITE)
            row.pack(fill="x", pady=5)
            tk.Label(
                row,
                text=label,
                bg=WHITE,
                fg=TEXT_COLOR,
                width=22,
                anchor="w",
                font=BODY_FONT,
            ).pack(side="left")
            entry = tk.Entry(
                row,
                show="*" if secret else "",
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                font=BODY_FONT,
            )
            entry.insert(0, str(config.get(key, "")))
            entry.pack(side="left", fill="x", expand=True, ipady=5)
            entries[key] = entry
            return entry

        section_title("AI 与抓取")
        add_entry("DeepSeek API Key", "openai_api_key", secret=True)
        add_entry("DeepSeek Base URL", "openai_base_url")
        add_entry("模型", "model")
        add_entry("Firecrawl API Key", "firecrawl_api_key", secret=True)

        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=5)
        tk.Label(
            row,
            text="抓取模式",
            bg=WHITE,
            fg=TEXT_COLOR,
            width=22,
            anchor="w",
            font=BODY_FONT,
        ).pack(side="left")
        mode_var = tk.StringVar(value=str(config.get("scrape_mode", "auto")))
        ttk.Combobox(
            row,
            textvariable=mode_var,
            values=("auto", "direct", "firecrawl"),
            state="readonly",
        ).pack(side="left", fill="x", expand=True)

        section_title("抓取控制")
        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=5)
        tk.Label(
            row,
            text="每日最多篇数",
            bg=WHITE,
            fg=TEXT_COLOR,
            width=22,
            anchor="w",
            font=BODY_FONT,
        ).pack(side="left")
        max_var = tk.StringVar(value=str(config.get("max_articles", 5)))
        tk.Spinbox(
            row,
            from_=1,
            to=20,
            textvariable=max_var,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=BODY_FONT,
        ).pack(side="left", fill="x", expand=True, ipady=5)

        row = tk.Frame(body, bg=WHITE)
        row.pack(fill="x", pady=5)
        tk.Label(
            row,
            text="请求超时（秒）",
            bg=WHITE,
            fg=TEXT_COLOR,
            width=22,
            anchor="w",
            font=BODY_FONT,
        ).pack(side="left")
        timeout_var = tk.StringVar(value=str(config.get("request_timeout", 30)))
        tk.Spinbox(
            row,
            from_=5,
            to=120,
            textvariable=timeout_var,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            font=BODY_FONT,
        ).pack(side="left", fill="x", expand=True, ipady=5)

        add_entry("每日定时（HH:MM）", "schedule_time")

        section_title("来源管理")
        source_container = tk.Frame(body, bg=WHITE)
        source_container.pack(fill="x")

        def render_sources():
            sources = config.get("sources", [])
            for index, enabled_var, limit_var in source_vars:
                if index < len(sources):
                    try:
                        sources[index]["enabled"] = bool(enabled_var.get())
                        sources[index]["limit"] = max(1, int(limit_var.get()))
                    except ValueError:
                        pass
            for child in source_container.winfo_children():
                child.destroy()
            source_vars.clear()
            for index, source in enumerate(sources):
                source_row = tk.Frame(source_container, bg=WHITE)
                source_row.pack(fill="x", pady=5)
                enabled_var = tk.BooleanVar(value=bool(source.get("enabled", True)))
                limit_var = tk.StringVar(value=str(source.get("limit", 5)))
                ttk.Checkbutton(
                    source_row,
                    text="启用爬取",
                    variable=enabled_var,
                    style="Digest.TCheckbutton",
                ).pack(side="left")
                tk.Label(
                    source_row,
                    text=source.get("name", f"来源 {index + 1}"),
                    bg=WHITE,
                    fg=TEXT_COLOR,
                    font=("Microsoft YaHei UI", 10, "bold"),
                ).pack(side="left", padx=(6, 0))
                tk.Label(
                    source_row,
                    text="上限",
                    bg=WHITE,
                    fg=TEXT_COLOR,
                    font=BODY_FONT,
                ).pack(side="left", padx=(10, 4))
                tk.Spinbox(
                    source_row,
                    from_=1,
                    to=50,
                    textvariable=limit_var,
                    width=6,
                    relief="flat",
                    highlightthickness=1,
                    highlightbackground=BORDER,
                    highlightcolor=ACCENT,
                    font=BODY_FONT,
                ).pack(side="left", ipady=5)
                ttk.Button(
                    source_row,
                    text="删除",
                    style="Danger.TButton",
                    command=lambda idx=index: delete_source(idx),
                ).pack(side="right", padx=(8, 0))
                tk.Label(
                    source_row,
                    text=(
                        f"{REGION_NAMES.get(source.get('region', ''), '')} · "
                        f"{PERIOD_NAMES.get(source.get('period', ''), '')}"
                    ),
                    bg=WHITE,
                    fg=MUTED,
                    font=BODY_FONT,
                ).pack(side="right")
                source_vars.append((index, enabled_var, limit_var))

        def delete_source(index):
            sources = config.get("sources", [])
            if index < 0 or index >= len(sources):
                return
            source = sources[index]
            if not messagebox.askyesno(
                "删除来源",
                f"确定删除来源「{source.get('name', '')}」吗？\n\n"
                "只会从设置中移除该来源，已抓取的文章不会删除。",
                parent=dialog,
            ):
                return
            sources.pop(index)
            render_sources()

        def add_source_form():
            form = tk.Toplevel(dialog, bg=WHITE)
            form.title("新增来源")
            form.geometry("520x440")
            form.minsize(480, 400)
            form.transient(dialog)
            form.grab_set()

            form_body = tk.Frame(form, bg=WHITE, padx=24, pady=18)
            form_body.pack(fill="both", expand=True)
            tk.Label(
                form_body,
                text="新增来源",
                bg=WHITE,
                fg=TEXT_COLOR,
                font=("Microsoft YaHei UI", 14, "bold"),
            ).pack(anchor="w")
            tk.Label(
                form_body,
                text="保存后将参与全局刷新与每日定时任务",
                bg=WHITE,
                fg=MUTED,
                font=BODY_FONT,
            ).pack(anchor="w", pady=(2, 12))

            def field_row(label):
                row = tk.Frame(form_body, bg=WHITE)
                row.pack(fill="x", pady=6)
                tk.Label(
                    row,
                    text=label,
                    bg=WHITE,
                    fg=TEXT_COLOR,
                    width=16,
                    anchor="w",
                    font=BODY_FONT,
                ).pack(side="left")
                return row

            name_row = field_row("显示名称")
            name_var = tk.StringVar()
            tk.Entry(
                name_row,
                textvariable=name_var,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                font=BODY_FONT,
            ).pack(side="left", fill="x", expand=True, ipady=5)

            url_row = field_row("网址")
            url_var = tk.StringVar()
            tk.Entry(
                url_row,
                textvariable=url_var,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                font=BODY_FONT,
            ).pack(side="left", fill="x", expand=True, ipady=5)

            region_row = field_row("区域")
            region_var = tk.StringVar(value="新闻")
            ttk.Combobox(
                region_row,
                textvariable=region_var,
                values=("新闻", "美食", "文化"),
                state="readonly",
            ).pack(side="left", fill="x", expand=True)

            period_row = field_row("周期")
            period_var = tk.StringVar(value="日刊")
            ttk.Combobox(
                period_row,
                textvariable=period_var,
                values=("日刊", "月刊"),
                state="readonly",
            ).pack(side="left", fill="x", expand=True)

            type_row = field_row("来源类型")
            type_var = tk.StringVar(value="列表页")
            type_combo = ttk.Combobox(
                type_row,
                textvariable=type_var,
                values=("单篇文章", "列表页"),
                state="readonly",
            )
            type_combo.pack(side="left", fill="x", expand=True)

            limit_row = field_row("单次上限")
            limit_var = tk.StringVar(value="10")
            tk.Spinbox(
                limit_row,
                from_=1,
                to=50,
                textvariable=limit_var,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER,
                highlightcolor=ACCENT,
                font=BODY_FONT,
            ).pack(side="left", fill="x", expand=True, ipady=5)

            def on_type_change(_event=None):
                if type_var.get() == "单篇文章" and limit_var.get() in ("", "10"):
                    limit_var.set("1")
                elif type_var.get() == "列表页" and limit_var.get() == "1":
                    limit_var.set("10")

            type_combo.bind("<<ComboboxSelected>>", on_type_change)

            def submit():
                name = name_var.get().strip()
                url = url_var.get().strip()
                if not name:
                    messagebox.showerror("输入错误", "请填写来源名称", parent=form)
                    return
                if not re.match(r"^https?://", url, flags=re.IGNORECASE):
                    messagebox.showerror(
                        "输入错误",
                        "网址必须以 http:// 或 https:// 开头",
                        parent=form,
                    )
                    return
                try:
                    limit = max(1, min(50, int(limit_var.get())))
                except ValueError:
                    messagebox.showerror(
                        "输入错误", "单次上限必须是 1-50 的数字", parent=form
                    )
                    return
                normalized_url = url.rstrip("/")
                for source in config.get("sources", []):
                    if str(source.get("url", "")).rstrip("/") == normalized_url:
                        messagebox.showerror(
                            "输入错误", "该网址已存在，请勿重复添加", parent=form
                        )
                        return
                region = next(
                    (key for key, label in REGIONS if label == region_var.get()),
                    "news",
                )
                period = "monthly" if period_var.get() == "月刊" else "daily"
                adapter = (
                    "single_url" if type_var.get() == "单篇文章" else "list_page"
                )
                used_ids = {
                    str(source.get("id", ""))
                    for source in config.get("sources", [])
                    if isinstance(source, dict)
                }
                while True:
                    source_id = "user_" + secrets.token_hex(4)
                    if source_id in used_ids:
                        continue
                    if any(
                        (OUTPUT_DIR / region_key / source_id).exists()
                        for region_key in REGION_NAMES
                    ):
                        continue
                    break
                config.setdefault("sources", []).append(
                    {
                        "id": source_id,
                        "name": name,
                        "region": region,
                        "period": period,
                        "adapter": adapter,
                        "url": url,
                        "enabled": True,
                        "limit": limit,
                    }
                )
                render_sources()
                form.destroy()

            button_row = tk.Frame(form, bg=WHITE, padx=24, pady=12)
            button_row.pack(fill="x", side="bottom")
            ttk.Button(
                button_row, text="添加", style="Accent.TButton", command=submit
            ).pack(side="right")
            ttk.Button(
                button_row, text="取消", style="TButton", command=form.destroy
            ).pack(side="right", padx=(0, 10))

        render_sources()
        ttk.Button(
            body, text="新增来源", style="Accent.TButton", command=add_source_form
        ).pack(anchor="w", pady=(8, 0))

        tk.Label(
            body,
            text="提示：Firecrawl Key 可留空；留空时直连失败会跳过 Firecrawl，CLI 已登录的电脑会自动使用 CLI。",
            bg=WHITE,
            fg=MUTED,
            font=BODY_FONT,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(14, 0))

        button_row = tk.Frame(dialog, bg=WHITE, padx=28, pady=12)
        button_row.pack(fill="x", side="bottom")

        def save():
            updated = config
            updated["openai_api_key"] = entries["openai_api_key"].get().strip()
            updated["openai_base_url"] = (
                entries["openai_base_url"].get().strip() or "https://api.deepseek.com/v1"
            )
            updated["model"] = entries["model"].get().strip() or "deepseek-chat"
            updated["firecrawl_api_key"] = entries["firecrawl_api_key"].get().strip()
            schedule_time = validate_schedule_time(entries["schedule_time"].get())
            if not schedule_time:
                messagebox.showerror("设置错误", "定时时间必须是 HH:MM 格式")
                return
            updated["schedule_time"] = schedule_time
            updated["scrape_mode"] = mode_var.get()
            try:
                updated["max_articles"] = max(1, int(max_var.get()))
                updated["request_timeout"] = max(5, int(timeout_var.get()))
                updated_sources = updated.get("sources") or []
                for index, enabled_var, limit_var in source_vars:
                    if index < len(updated_sources):
                        updated_sources[index]["enabled"] = bool(enabled_var.get())
                        updated_sources[index]["limit"] = max(1, int(limit_var.get()))
            except ValueError:
                messagebox.showerror("设置错误", "篇数、超时和来源上限必须是数字")
                return
            save_config(updated, CONFIG_PATH)
            if updated.get("auto_schedule"):
                try:
                    create_or_update_task(updated["schedule_time"])
                except Exception as exc:
                    messagebox.showerror("定时任务更新失败", str(exc))
            self.config_data = updated
            self._load_schedule_setting()
            self._set_status("设置已保存")
            dialog.destroy()
            self.refresh_dates()

        ttk.Button(
            button_row, text="保存并关闭", style="Accent.TButton", command=save
        ).pack(side="right")
        ttk.Button(
            button_row, text="取消", style="TButton", command=dialog.destroy
        ).pack(side="right", padx=(0, 10))

    def _open_settings(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("设置")
        dialog.geometry("720x780")
        dialog.minsize(620, 600)
        dialog.configure(fg_color=BG)
        dialog.transient(self)
        dialog.grab_set()

        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True, padx=SPACE_MD, pady=SPACE_MD)

        config = ensure_config(CONFIG_PATH)
        entries = {}
        source_vars = []

        def section_title(text):
            ctk.CTkLabel(body, text=text, text_color=ACCENT, font=section_font(), anchor="w").pack(fill="x", pady=(SPACE_SM, SPACE_XS))

        def add_entry(label, key, secret=False):
            row = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=SPACE_XS)
            ctk.CTkLabel(row, text=label, text_color=TEXT, font=small_font(), width=180, anchor="w").pack(side="left", padx=SPACE_SM, pady=SPACE_XS)
            entry = ctk.CTkEntry(
                row,
                show="*" if secret else "",
                height=36,
                corner_radius=RADIUS_CONTROL,
                fg_color=BG,
                border_color=BORDER,
                text_color=TEXT,
                font=body_font(),
            )
            entry.insert(0, str(config.get(key, "")))
            entry.pack(side="left", fill="x", expand=True, padx=(0, SPACE_SM), pady=SPACE_XS)
            entries[key] = entry
            return entry

        def combo_field(label, values, value):
            row = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=SPACE_XS)
            ctk.CTkLabel(row, text=label, text_color=TEXT, font=small_font(), width=180, anchor="w").pack(side="left", padx=SPACE_SM, pady=SPACE_XS)
            var = tk.StringVar(value=value)
            combo = ctk.CTkComboBox(
                row,
                variable=var,
                values=values,
                state="readonly",
                height=36,
                corner_radius=RADIUS_CONTROL,
                fg_color=BG,
                border_color=BORDER,
                text_color=TEXT,
                dropdown_font=small_font(),
                font=small_font(),
            )
            combo.pack(side="left", fill="x", expand=True, padx=(0, SPACE_SM), pady=SPACE_XS)
            return var, combo

        def number_field(label, var, minimum, maximum):
            row = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
            row.pack(fill="x", pady=SPACE_XS)
            ctk.CTkLabel(row, text=label, text_color=TEXT, font=small_font(), width=180, anchor="w").pack(side="left", padx=SPACE_SM, pady=SPACE_XS)

            def adjust(delta):
                try:
                    current = int(var.get())
                except ValueError:
                    current = minimum
                var.set(str(max(minimum, min(maximum, current + delta))))

            ctk.CTkButton(row, text="−", width=34, height=34, corner_radius=RADIUS_CONTROL, fg_color=SURFACE_ALT, hover_color=BORDER, text_color=TEXT, command=lambda: adjust(-1)).pack(side="left", padx=(0, SPACE_XS))
            entry = ctk.CTkEntry(row, textvariable=var, width=80, height=34, corner_radius=RADIUS_CONTROL, fg_color=BG, border_color=BORDER, text_color=TEXT, font=body_font(), justify="center")
            entry.pack(side="left")
            ctk.CTkButton(row, text="＋", width=34, height=34, corner_radius=RADIUS_CONTROL, fg_color=SURFACE_ALT, hover_color=BORDER, text_color=TEXT, command=lambda: adjust(1)).pack(side="left", padx=(SPACE_XS, SPACE_SM))
            return entry

        def build_beginner_guide():
            guide_card = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
            guide_card.pack(fill="x", pady=(0, SPACE_SM))

            guide_content = ctk.CTkFrame(guide_card, fg_color="transparent")
            guide_open = tk.BooleanVar(value=True)

            def toggle_guide():
                if guide_open.get():
                    guide_content.pack_forget()
                    toggle_button.configure(text="新手如何填写 API  ＋")
                    guide_open.set(False)
                else:
                    guide_content.pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_SM))
                    toggle_button.configure(text="新手如何填写 API  −")
                    guide_open.set(True)

            toggle_button = ctk.CTkButton(
                guide_card,
                text="新手如何填写 API  −",
                height=40,
                corner_radius=RADIUS_CONTROL,
                fg_color="transparent",
                hover_color=SURFACE_ALT,
                text_color=TEXT,
                font=small_font(),
                anchor="w",
                command=toggle_guide,
            )
            toggle_button.pack(fill="x", padx=SPACE_XS, pady=(SPACE_XS, 0))

            guide_content.pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_SM))

            def guide_text(text, color=TEXT, font_=caption_font()):
                ctk.CTkLabel(guide_content, text=text, text_color=color, font=font_, wraplength=620, justify="left").pack(anchor="w", pady=(0, 2))

            ctk.CTkLabel(guide_content, text="DeepSeek API Key", text_color=ACCENT, font=small_font(), anchor="w").pack(anchor="w", pady=(SPACE_XS, 2))
            guide_text("必填。负责 AI 翻译、词汇分析、难句辅助和背景解释。")
            guide_text("注册 DeepSeek 开放平台后，在 API Keys 页面创建 Key，通常以 sk- 开头。")
            guide_text("Base URL 默认使用 https://api.deepseek.com/v1，模型默认使用 deepseek-chat。")
            ctk.CTkButton(
                guide_content,
                text="DeepSeek API Keys →",
                height=32,
                corner_radius=RADIUS_CONTROL,
                fg_color="transparent",
                hover_color=SURFACE_ALT,
                text_color=LINK,
                font=caption_font(),
                command=lambda: webbrowser.open("https://platform.deepseek.com/api_keys"),
            ).pack(anchor="w", pady=(SPACE_XS, SPACE_SM))

            ctk.CTkLabel(guide_content, text="Firecrawl API Key", text_color=ACCENT, font=small_font(), anchor="w").pack(anchor="w", pady=(0, 2))
            guide_text("可选。作为抓取失败时的兜底服务。")
            guide_text("可以留空；留空时使用直接抓取，若本机 Firecrawl CLI 已登录则自动使用 CLI。")
            guide_text("注册 Firecrawl 后，在 Dashboard 的 API Keys 页面创建 Key，通常以 fc- 开头。")
            ctk.CTkButton(
                guide_content,
                text="Firecrawl 官网 →",
                height=32,
                corner_radius=RADIUS_CONTROL,
                fg_color="transparent",
                hover_color=SURFACE_ALT,
                text_color=LINK,
                font=caption_font(),
                command=lambda: webbrowser.open("https://www.firecrawl.dev/"),
            ).pack(anchor="w", pady=(SPACE_XS, 0))

        build_beginner_guide()

        section_title("AI 与抓取")
        add_entry("DeepSeek API Key", "openai_api_key", secret=True)
        add_entry("DeepSeek Base URL", "openai_base_url")
        add_entry("模型", "model")
        add_entry("Firecrawl API Key", "firecrawl_api_key", secret=True)
        mode_var, _mode_combo = combo_field("抓取模式", ("auto", "direct", "firecrawl"), str(config.get("scrape_mode", "auto")))

        section_title("抓取控制")
        max_var = tk.StringVar(value=str(config.get("max_articles", 5)))
        number_field("每日最多篇数", max_var, 1, 20)
        timeout_var = tk.StringVar(value=str(config.get("request_timeout", 30)))
        number_field("请求超时（秒）", timeout_var, 5, 120)
        add_entry("每日定时（HH:MM）", "schedule_time")

        section_title("来源管理")
        source_container = ctk.CTkFrame(body, fg_color="transparent")
        source_container.pack(fill="x")

        def render_sources():
            sources = config.get("sources", [])
            for index, enabled_var, limit_var in source_vars:
                if index < len(sources):
                    try:
                        sources[index]["enabled"] = bool(enabled_var.get())
                        sources[index]["limit"] = max(1, int(limit_var.get()))
                    except ValueError:
                        pass
            for child in source_container.winfo_children():
                child.destroy()
            source_vars.clear()

            for index, source in enumerate(sources):
                row = ctk.CTkFrame(source_container, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
                row.pack(fill="x", pady=SPACE_XS)
                enabled_var = tk.BooleanVar(value=bool(source.get("enabled", True)))
                limit_var = tk.StringVar(value=str(source.get("limit", 5)))
                ctk.CTkSwitch(row, text="启用爬取", variable=enabled_var, fg_color=SURFACE_ALT, progress_color=ACCENT, button_color=SURFACE, text_color=MUTED, font=small_font()).pack(side="left", padx=SPACE_SM, pady=SPACE_SM)
                ctk.CTkLabel(row, text=source.get("name", f"来源 {index + 1}"), text_color=TEXT, font=card_title_font(), anchor="w").pack(side="left", padx=(SPACE_XS, SPACE_SM), pady=SPACE_SM)
                ctk.CTkLabel(row, text=f"{REGION_NAMES.get(source.get('region', ''), '')} · {PERIOD_NAMES.get(source.get('period', ''), '')}", text_color=MUTED, font=caption_font()).pack(side="left", padx=(0, SPACE_SM))
                ctk.CTkLabel(row, text="上限", text_color=MUTED, font=small_font()).pack(side="left", padx=(SPACE_SM, SPACE_XS))
                limit_entry = ctk.CTkEntry(row, textvariable=limit_var, width=60, height=34, corner_radius=RADIUS_CONTROL, fg_color=BG, border_color=BORDER, text_color=TEXT, font=body_font(), justify="center")
                limit_entry.pack(side="left")
                ctk.CTkButton(row, text="删除", width=56, height=30, corner_radius=RADIUS_CONTROL, fg_color="transparent", hover_color="#F7E1DC", text_color=DANGER, font=small_font(), command=lambda idx=index: delete_source(idx)).pack(side="right", padx=SPACE_SM, pady=SPACE_SM)
                source_vars.append((index, enabled_var, limit_var))

        def delete_source(index):
            sources = config.get("sources", [])
            if index < 0 or index >= len(sources):
                return
            source = sources[index]
            if not modal_confirm(
                dialog,
                "删除来源",
                f"确定删除来源「{source.get('name', '')}」吗？\n\n只会从设置中移除该来源，已抓取的文章不会删除。",
            ):
                return
            sources.pop(index)
            render_sources()

        def add_source_form():
            form = ctk.CTkToplevel(dialog)
            form.title("新增来源")
            form.geometry("560x520")
            form.minsize(500, 480)
            form.configure(fg_color=BG)
            form.transient(dialog)
            form.grab_set()

            form_body = ctk.CTkFrame(form, fg_color="transparent")
            form_body.pack(fill="both", expand=True, padx=SPACE_MD, pady=SPACE_MD)
            ctk.CTkLabel(form_body, text="新增来源", text_color=TEXT, font=title_font(), anchor="w").pack(anchor="w")
            ctk.CTkLabel(form_body, text="保存后将参与全局刷新与每日定时任务", text_color=MUTED, font=small_font(), anchor="w").pack(anchor="w", pady=(2, SPACE_SM))

            def field_row(label):
                row = ctk.CTkFrame(form_body, fg_color="transparent")
                row.pack(fill="x", pady=SPACE_XS)
                ctk.CTkLabel(row, text=label, text_color=TEXT, font=small_font(), width=110, anchor="w").pack(side="left")
                return row

            name_row = field_row("显示名称")
            name_var = tk.StringVar()
            ctk.CTkEntry(name_row, textvariable=name_var, height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, font=body_font()).pack(side="left", fill="x", expand=True)

            url_row = field_row("网址")
            url_var = tk.StringVar()
            ctk.CTkEntry(url_row, textvariable=url_var, height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, font=body_font()).pack(side="left", fill="x", expand=True)

            region_row = field_row("区域")
            region_var = tk.StringVar(value="新闻")
            ctk.CTkComboBox(region_row, variable=region_var, values=("新闻", "美食", "文化"), state="readonly", height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, dropdown_font=small_font(), font=small_font()).pack(side="left", fill="x", expand=True)

            period_row = field_row("周期")
            period_var = tk.StringVar(value="日刊")
            ctk.CTkComboBox(period_row, variable=period_var, values=("日刊", "月刊"), state="readonly", height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, dropdown_font=small_font(), font=small_font()).pack(side="left", fill="x", expand=True)

            type_row = field_row("来源类型")
            type_var = tk.StringVar(value="列表页")
            type_combo = ctk.CTkComboBox(type_row, variable=type_var, values=("单篇文章", "列表页"), state="readonly", height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, dropdown_font=small_font(), font=small_font(), command=lambda _value: on_type_change())
            type_combo.pack(side="left", fill="x", expand=True)

            limit_row = field_row("单次上限")
            limit_var = tk.StringVar(value="10")
            ctk.CTkEntry(limit_row, textvariable=limit_var, width=120, height=36, corner_radius=RADIUS_CONTROL, fg_color=SURFACE, border_color=BORDER, text_color=TEXT, font=body_font()).pack(side="left")

            def on_type_change():
                if type_var.get() == "单篇文章" and limit_var.get() in ("", "10"):
                    limit_var.set("1")
                elif type_var.get() == "列表页" and limit_var.get() == "1":
                    limit_var.set("10")

            def submit():
                name = name_var.get().strip()
                url = url_var.get().strip()
                if not name:
                    modal_error(form, "输入错误", "请填写来源名称")
                    return
                if not re.match(r"^https?://", url, flags=re.IGNORECASE):
                    modal_error(form, "输入错误", "网址必须以 http:// 或 https:// 开头")
                    return
                try:
                    limit = max(1, min(50, int(limit_var.get())))
                except ValueError:
                    modal_error(form, "输入错误", "单次上限必须是 1-50 的数字")
                    return
                normalized_url = url.rstrip("/")
                for source in config.get("sources", []):
                    if str(source.get("url", "")).rstrip("/") == normalized_url:
                        modal_error(form, "输入错误", "该网址已存在，请勿重复添加")
                        return
                region = next((key for key, label in REGIONS if label == region_var.get()), "news")
                period = "monthly" if period_var.get() == "月刊" else "daily"
                adapter = "single_url" if type_var.get() == "单篇文章" else "list_page"
                used_ids = {str(source.get("id", "")) for source in config.get("sources", []) if isinstance(source, dict)}
                while True:
                    source_id = "user_" + secrets.token_hex(4)
                    if source_id in used_ids:
                        continue
                    if any((OUTPUT_DIR / region_key / source_id).exists() for region_key in REGION_NAMES):
                        continue
                    break
                config.setdefault("sources", []).append(
                    {"id": source_id, "name": name, "region": region, "period": period, "adapter": adapter, "url": url, "enabled": True, "limit": limit}
                )
                render_sources()
                form.destroy()

            button_row = ctk.CTkFrame(form, fg_color="transparent")
            button_row.pack(fill="x", side="bottom", padx=SPACE_MD, pady=SPACE_SM)
            ctk.CTkButton(button_row, text="添加", height=36, corner_radius=RADIUS_CONTROL, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=SURFACE, font=small_font(), command=submit).pack(side="right")
            ctk.CTkButton(button_row, text="取消", height=36, corner_radius=RADIUS_CONTROL, fg_color="transparent", hover_color=SURFACE_ALT, text_color=MUTED, font=small_font(), command=form.destroy).pack(side="right", padx=(0, SPACE_XS))

        render_sources()
        ctk.CTkButton(body, text="＋ 新增来源", height=36, corner_radius=RADIUS_CONTROL, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=SURFACE, font=small_font(), command=add_source_form).pack(anchor="w", pady=(SPACE_XS, 0))

        ctk.CTkLabel(body, text="提示：Firecrawl Key 可留空；留空时直连失败会跳过 Firecrawl，CLI 已登录的电脑会自动使用 CLI。", text_color=MUTED, font=caption_font(), wraplength=560, justify="left").pack(anchor="w", pady=(SPACE_SM, 0))

        button_row = ctk.CTkFrame(dialog, fg_color="transparent")
        button_row.pack(fill="x", side="bottom", padx=SPACE_MD, pady=SPACE_SM)

        def save():
            updated = config
            updated["openai_api_key"] = entries["openai_api_key"].get().strip()
            updated["openai_base_url"] = entries["openai_base_url"].get().strip() or "https://api.deepseek.com/v1"
            updated["model"] = entries["model"].get().strip() or "deepseek-chat"
            updated["firecrawl_api_key"] = entries["firecrawl_api_key"].get().strip()
            schedule_time = validate_schedule_time(entries["schedule_time"].get())
            if not schedule_time:
                modal_error(dialog, "设置错误", "定时时间必须是 HH:MM 格式")
                return
            updated["schedule_time"] = schedule_time
            updated["scrape_mode"] = mode_var.get()
            try:
                updated["max_articles"] = max(1, int(max_var.get()))
                updated["request_timeout"] = max(5, int(timeout_var.get()))
                updated_sources = updated.get("sources") or []
                for index, enabled_var, limit_var in source_vars:
                    if index < len(updated_sources):
                        updated_sources[index]["enabled"] = bool(enabled_var.get())
                        updated_sources[index]["limit"] = max(1, int(limit_var.get()))
            except ValueError:
                modal_error(dialog, "设置错误", "篇数、超时和来源上限必须是数字")
                return
            save_config(updated, CONFIG_PATH)
            if updated.get("auto_schedule"):
                try:
                    create_or_update_task(updated["schedule_time"])
                except Exception as exc:
                    modal_error(dialog, "定时任务更新失败", str(exc))
            self.config_data = updated
            self._load_schedule_setting()
            self._set_status("设置已保存")
            dialog.destroy()
            self.refresh_dates()

        ctk.CTkButton(button_row, text="关于", height=38, corner_radius=RADIUS_CONTROL, fg_color="transparent", hover_color=SURFACE_ALT, text_color=MUTED, font=small_font(), command=lambda: self._open_about(dialog)).pack(side="left")
        ctk.CTkButton(button_row, text="保存并关闭", height=38, corner_radius=RADIUS_CONTROL, fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=SURFACE, font=small_font(), command=save).pack(side="right")
        ctk.CTkButton(button_row, text="取消", height=38, corner_radius=RADIUS_CONTROL, fg_color="transparent", hover_color=SURFACE_ALT, text_color=MUTED, font=small_font(), command=dialog.destroy).pack(side="right", padx=(0, SPACE_XS))

    def _open_about(self, parent=None):
        dialog = ctk.CTkToplevel(parent or self)
        dialog.title("关于言叶")
        dialog.geometry("760x860")
        dialog.minsize(640, 720)
        dialog.configure(fg_color=BG)
        if parent is not None:
            dialog.transient(parent)
        dialog.grab_set()

        body = ctk.CTkScrollableFrame(dialog, fg_color="transparent", corner_radius=0)
        body.pack(fill="both", expand=True, padx=SPACE_MD, pady=SPACE_MD)

        top_bar = ctk.CTkFrame(body, fg_color="transparent")
        top_bar.pack(fill="x", pady=(0, SPACE_SM))
        ctk.CTkButton(
            top_bar,
            text="← 返回设置",
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=MUTED,
            font=small_font(),
            command=dialog.destroy,
        ).pack(side="left")

        hero = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
        hero.pack(fill="x", pady=(0, SPACE_XS))

        self.about_mascot_image = None
        logo_path = _resource_path("assets/logo.png")
        if logo_path.is_file() and Image is not None:
            try:
                self.about_mascot_image = ctk.CTkImage(
                    light_image=Image.open(logo_path),
                    dark_image=None,
                    size=(120, 120),
                )
            except Exception:
                self.about_mascot_image = None
        if self.about_mascot_image is not None:
            ctk.CTkLabel(hero, image=self.about_mascot_image, text="").pack(pady=(SPACE_MD, SPACE_XS))

        ctk.CTkLabel(hero, text=APP_NAME, text_color=TEXT, font=hero_font()).pack()
        ctk.CTkLabel(hero, text=APP_ROMANJI, text_color=ACCENT, font=small_font()).pack(pady=(2, 0))
        ctk.CTkLabel(hero, text="用英文阅读世界", text_color=MUTED, font=body_font()).pack(pady=(SPACE_XS, 0))
        ctk.CTkLabel(hero, text=f"Version {APP_VERSION}", text_color=MUTED, font=caption_font()).pack(pady=(4, SPACE_MD))

        def section_card(title):
            card = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=RADIUS_CARD, border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=SPACE_XS)
            ctk.CTkLabel(card, text=title, text_color=ACCENT, font=section_font(), anchor="w").pack(
                fill="x", padx=SPACE_SM, pady=(SPACE_SM, SPACE_XS)
            )
            return card

        def paragraph(parent, text, color=TEXT, font_=body_font()):
            ctk.CTkLabel(
                parent,
                text=text,
                text_color=color,
                font=font_,
                wraplength=560,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_XS))

        about = section_card("关于言叶")
        paragraph(about, "“言叶”是一个通过英文新闻、文化与生活内容辅助英语学习的个人 AI 应用。")
        paragraph(about, "它诞生于一个很简单的想法：", MUTED)
        paragraph(about, "如果每天阅读真正感兴趣的英文内容，英语学习也可以成为一种日常。", TEXT, font(14, "bold"))
        paragraph(about, "目前应用支持从多个英文媒体获取内容，并通过 AI 提供翻译、词汇分析、难句辅助和文化背景等学习功能。")

        author = section_card("作者")
        ctk.CTkLabel(author, text="水野凪", text_color=TEXT, font=font(18, "bold"), anchor="w").pack(
            fill="x", padx=SPACE_SM, pady=(SPACE_SM, SPACE_XS)
        )
        paragraph(author, "一个喜欢日本文化、英语学习与 AI 的大学生。")
        paragraph(author, "“言叶”是一个个人项目，也是一次关于“一个人能否借助 AI 做出真正可用的软件”的尝试。")
        author_links = ctk.CTkFrame(author, fg_color="transparent")
        author_links.pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_SM))
        ctk.CTkButton(
            author_links,
            text="X 主页 →",
            height=34,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=LINK,
            font=small_font(),
            command=lambda: webbrowser.open(X_URL),
        ).pack(side="left")

        ai_dev = section_card("AI-assisted Development")
        paragraph(ai_dev, "“言叶”的大部分程序代码由 AI 辅助生成。")
        paragraph(ai_dev, "作者负责产品构思、功能设计、实际测试、用户体验反馈以及迭代决策。")
        paragraph(ai_dev, "AI 是“言叶”的开发工具，而不是项目的作者。")

        config = ensure_config(CONFIG_PATH)

        sources = section_card("内容来源")
        paragraph(sources, "本应用会从多个英文媒体及公开网络来源获取文章信息，用于英语阅读与学习辅助。")
        paragraph(sources, "第三方文章、图片及其他内容的版权归其原作者及相应权利人所有。")
        paragraph(sources, "“言叶”不主张拥有第三方内容的版权。")
        source_list = ctk.CTkFrame(sources, fg_color="transparent")
        source_list.pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_SM))
        enabled_names = []
        for source in config.get("sources", []):
            if not isinstance(source, dict) or not source.get("enabled", True):
                continue
            name = str(source.get("name", "")).strip()
            if name and name not in enabled_names:
                enabled_names.append(name)
        if enabled_names:
            for name in enabled_names:
                Pill(source_list, name, fg_color=SURFACE_ALT, text_color=MUTED).pack(anchor="w", pady=(0, SPACE_XS))
        else:
            ctk.CTkLabel(source_list, text="暂无启用来源", text_color=MUTED, font=body_font()).pack(anchor="w")

        model = str(config.get("model", "")).strip() or "deepseek-chat"
        base_url = str(config.get("openai_base_url", "")).lower()
        service_name = "DeepSeek" if ("deepseek" in base_url or "deepseek" in model.lower()) else (model or "OpenAI-compatible API")

        ai_service = section_card("AI 服务")
        ctk.CTkLabel(ai_service, text=f"{service_name} · {model}", text_color=TEXT, font=card_title_font(), anchor="w").pack(
            fill="x", padx=SPACE_SM, pady=(SPACE_SM, SPACE_XS)
        )
        for item in ("文章翻译", "词汇分析", "难句辅助", "文章背景解释"):
            ctk.CTkLabel(ai_service, text=f"• {item}", text_color=TEXT, font=body_font(), anchor="w").pack(
                fill="x", padx=SPACE_SM, pady=(0, SPACE_XS)
            )
        ctk.CTkLabel(
            ai_service,
            text="AI 生成内容仅供学习参考，可能存在错误，请结合原文进行判断。",
            text_color=MUTED,
            font=caption_font(),
            justify="left",
            anchor="w",
            wraplength=560,
        ).pack(fill="x", padx=SPACE_SM, pady=(0, SPACE_SM))

        open_source = section_card("Open Source")
        paragraph(open_source, "本项目是一个个人开发项目。")
        ctk.CTkButton(
            open_source,
            text="GitHub →",
            height=36,
            corner_radius=RADIUS_CONTROL,
            fg_color="transparent",
            hover_color=SURFACE_ALT,
            text_color=LINK,
            font=small_font(),
            command=lambda: webbrowser.open(GITHUB_URL),
        ).pack(anchor="w", padx=SPACE_SM, pady=(0, SPACE_SM))

        thanks = section_card("Special Thanks")
        paragraph(thanks, "感谢所有提供英文内容的媒体与作者。")
        paragraph(thanks, "感谢开源社区提供的工具与技术。")
        paragraph(thanks, "也感谢 AI，让一个普通的个人开发者能够把脑海里的想法逐渐变成真正可以使用的软件。")

    def _schedule_tick(self):
        if self.auto_schedule_var.get():
            now = datetime.now()
            today = now.date().isoformat()
            if (
                now.strftime("%H:%M") == self.schedule_time
                and self._scheduled_date != today
            ):
                self._scheduled_date = today
                if not self.job_running:
                    self._start_job()
        self.after(1000, self._schedule_tick)


def _first_title(raw):
    for line in raw.splitlines():
        if line.startswith("# "):
            return re.sub(r"^\d+\.\s+", "", line[2:].strip())
    return ""


def _first_summary(raw):
    lines = raw.splitlines()
    started = False
    collected = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## 原文":
            started = True
            continue
        if started:
            if stripped.startswith("#"):
                break
            if stripped.startswith("![") or stripped.startswith("- !["):
                continue
            if stripped:
                collected.append(stripped)
            elif collected:
                break
    return " ".join(" ".join(collected).split())[:140]


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        app = DigestApp()
        app.update_idletasks()
        app.refresh_dates()
        app.update_idletasks()
        if app.all_articles:
            app._open_article(app.all_articles[0])
            app.update_idletasks()
        app.destroy()
        marker = Path(os.environ.get("TEMP", ".")) / "japan-news-study-smoke-ok.txt"
        marker.write_text("ok", encoding="utf-8")
        os._exit(0)
    elif "--scheduled-job" in sys.argv:
        base_dir = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent
        )
        configure_logging(base_dir)
        try:
            run_refresh_job()
            logging.getLogger(__name__).info("Scheduled refresh completed")
        except SystemExit as exc:
            logging.getLogger(__name__).warning("Scheduled refresh skipped: %s", exc)
        except Exception:
            logging.getLogger(__name__).exception("Scheduled refresh failed")
        sys.exit(0)
    else:
        app = DigestApp()
        app.mainloop()
