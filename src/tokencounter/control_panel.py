"""Tkinter-based control panel for TokenCounter."""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
from collections.abc import Callable, Mapping
from typing import Any

from tokencounter import __app_name__, __version__
from tokencounter.config import Config
from tokencounter.utils import get_screen_rect

logger = logging.getLogger("tokencounter")

WINDOW_WIDTH = 1080
WINDOW_HEIGHT = 800
PANEL_MARGIN_X = 8
PANEL_MARGIN_Y = 8
PANEL_RADIUS = 44
PANEL_CONTENT_INSET = 12
PANEL_PADDING_X = 26
PANEL_PADDING_Y = 18
BLACKLIST_SAVE_DEBOUNCE_MS = 500
THEME_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
THEME_REGISTRY_VALUE = "AppsUseLightTheme"
SUPPORTED_DURATIONS = (1.0, 2.0, 3.0, 5.0)

WINDOW_BG = "#010203"
CHECK_GLYPH = "\u2713"
RADIO_SELECTED_GLYPH = "\u25cf"
RADIO_UNSELECTED_GLYPH = "\u25cb"
CHEVRON_COLLAPSED = "\u25b8"
CHEVRON_EXPANDED = "\u25be"
RADIO_UNSELECTED_ICON_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAARnQU1BAACx"
    "jwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAEqSURBVDhP1VMhUEMxDJ1ETiInkUjkJHISiUQikX"
    "OTk8hJJHJychKJRCLbJmm+LPf62x3NVnbcYXh3/3aXl7y8Jtlk8m/gnJsyD/PAcUkUX8rvwrlhZnO7"
    "yAKkn8Sa7BcoDiHER1tzBE/yVIqcp/jgRK4RJ6Irz3oXWN+zIOtrSunC1mfASRHZi8il5QEUM+vzKB"
    "aXls8zKc9xPZEKiBHpG55ZHR+AQeYuQe4booMQ4s1JV8zDCsRvtgL3mJUNbmG1CZ4BZkkcP9qg6Hp0"
    "5KYN8QMgArEmiFVDyHu5bYgO0DBvWHTdELiTTJDuGqKDegJYkuUOAz/ahAFcl3vbWi6j3kdNsvc0Hu"
    "PY7Oy9lbdvSnLKAyXdfWtwskkXsF/msC+zg9AG/zeb+6f4AsLgeWvrB+2iAAAAAElFTkSuQmCC"
)
RADIO_SELECTED_ICON_DATA = (
    "iVBORw0KGgoAAAANSUhEUgAAABIAAAASCAYAAABWzo5XAAAAAXNSR0IArs4c6QAAAARnQU1BAACx"
    "jwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAADKSURBVDhP5ZI9DoJAFIQpLS09AqWlpUfwCJaWlp"
    "Z2HoHSY3AEj2K5vJ9dyjVvE8wyLITSxC+ZipnJg6Gq/hdmrkX6o1Pd47NVEOmZJTiWEAcR+75jvaF3"
    "FpbQ5gUFvWKMG8yN6NhfCsGJRPoHZkfY+Riak6ruMJ+wD4rmRbE/YUdi7WsNIvF37EjYzGheki2LHQ"
    "lbAs2LYq6x44tIaCaBslrMjrCriMO7EMzlZhfLcc5tWcKzUJAuWVWSY7+DLWnrEPkrkT+g53f5AOCy"
    "43JGNlpkAAAAAElFTkSuQmCC"
)

PALETTE = {
    "window_bg": WINDOW_BG,
    "panel_bg": "#2b2d33",
    "panel_border": "#2b2d33",
    "divider": "#6d6f77",
    "text": "#f4f5f8",
    "muted": "#d5d7de",
    "subtle": "#a8abb4",
    "radio_on": "#111317",
    "radio_off": "#f2f3f6",
    "primary": "#57a7ff",
    "primary_hover": "#75b8ff",
    "primary_border": "#9accff",
    "primary_text": "#f6fbff",
    "secondary": "#3d3f47",
    "secondary_hover": "#4b4e58",
    "secondary_border": "#636670",
    "secondary_text": "#f2f3f6",
    "text_bg": "#24262b",
    "text_border": "#4e5159",
}


@dataclasses.dataclass(frozen=True)
class PanelState:
    app_name: str
    version: str
    subtitle: str
    status_text: str
    trigger_text: str
    enabled: bool
    startup_enabled: bool
    tokenizer: str
    tokenizer_options: list[tuple[str, str]]
    tooltip_display_s: float
    blacklist_text: str


def normalize_blacklist(value: str | list[str]) -> list[str]:
    """Normalize blacklist input into a deduplicated process-name list."""

    lines = value.splitlines() if isinstance(value, str) else value
    normalized: list[str] = []
    seen: set[str] = set()
    for line in lines:
        item = line.strip()
        if not item:
            continue
        lowered = item.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(item)
    return normalized


def blacklist_to_text(blacklist: list[str]) -> str:
    return "\n".join(blacklist)


def get_system_theme(*, registry: Any | None = None) -> str:
    """Return `light` or `dark` based on the user's Windows app theme."""

    if registry is None:
        import winreg

        registry = winreg

    try:
        with registry.OpenKey(
            registry.HKEY_CURRENT_USER,
            THEME_REGISTRY_PATH,
            0,
            registry.KEY_READ,
        ) as key:
            value, _ = registry.QueryValueEx(key, THEME_REGISTRY_VALUE)
    except (FileNotFoundError, OSError, AttributeError):
        return "light"

    return "light" if bool(value) else "dark"


def duration_to_choice(value: float) -> float:
    """Map any stored duration value to the nearest supported radio option."""

    return min(SUPPORTED_DURATIONS, key=lambda candidate: (abs(candidate - value), candidate))


def format_duration_label(value: float) -> str:
    whole = int(value)
    unit = "Second" if whole == 1 else "Seconds"
    return f"{whole} {unit}"


def build_tokenizer_display_map(options: list[tuple[str, str]]) -> dict[str, str]:
    return {encoding_name: label for encoding_name, label in options}


def toggle_advanced(is_expanded: bool) -> bool:
    return not is_expanded


def build_panel_state(
    config: Config,
    *,
    startup_enabled: bool,
    providers: Mapping[str, Any],
    app_name: str = __app_name__,
    version: str = __version__,
) -> PanelState:
    """Build a UI-friendly view model from the current runtime state."""

    status_text = (
        "Enabled - listening for double Ctrl"
        if config.enabled
        else "Paused - monitoring disabled"
    )
    options = [(encoding_name, provider.name) for encoding_name, provider in providers.items()]
    return PanelState(
        app_name=app_name,
        version=version,
        subtitle="Local token counter control panel",
        status_text=status_text,
        trigger_text="Trigger: double-press Ctrl",
        enabled=config.enabled,
        startup_enabled=startup_enabled,
        tokenizer=config.tokenizer,
        tokenizer_options=options,
        tooltip_display_s=config.tooltip_display_s,
        blacklist_text=blacklist_to_text(config.blacklist),
    )


def _rounded_polygon_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    return [
        x1 + r, y1,
        x2 - r, y1,
        x2, y1,
        x2, y1 + r,
        x2, y2 - r,
        x2, y2,
        x2 - r, y2,
        x1 + r, y2,
        x1, y2,
        x1, y2 - r,
        x1, y1 + r,
        x1, y1,
    ]


class ControlPanel:
    """Single-instance Tkinter control panel running on its own UI thread."""

    def __init__(
        self,
        *,
        state_provider: Callable[[], PanelState],
        on_enabled_changed: Callable[[bool], None],
        on_startup_changed: Callable[[bool], None],
        on_tokenizer_changed: Callable[[str], None],
        on_tooltip_duration_changed: Callable[[float], None],
        on_blacklist_changed: Callable[[list[str]], None],
        on_clipboard_calculate: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._state_provider = state_provider
        self._on_enabled_changed = on_enabled_changed
        self._on_startup_changed = on_startup_changed
        self._on_tokenizer_changed = on_tokenizer_changed
        self._on_tooltip_duration_changed = on_tooltip_duration_changed
        self._on_blacklist_changed = on_blacklist_changed
        self._on_clipboard_calculate = on_clipboard_calculate
        self._on_exit = on_exit

        self._commands: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

        self._tk = None
        self._root = None
        self._window_built = False
        self._advanced_expanded = False

        self._current_state: PanelState | None = None
        self._selected_tokenizer = ""
        self._selected_duration = 2.0
        self._enabled = False
        self._startup_enabled = False
        self._blacklist_dirty = False

        self._shell_canvas = None
        self._panel_frame = None
        self._scroll_canvas = None
        self._scroll_window = None
        self._scroll_frame = None
        self._advanced_toggle = None
        self._advanced_chevron = None
        self._advanced_content = None
        self._blacklist_text = None
        self._status_label = None
        self._trigger_label = None
        self._version_label = None
        self._tokenizer_section = None
        self._enabled_indicator = None
        self._enabled_label = None
        self._startup_indicator = None
        self._startup_label = None
        self._tokenizer_rows: dict[str, tuple[Any, Any, Any]] = {}
        self._duration_rows: dict[float, tuple[Any, Any, Any]] = {}
        self._tokenizer_display_map: dict[str, str] = {}
        self._radio_icon_unselected = None
        self._radio_icon_selected = None

        self._blacklist_after_id = None
        self._fade_after_id = None
        self._drag_pointer_origin: tuple[int, int] | None = None
        self._drag_window_origin: tuple[int, int] | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._ui_thread_main, name="ControlPanelThread", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)

    def show(self) -> None:
        self._enqueue("show")

    def hide(self) -> None:
        self._enqueue("hide")

    def refresh(self) -> None:
        self._enqueue("refresh")

    def stop(self) -> None:
        if not self._thread:
            return
        if threading.current_thread() is self._thread:
            self._shutdown_ui()
            return

        self._enqueue("shutdown")
        self._thread.join(timeout=3.0)
        self._thread = None

    def _enqueue(self, command: str, payload: object | None = None) -> None:
        self._commands.put((command, payload))

    def _ui_thread_main(self) -> None:
        import tkinter as tk

        self._tk = tk
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.resizable(False, False)
        root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        root.configure(bg=PALETTE["window_bg"])
        try:
            root.wm_attributes("-transparentcolor", PALETTE["window_bg"])
        except tk.TclError:
            root.configure(bg=PALETTE["panel_bg"])
        root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        root.bind("<Escape>", lambda _event: self._hide_window())
        root.bind_all("<MouseWheel>", self._handle_mousewheel, add="+")

        self._root = root
        root.after(50, self._process_commands)
        self._ready.set()

        try:
            root.mainloop()
        finally:
            self._reset_ui_references()
            self._thread = None

    def _process_commands(self) -> None:
        root = self._root
        if root is None:
            return

        while True:
            try:
                command, _payload = self._commands.get_nowait()
            except queue.Empty:
                break

            if command == "show":
                self._show_window()
            elif command == "hide":
                self._hide_window()
            elif command == "refresh":
                self._refresh_ui()
            elif command == "shutdown":
                self._shutdown_ui()
                return

        root.after(50, self._process_commands)

    def _show_window(self) -> None:
        root = self._root
        if root is None:
            return

        self._ensure_window()
        self._apply_state(self._state_provider())
        self._center_window()
        root.deiconify()
        root.lift()
        root.attributes("-alpha", 0.0)
        self._raise_to_front()
        self._start_fade_in()
        try:
            root.focus_force()
        except self._tk.TclError:
            pass

    def _hide_window(self) -> None:
        root = self._root
        if root is None:
            return

        self._commit_blacklist()
        self._cancel_blacklist_debounce()
        self._cancel_fade_in()
        root.withdraw()

    def _refresh_ui(self) -> None:
        if not self._window_built:
            return
        self._apply_state(self._state_provider())

    def _shutdown_ui(self) -> None:
        root = self._root
        if root is None:
            return

        self._commit_blacklist()
        self._cancel_blacklist_debounce()
        self._cancel_fade_in()
        try:
            root.unbind_all("<MouseWheel>")
        except self._tk.TclError:
            pass
        try:
            root.destroy()
        except self._tk.TclError:
            pass

    def _reset_ui_references(self) -> None:
        self._tk = None
        self._root = None
        self._window_built = False
        self._advanced_expanded = False
        self._current_state = None
        self._selected_tokenizer = ""
        self._selected_duration = 2.0
        self._enabled = False
        self._startup_enabled = False
        self._blacklist_dirty = False
        self._shell_canvas = None
        self._panel_frame = None
        self._scroll_canvas = None
        self._scroll_window = None
        self._scroll_frame = None
        self._advanced_toggle = None
        self._advanced_chevron = None
        self._advanced_content = None
        self._blacklist_text = None
        self._status_label = None
        self._trigger_label = None
        self._version_label = None
        self._tokenizer_section = None
        self._enabled_indicator = None
        self._enabled_label = None
        self._startup_indicator = None
        self._startup_label = None
        self._tokenizer_rows = {}
        self._duration_rows = {}
        self._tokenizer_display_map = {}
        self._radio_icon_unselected = None
        self._radio_icon_selected = None
        self._blacklist_after_id = None
        self._fade_after_id = None
        self._drag_pointer_origin = None
        self._drag_window_origin = None

    def _ensure_window(self) -> None:
        if self._window_built or self._root is None:
            return

        tk = self._tk
        root = self._root
        canvas_bg = root.cget("bg")

        self._shell_canvas = tk.Canvas(
            root,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            bg=canvas_bg,
            highlightthickness=0,
            bd=0,
        )
        self._shell_canvas.pack(fill="both", expand=True)
        self._shell_canvas.bind("<ButtonPress-1>", self._start_window_drag)
        self._shell_canvas.bind("<B1-Motion>", self._perform_window_drag)
        self._shell_canvas.bind("<ButtonRelease-1>", self._stop_window_drag)
        self._draw_shell()
        self._radio_icon_unselected = tk.PhotoImage(data=RADIO_UNSELECTED_ICON_DATA)
        self._radio_icon_selected = tk.PhotoImage(data=RADIO_SELECTED_ICON_DATA)

        panel_x = PANEL_MARGIN_X + PANEL_CONTENT_INSET
        panel_y = PANEL_MARGIN_Y + PANEL_CONTENT_INSET
        panel_width = WINDOW_WIDTH - (panel_x * 2)
        panel_height = WINDOW_HEIGHT - (panel_y * 2)
        self._panel_frame = tk.Frame(self._shell_canvas, bg=PALETTE["panel_bg"], bd=0, highlightthickness=0)
        self._shell_canvas.create_window(
            panel_x,
            panel_y,
            anchor="nw",
            width=panel_width,
            height=panel_height,
            window=self._panel_frame,
        )

        drag_strip = tk.Frame(self._panel_frame, bg=PALETTE["panel_bg"], height=6)
        drag_strip.pack(fill="x", padx=PANEL_PADDING_X, pady=(6, 0))
        drag_strip.pack_propagate(False)
        drag_strip.bind("<ButtonPress-1>", self._start_window_drag)
        drag_strip.bind("<B1-Motion>", self._perform_window_drag)
        drag_strip.bind("<ButtonRelease-1>", self._stop_window_drag)

        top = tk.Frame(self._panel_frame, bg=PALETTE["panel_bg"])
        top.pack(fill="x", padx=PANEL_PADDING_X, pady=(4, 0))
        self._build_enabled_row(top)
        self._trigger_label = tk.Label(
            top,
            text="Trigger: double-press Ctrl",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 18),
        )
        self._trigger_label.pack(anchor="w", pady=(12, 0))
        self._trigger_label.bind("<ButtonPress-1>", self._start_window_drag)
        self._trigger_label.bind("<B1-Motion>", self._perform_window_drag)
        self._trigger_label.bind("<ButtonRelease-1>", self._stop_window_drag)
        self._status_label = tk.Label(
            top,
            text="",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["subtle"],
            font=("Segoe UI", 9),
        )
        self._status_label.pack(anchor="w", pady=(4, 0))
        self._status_label.bind("<ButtonPress-1>", self._start_window_drag)
        self._status_label.bind("<B1-Motion>", self._perform_window_drag)
        self._status_label.bind("<ButtonRelease-1>", self._stop_window_drag)

        self._divider(self._panel_frame).pack(fill="x", padx=PANEL_PADDING_X, pady=(16, 14))

        scroll_host = tk.Frame(self._panel_frame, bg=PALETTE["panel_bg"])
        scroll_host.pack(fill="both", expand=True, padx=PANEL_PADDING_X)

        self._scroll_canvas = tk.Canvas(
            scroll_host,
            bg=PALETTE["panel_bg"],
            highlightthickness=0,
            bd=0,
            yscrollincrement=18,
        )
        self._scroll_canvas.pack(fill="both", expand=True)
        self._scroll_frame = tk.Frame(self._scroll_canvas, bg=PALETTE["panel_bg"])
        self._scroll_window = self._scroll_canvas.create_window(0, 0, anchor="nw", window=self._scroll_frame)
        self._scroll_canvas.bind("<Configure>", self._sync_scroll_width)
        self._scroll_frame.bind("<Configure>", self._sync_scroll_region)

        self._build_scroll_content()

        action_frame = tk.Frame(self._panel_frame, bg=PALETTE["panel_bg"])
        action_frame.pack(fill="x", padx=PANEL_PADDING_X, pady=(12, PANEL_PADDING_Y))

        left_actions = tk.Frame(action_frame, bg=PALETTE["panel_bg"])
        left_actions.pack(side="left")
        right_actions = tk.Frame(action_frame, bg=PALETTE["panel_bg"])
        right_actions.pack(side="right")

        self._create_action_button(
            left_actions,
            text="Calculate from Clipboard",
            width=392,
            height=54,
            fill=PALETTE["primary"],
            hover_fill=PALETTE["primary_hover"],
            text_color=PALETTE["primary_text"],
            border=PALETTE["primary_border"],
            command=self._handle_clipboard_calculate,
        ).pack(side="left")
        self._create_action_button(
            right_actions,
            text="Hide to Tray",
            width=164,
            height=54,
            fill=PALETTE["secondary"],
            hover_fill=PALETTE["secondary_hover"],
            text_color=PALETTE["secondary_text"],
            border=PALETTE["secondary_border"],
            command=self._hide_window,
        ).pack(side="left", padx=(0, 16))
        self._create_action_button(
            right_actions,
            text="Exit",
            width=138,
            height=54,
            fill=PALETTE["secondary"],
            hover_fill=PALETTE["secondary_hover"],
            text_color=PALETTE["secondary_text"],
            border=PALETTE["secondary_border"],
            command=self._handle_exit,
        ).pack(side="left")

        self._window_built = True
        self._root.after_idle(self._sync_scroll_region)

    def _draw_shell(self) -> None:
        canvas = self._shell_canvas
        if canvas is None:
            return

        canvas.delete("panel")
        self._create_rounded_rect(
            canvas,
            PANEL_MARGIN_X,
            PANEL_MARGIN_Y,
            WINDOW_WIDTH - PANEL_MARGIN_X,
            WINDOW_HEIGHT - PANEL_MARGIN_Y,
            PANEL_RADIUS,
            fill=PALETTE["panel_bg"],
            outline="",
            tags="panel",
        )

    def _build_scroll_content(self) -> None:
        tk = self._tk
        parent = self._scroll_frame

        tokenizer_section = tk.Frame(parent, bg=PALETTE["panel_bg"])
        tokenizer_section.pack(fill="x")
        self._section_title(tokenizer_section, "Tokenizer").pack(anchor="w", pady=(0, 10))
        self._tokenizer_section = tk.Frame(tokenizer_section, bg=PALETTE["panel_bg"])
        self._tokenizer_section.pack(fill="x")

        self._divider(parent).pack(fill="x", pady=(12, 12))

        duration_section = tk.Frame(parent, bg=PALETTE["panel_bg"])
        duration_section.pack(fill="x")
        self._section_title(duration_section, "Display Duration").pack(anchor="w", pady=(0, 10))
        for value in SUPPORTED_DURATIONS:
            row = self._create_option_row(
                duration_section,
                label=format_duration_label(value),
                command=lambda selected=value: self._handle_duration_selected(selected),
                font_size=15,
                indicator_size=20,
            )
            row[0].pack(anchor="w", fill="x", pady=(0, 4))
            self._duration_rows[value] = row

        self._divider(parent).pack(fill="x", pady=(10, 10))

        advanced = tk.Frame(parent, bg=PALETTE["panel_bg"])
        advanced.pack(fill="x", pady=(0, 6))
        self._build_advanced_section(advanced)

        bottom_pad = tk.Frame(parent, bg=PALETTE["panel_bg"], height=4)
        bottom_pad.pack(fill="x")

    def _build_enabled_row(self, parent: Any) -> None:
        row = self._tk.Frame(parent, bg=PALETTE["panel_bg"], cursor="hand2")
        row.pack(anchor="w")
        self._enabled_indicator = self._tk.Label(
            row,
            text=CHECK_GLYPH,
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Segoe UI Symbol", 25, "bold"),
            cursor="hand2",
        )
        self._enabled_indicator.pack(side="left")
        self._enabled_label = self._tk.Label(
            row,
            text="Enable",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Segoe UI", 22, "bold"),
            cursor="hand2",
        )
        self._enabled_label.pack(side="left", padx=(10, 0))

        for widget in (row, self._enabled_indicator, self._enabled_label):
            widget.bind("<Button-1>", lambda _event: self._handle_enabled_changed())

    def _build_advanced_section(self, parent: Any) -> None:
        tk = self._tk

        header = tk.Frame(parent, bg=PALETTE["panel_bg"], cursor="hand2")
        header.pack(fill="x")
        self._advanced_chevron = tk.Label(
            header,
            text=CHEVRON_COLLAPSED,
            bg=PALETTE["panel_bg"],
            fg=PALETTE["muted"],
            font=("Segoe UI Symbol", 14, "bold"),
            cursor="hand2",
        )
        self._advanced_chevron.pack(side="left")
        self._advanced_toggle = tk.Label(
            header,
            text="Advanced",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["muted"],
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        self._advanced_toggle.pack(side="left", padx=(8, 0))

        for widget in (header, self._advanced_chevron, self._advanced_toggle):
            widget.bind("<Button-1>", lambda _event: self._toggle_advanced())

        self._advanced_content = tk.Frame(parent, bg=PALETTE["panel_bg"])
        self._divider(self._advanced_content).pack(fill="x", pady=(12, 14))

        startup_row = self._create_option_row(
            self._advanced_content,
            label="Launch at startup",
            command=self._handle_startup_changed,
            font_size=13,
            indicator_size=18,
        )
        startup_row[0].pack(anchor="w", fill="x", pady=(0, 14))
        self._startup_indicator = startup_row[1]
        self._startup_label = startup_row[2]

        blacklist_label = tk.Label(
            self._advanced_content,
            text="Blacklist",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Segoe UI", 13, "bold"),
        )
        blacklist_label.pack(anchor="w", pady=(0, 8))
        blacklist_hint = tk.Label(
            self._advanced_content,
            text="One process name per line, for example Code.exe",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["subtle"],
            font=("Segoe UI", 9),
        )
        blacklist_hint.pack(anchor="w", pady=(0, 8))
        self._blacklist_text = tk.Text(
            self._advanced_content,
            height=4,
            wrap="none",
            relief="flat",
            undo=False,
            font=("Segoe UI", 10),
            padx=12,
            pady=10,
            bg=PALETTE["text_bg"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            highlightthickness=1,
            highlightbackground=PALETTE["text_border"],
            highlightcolor=PALETTE["primary"],
            selectbackground=PALETTE["primary"],
            selectforeground=PALETTE["primary_text"],
        )
        self._blacklist_text.pack(fill="x")
        self._blacklist_text.bind("<<Modified>>", self._handle_blacklist_modified)
        self._blacklist_text.bind("<FocusOut>", self._handle_blacklist_focus_out)
        self._blacklist_text.bind("<MouseWheel>", self._handle_mousewheel)

        self._version_label = tk.Label(
            self._advanced_content,
            text="",
            bg=PALETTE["panel_bg"],
            fg=PALETTE["subtle"],
            font=("Segoe UI", 9),
        )
        self._version_label.pack(anchor="w", pady=(12, 0))

    def _create_option_row(
        self,
        parent: Any,
        *,
        label: str,
        command: Callable[[], None],
        font_size: int,
        indicator_size: int,
    ) -> tuple[Any, Any, Any]:
        frame = self._tk.Frame(parent, bg=PALETTE["panel_bg"], cursor="hand2")
        indicator = self._create_option_indicator(frame, indicator_size=indicator_size)
        indicator.pack(side="left")
        text = self._tk.Label(
            frame,
            text=label,
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Segoe UI", font_size),
            cursor="hand2",
        )
        text.pack(side="left", padx=(8, 0))

        for widget in (frame, indicator, text):
            widget.bind("<Button-1>", lambda _event, cb=command: cb())

        return frame, indicator, text

    def _create_option_indicator(self, parent: Any, *, indicator_size: int) -> Any:
        indicator = self._tk.Label(
            parent,
            bg=PALETTE["panel_bg"],
            cursor="hand2",
        )
        self._draw_option_indicator(indicator, selected=False)
        return indicator

    def _draw_option_indicator(self, indicator: Any, *, selected: bool) -> None:
        image = self._radio_icon_selected if selected else self._radio_icon_unselected
        indicator.configure(image=image)
        indicator.image = image

    def _create_action_button(
        self,
        parent: Any,
        *,
        text: str,
        width: int,
        height: int,
        fill: str,
        hover_fill: str,
        text_color: str,
        border: str,
        command: Callable[[], None],
    ) -> Any:
        canvas = self._tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=PALETTE["panel_bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self._redraw_action_button(canvas, text, width, height, fill, text_color, border)

        def on_enter(_event: object) -> None:
            self._redraw_action_button(canvas, text, width, height, hover_fill, text_color, border)

        def on_leave(_event: object) -> None:
            self._redraw_action_button(canvas, text, width, height, fill, text_color, border)

        canvas.bind("<Enter>", on_enter)
        canvas.bind("<Leave>", on_leave)
        canvas.bind("<Button-1>", lambda _event: command())
        return canvas

    def _redraw_action_button(
        self,
        canvas: Any,
        text: str,
        width: int,
        height: int,
        fill: str,
        text_color: str,
        border: str,
    ) -> None:
        canvas.delete("all")
        self._create_rounded_rect(
            canvas,
            4,
            4,
            width - 4,
            height - 4,
            24,
            fill=fill,
            outline=border,
            width=2,
        )
        canvas.create_text(
            width // 2,
            height // 2 + 1,
            text=text,
            fill=text_color,
            font=("Segoe UI", 14, "bold"),
        )

    def _create_rounded_rect(
        self,
        canvas: Any,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        radius: float,
        **kwargs: Any,
    ) -> Any:
        points = _rounded_polygon_points(x1, y1, x2, y2, radius)
        return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)

    def _section_title(self, parent: Any, title: str) -> Any:
        return self._tk.Label(
            parent,
            text=title,
            bg=PALETTE["panel_bg"],
            fg=PALETTE["text"],
            font=("Segoe UI", 18, "bold"),
        )

    def _divider(self, parent: Any) -> Any:
        return self._tk.Frame(parent, bg=PALETTE["divider"], height=1)

    def _apply_state(self, state: PanelState) -> None:
        if not self._window_built:
            return

        self._current_state = state
        self._enabled = state.enabled
        self._startup_enabled = state.startup_enabled
        self._selected_tokenizer = state.tokenizer
        self._selected_duration = duration_to_choice(state.tooltip_display_s)
        self._tokenizer_display_map = build_tokenizer_display_map(state.tokenizer_options)

        self._rebuild_tokenizer_rows(state.tokenizer_options)
        self._enabled_indicator.configure(
            text=CHECK_GLYPH if state.enabled else RADIO_UNSELECTED_GLYPH,
            fg=PALETTE["text"] if state.enabled else PALETTE["radio_off"],
        )
        self._enabled_label.configure(text="Enable", fg=PALETTE["text"])
        self._trigger_label.configure(text=state.trigger_text)
        self._status_label.configure(text=state.status_text)
        self._version_label.configure(text=f"{state.app_name}  v{state.version}")

        self._refresh_option_group(self._tokenizer_rows, self._selected_tokenizer)
        self._refresh_option_group(self._duration_rows, self._selected_duration)
        self._refresh_startup_row()

        if not self._blacklist_dirty:
            current = self._blacklist_text.get("1.0", "end-1c")
            if current != state.blacklist_text:
                self._blacklist_text.delete("1.0", "end")
                if state.blacklist_text:
                    self._blacklist_text.insert("1.0", state.blacklist_text)
                self._blacklist_text.edit_modified(False)

        self._root.after_idle(self._sync_scroll_region)

    def _refresh_option_group(self, rows: dict[Any, tuple[Any, Any, Any]], selected: Any) -> None:
        for value, (frame, indicator, label) in rows.items():
            is_selected = value == selected
            self._draw_option_indicator(indicator, selected=is_selected)
            label.configure(fg=PALETTE["text"] if is_selected else PALETTE["muted"])
            frame.configure(bg=PALETTE["panel_bg"])

    def _rebuild_tokenizer_rows(self, options: list[tuple[str, str]]) -> None:
        if self._tokenizer_section is None:
            return
        existing = [(encoding, row[2].cget("text")) for encoding, row in self._tokenizer_rows.items()]
        if existing == options:
            return

        for child in self._tokenizer_section.winfo_children():
            child.destroy()
        self._tokenizer_rows = {}

        for encoding, label in options:
            row = self._create_option_row(
                self._tokenizer_section,
                label=label,
                command=lambda value=encoding: self._handle_tokenizer_selected(value),
                font_size=16,
                indicator_size=21,
            )
            row[0].pack(anchor="w", fill="x", pady=(0, 6))
            self._tokenizer_rows[encoding] = row

    def _refresh_startup_row(self) -> None:
        if self._startup_indicator is None or self._startup_label is None:
            return
        self._draw_option_indicator(self._startup_indicator, selected=self._startup_enabled)
        self._startup_label.configure(fg=PALETTE["text"] if self._startup_enabled else PALETTE["muted"])

    def _sync_scroll_width(self, _event: object = None) -> None:
        if self._scroll_canvas is None or self._scroll_window is None:
            return
        width = max(1, self._scroll_canvas.winfo_width())
        self._scroll_canvas.itemconfigure(self._scroll_window, width=width)
        self._sync_scroll_region()

    def _sync_scroll_region(self, _event: object = None) -> None:
        if self._scroll_canvas is None:
            return
        self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

    def _center_window(self) -> None:
        if self._root is None:
            return
        left, top, right, bottom = get_screen_rect()
        x = left + max(0, (right - left - WINDOW_WIDTH) // 2)
        y = top + max(0, (bottom - top - WINDOW_HEIGHT) // 2)
        self._root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")

    def _raise_to_front(self) -> None:
        if self._root is None:
            return
        try:
            self._root.attributes("-topmost", True)
            self._root.after(120, lambda: self._root and self._root.attributes("-topmost", False))
        except self._tk.TclError:
            return

    def _start_fade_in(self) -> None:
        if self._root is None:
            return
        self._cancel_fade_in()
        self._animate_fade_in(0)

    def _animate_fade_in(self, step: int) -> None:
        if self._root is None:
            return

        alpha = min(1.0, (step + 1) / 8.0)
        try:
            self._root.attributes("-alpha", alpha)
        except self._tk.TclError:
            return

        if alpha < 1.0:
            self._fade_after_id = self._root.after(18, self._animate_fade_in, step + 1)

    def _cancel_fade_in(self) -> None:
        if self._root is None or self._fade_after_id is None:
            return
        try:
            self._root.after_cancel(self._fade_after_id)
        except self._tk.TclError:
            pass
        self._fade_after_id = None

    def _toggle_advanced(self) -> None:
        self._advanced_expanded = toggle_advanced(self._advanced_expanded)
        if self._advanced_expanded:
            self._advanced_content.pack(fill="x", pady=(10, 0))
            self._advanced_chevron.configure(text=CHEVRON_EXPANDED)
        else:
            self._advanced_content.pack_forget()
            self._advanced_chevron.configure(text=CHEVRON_COLLAPSED)
        self._root.after_idle(self._sync_scroll_region)

    def _start_window_drag(self, event: Any) -> None:
        if self._root is None:
            return
        self._drag_pointer_origin = (event.x_root, event.y_root)
        self._drag_window_origin = (self._root.winfo_x(), self._root.winfo_y())

    def _perform_window_drag(self, event: Any) -> None:
        if self._root is None or self._drag_pointer_origin is None or self._drag_window_origin is None:
            return
        delta_x = event.x_root - self._drag_pointer_origin[0]
        delta_y = event.y_root - self._drag_pointer_origin[1]
        next_x = self._drag_window_origin[0] + delta_x
        next_y = self._drag_window_origin[1] + delta_y
        self._root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{next_x}+{next_y}")

    def _stop_window_drag(self, _event: Any = None) -> None:
        self._drag_pointer_origin = None
        self._drag_window_origin = None

    def _handle_mousewheel(self, event: Any) -> str | None:
        if self._root is None or self._scroll_canvas is None or not self._root.winfo_viewable():
            return None

        widget = getattr(event, "widget", None)
        if widget is None:
            return None

        try:
            if widget.winfo_toplevel() is not self._root:
                return None
        except self._tk.TclError:
            return None

        scroll_region = self._scroll_canvas.bbox("all")
        if not scroll_region:
            return "break"

        content_height = scroll_region[3] - scroll_region[1]
        visible_height = self._scroll_canvas.winfo_height()
        if content_height <= visible_height:
            return "break"

        delta = getattr(event, "delta", 0)
        if delta == 0:
            return "break"

        units = -1 * int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self._scroll_canvas.yview_scroll(units, "units")
        return "break"

    def _handle_enabled_changed(self) -> None:
        self._on_enabled_changed(not self._enabled)
        self.refresh()

    def _handle_startup_changed(self) -> None:
        self._on_startup_changed(not self._startup_enabled)
        self.refresh()

    def _handle_tokenizer_selected(self, encoding_name: str) -> None:
        if encoding_name == self._selected_tokenizer:
            return
        self._selected_tokenizer = encoding_name
        self._refresh_option_group(self._tokenizer_rows, self._selected_tokenizer)
        self._on_tokenizer_changed(encoding_name)
        self.refresh()

    def _handle_duration_selected(self, value: float) -> None:
        if abs(value - self._selected_duration) < 0.001:
            return
        self._selected_duration = value
        self._refresh_option_group(self._duration_rows, self._selected_duration)
        self._on_tooltip_duration_changed(value)

    def _handle_blacklist_modified(self, _event: object = None) -> None:
        if self._blacklist_text is None:
            return
        if not self._blacklist_text.edit_modified():
            return
        self._blacklist_text.edit_modified(False)
        self._blacklist_dirty = True
        self._cancel_blacklist_debounce()
        self._blacklist_after_id = self._root.after(BLACKLIST_SAVE_DEBOUNCE_MS, self._commit_blacklist)

    def _handle_blacklist_focus_out(self, _event: object = None) -> None:
        self._commit_blacklist()

    def _commit_blacklist(self) -> None:
        if self._blacklist_text is None or not self._blacklist_dirty:
            return
        self._cancel_blacklist_debounce()
        normalized = normalize_blacklist(self._blacklist_text.get("1.0", "end-1c"))
        self._blacklist_dirty = False
        self._on_blacklist_changed(normalized)
        self.refresh()

    def _cancel_blacklist_debounce(self) -> None:
        if self._root is None or self._blacklist_after_id is None:
            return
        try:
            self._root.after_cancel(self._blacklist_after_id)
        except self._tk.TclError:
            pass
        self._blacklist_after_id = None

    def _handle_clipboard_calculate(self) -> None:
        self._on_clipboard_calculate()

    def _handle_exit(self) -> None:
        self._commit_blacklist()
        self._on_exit()

    def _on_window_close(self) -> None:
        self._hide_window()
