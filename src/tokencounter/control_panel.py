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

PANEL_WIDTH = 560
PANEL_HEIGHT = 520
BLACKLIST_SAVE_DEBOUNCE_MS = 500
THEME_REGISTRY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
THEME_REGISTRY_VALUE = "AppsUseLightTheme"


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


LIGHT_THEME = {
    "bg": "#f5f7fb",
    "card": "#ffffff",
    "border": "#d8dee9",
    "text": "#172033",
    "muted": "#697386",
    "accent": "#1868db",
    "accent_hover": "#165fc7",
    "button_text": "#ffffff",
    "input_bg": "#ffffff",
    "input_fg": "#172033",
}

DARK_THEME = {
    "bg": "#11161f",
    "card": "#171d28",
    "border": "#273246",
    "text": "#edf2ff",
    "muted": "#95a1b3",
    "accent": "#5ea1ff",
    "accent_hover": "#7cb3ff",
    "button_text": "#08111f",
    "input_bg": "#0f141d",
    "input_fg": "#edf2ff",
}


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
        self._ttk = None
        self._root = None
        self._style = None
        self._window_built = False
        self._theme_name = "light"

        self._enabled_var = None
        self._startup_var = None
        self._tokenizer_var = None
        self._tooltip_var = None
        self._status_var = None
        self._version_var = None
        self._subtitle_var = None
        self._trigger_var = None
        self._tooltip_value_var = None

        self._title_label = None
        self._tokenizer_combo = None
        self._tooltip_scale = None
        self._blacklist_text = None

        self._tokenizer_display_to_encoding: dict[str, str] = {}
        self._blacklist_after_id = None
        self._fade_after_id = None
        self._updating_ui = False
        self._blacklist_dirty = False
        self._last_tooltip_value = 2.0

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
        from tkinter import ttk

        self._tk = tk
        self._ttk = ttk
        root = tk.Tk()
        root.withdraw()
        root.title(f"{__app_name__} Control Panel")
        root.resizable(False, False)
        root.geometry(f"{PANEL_WIDTH}x{PANEL_HEIGHT}")
        root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        self._root = root
        self._style = ttk.Style(root)
        try:
            self._style.theme_use("clam")
        except tk.TclError:
            pass

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
        self._apply_theme(get_system_theme())
        self._apply_state(self._state_provider())
        self._center_window()
        root.deiconify()
        root.lift()
        root.attributes("-alpha", 0.0)
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
            root.destroy()
        except self._tk.TclError:
            pass

    def _reset_ui_references(self) -> None:
        self._root = None
        self._style = None
        self._window_built = False
        self._enabled_var = None
        self._startup_var = None
        self._tokenizer_var = None
        self._tooltip_var = None
        self._status_var = None
        self._version_var = None
        self._subtitle_var = None
        self._trigger_var = None
        self._tooltip_value_var = None
        self._title_label = None
        self._tokenizer_combo = None
        self._tooltip_scale = None
        self._blacklist_text = None
        self._tokenizer_display_to_encoding = {}
        self._blacklist_after_id = None
        self._fade_after_id = None
        self._updating_ui = False
        self._blacklist_dirty = False
        self._last_tooltip_value = 2.0
        self._tk = None
        self._ttk = None

    def _ensure_window(self) -> None:
        if self._window_built or self._root is None:
            return

        tk = self._tk
        ttk = self._ttk
        root = self._root

        self._enabled_var = tk.BooleanVar(root, False)
        self._startup_var = tk.BooleanVar(root, False)
        self._tokenizer_var = tk.StringVar(root, "")
        self._tooltip_var = tk.DoubleVar(root, 2.0)
        self._status_var = tk.StringVar(root, "")
        self._version_var = tk.StringVar(root, "")
        self._subtitle_var = tk.StringVar(root, "")
        self._trigger_var = tk.StringVar(root, "")
        self._tooltip_value_var = tk.StringVar(root, "2.0s")

        container = ttk.Frame(root, style="Panel.TFrame", padding=20)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container, style="Panel.TFrame")
        header.pack(fill="x", pady=(0, 16))
        self._title_label = ttk.Label(header, text=__app_name__, style="HeaderTitle.TLabel")
        self._title_label.pack(anchor="w")
        ttk.Label(header, textvariable=self._subtitle_var, style="Subtitle.TLabel").pack(anchor="w", pady=(4, 0))
        ttk.Label(header, textvariable=self._status_var, style="Status.TLabel").pack(anchor="w", pady=(10, 0))
        ttk.Label(header, textvariable=self._version_var, style="Version.TLabel").pack(anchor="w", pady=(4, 0))

        general_card = self._create_section(container, "General")
        ttk.Checkbutton(
            general_card,
            text="Enabled",
            variable=self._enabled_var,
            command=self._handle_enabled_changed,
            style="Panel.TCheckbutton",
        ).pack(anchor="w")
        ttk.Checkbutton(
            general_card,
            text="Launch at startup",
            variable=self._startup_var,
            command=self._handle_startup_changed,
            style="Panel.TCheckbutton",
        ).pack(anchor="w", pady=(10, 0))
        ttk.Label(general_card, textvariable=self._trigger_var, style="Muted.TLabel").pack(anchor="w", pady=(12, 0))

        tokenizer_card = self._create_section(container, "Tokenizer")
        self._tokenizer_combo = ttk.Combobox(
            tokenizer_card,
            textvariable=self._tokenizer_var,
            state="readonly",
            style="Panel.TCombobox",
        )
        self._tokenizer_combo.pack(fill="x")
        self._tokenizer_combo.bind("<<ComboboxSelected>>", self._handle_tokenizer_changed)

        tooltip_card = self._create_section(container, "Tooltip")
        tooltip_row = ttk.Frame(tooltip_card, style="Card.TFrame")
        tooltip_row.pack(fill="x")
        ttk.Label(tooltip_row, text="Display Duration", style="Body.TLabel").pack(side="left")
        ttk.Label(tooltip_row, textvariable=self._tooltip_value_var, style="Value.TLabel").pack(side="right")
        self._tooltip_scale = ttk.Scale(
            tooltip_card,
            orient="horizontal",
            from_=1.0,
            to=5.0,
            variable=self._tooltip_var,
            command=self._handle_tooltip_changed,
        )
        self._tooltip_scale.pack(fill="x", pady=(12, 0))

        blacklist_card = self._create_section(container, "Blacklist")
        blacklist_hint = ttk.Label(
            blacklist_card,
            text="One process name per line, for example Code.exe",
            style="Muted.TLabel",
        )
        blacklist_hint.pack(anchor="w", pady=(0, 8))
        self._blacklist_text = tk.Text(
            blacklist_card,
            height=7,
            wrap="none",
            relief="flat",
            undo=False,
            font=("Segoe UI", 10),
            padx=10,
            pady=10,
        )
        self._blacklist_text.pack(fill="both", expand=True)
        self._blacklist_text.bind("<<Modified>>", self._handle_blacklist_modified)
        self._blacklist_text.bind("<FocusOut>", self._handle_blacklist_focus_out)

        actions_card = self._create_section(container, "Actions")
        actions_row = ttk.Frame(actions_card, style="Card.TFrame")
        actions_row.pack(fill="x")
        ttk.Button(
            actions_row,
            text="Calculate from Clipboard",
            style="Primary.TButton",
            command=self._handle_clipboard_calculate,
        ).pack(side="left")
        ttk.Button(
            actions_row,
            text="Hide to Tray",
            style="Secondary.TButton",
            command=self._hide_window,
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            actions_row,
            text="Exit",
            style="Secondary.TButton",
            command=self._handle_exit,
        ).pack(side="right")

        self._window_built = True

    def _create_section(self, parent: Any, title: str) -> Any:
        ttk = self._ttk
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill="x", pady=(0, 14))
        ttk.Label(card, text=title, style="SectionTitle.TLabel").pack(anchor="w", pady=(0, 12))
        return card

    def _apply_theme(self, theme_name: str) -> None:
        if self._root is None or self._style is None:
            return

        self._theme_name = theme_name if theme_name in ("light", "dark") else "light"
        palette = LIGHT_THEME if self._theme_name == "light" else DARK_THEME
        root = self._root
        style = self._style

        root.configure(bg=palette["bg"])
        style.configure("Panel.TFrame", background=palette["bg"])
        style.configure("Card.TFrame", background=palette["card"], borderwidth=1, relief="solid")
        style.configure(
            "HeaderTitle.TLabel",
            background=palette["bg"],
            foreground=palette["text"],
            font=("Segoe UI", 22, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=palette["bg"],
            foreground=palette["muted"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Status.TLabel",
            background=palette["bg"],
            foreground=palette["accent"],
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Version.TLabel",
            background=palette["bg"],
            foreground=palette["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=palette["card"],
            foreground=palette["text"],
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=palette["card"],
            foreground=palette["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=palette["card"],
            foreground=palette["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Value.TLabel",
            background=palette["card"],
            foreground=palette["text"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Panel.TCheckbutton",
            background=palette["card"],
            foreground=palette["text"],
            font=("Segoe UI", 10),
        )
        style.map(
            "Panel.TCheckbutton",
            background=[("active", palette["card"])],
            foreground=[("active", palette["text"])],
        )
        style.configure(
            "Panel.TCombobox",
            fieldbackground=palette["input_bg"],
            background=palette["input_bg"],
            foreground=palette["input_fg"],
            arrowcolor=palette["text"],
            bordercolor=palette["border"],
            lightcolor=palette["border"],
            darkcolor=palette["border"],
            selectbackground=palette["accent"],
            selectforeground=palette["button_text"],
        )
        style.configure(
            "Primary.TButton",
            background=palette["accent"],
            foreground=palette["button_text"],
            bordercolor=palette["accent"],
            focusthickness=0,
            focuscolor=palette["accent"],
            padding=(14, 8),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", palette["accent_hover"])],
            foreground=[("active", palette["button_text"])],
        )
        style.configure(
            "Secondary.TButton",
            background=palette["card"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            focusthickness=0,
            focuscolor=palette["card"],
            padding=(14, 8),
            font=("Segoe UI", 10),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", palette["bg"])],
            foreground=[("active", palette["text"])],
        )

        if self._blacklist_text is not None:
            self._blacklist_text.configure(
                bg=palette["input_bg"],
                fg=palette["input_fg"],
                insertbackground=palette["input_fg"],
                highlightthickness=1,
                highlightbackground=palette["border"],
                highlightcolor=palette["accent"],
                selectbackground=palette["accent"],
                selectforeground=palette["button_text"],
            )

    def _apply_state(self, state: PanelState) -> None:
        if not self._window_built:
            return

        self._updating_ui = True
        try:
            self._title_label.configure(text=state.app_name)
            self._subtitle_var.set(state.subtitle)
            self._status_var.set(state.status_text)
            self._version_var.set(f"v{state.version}")
            self._trigger_var.set(state.trigger_text)
            self._enabled_var.set(state.enabled)
            self._startup_var.set(state.startup_enabled)
            self._tooltip_var.set(state.tooltip_display_s)
            self._tooltip_value_var.set(f"{state.tooltip_display_s:.1f}s")
            self._last_tooltip_value = state.tooltip_display_s

            display_values = [label for _, label in state.tokenizer_options]
            self._tokenizer_display_to_encoding = {
                label: encoding_name for encoding_name, label in state.tokenizer_options
            }
            self._tokenizer_combo.configure(values=display_values)
            selected_label = next(
                (label for encoding_name, label in state.tokenizer_options if encoding_name == state.tokenizer),
                display_values[0] if display_values else "",
            )
            self._tokenizer_var.set(selected_label)

            if not self._blacklist_dirty:
                current = self._blacklist_text.get("1.0", "end-1c")
                if current != state.blacklist_text:
                    self._blacklist_text.delete("1.0", "end")
                    if state.blacklist_text:
                        self._blacklist_text.insert("1.0", state.blacklist_text)
                    self._blacklist_text.edit_modified(False)
        finally:
            self._updating_ui = False

    def _center_window(self) -> None:
        if self._root is None:
            return
        left, top, right, bottom = get_screen_rect()
        x = left + max(0, (right - left - PANEL_WIDTH) // 2)
        y = top + max(0, (bottom - top - PANEL_HEIGHT) // 2)
        self._root.geometry(f"{PANEL_WIDTH}x{PANEL_HEIGHT}+{x}+{y}")

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

    def _handle_enabled_changed(self) -> None:
        if self._updating_ui:
            return
        self._on_enabled_changed(bool(self._enabled_var.get()))
        self.refresh()

    def _handle_startup_changed(self) -> None:
        if self._updating_ui:
            return
        self._on_startup_changed(bool(self._startup_var.get()))
        self.refresh()

    def _handle_tokenizer_changed(self, _event: object = None) -> None:
        if self._updating_ui:
            return
        selected = self._tokenizer_display_to_encoding.get(self._tokenizer_var.get())
        if not selected:
            return
        self._on_tokenizer_changed(selected)
        self.refresh()

    def _handle_tooltip_changed(self, value: str) -> None:
        if self._updating_ui:
            return
        snapped = max(1.0, min(5.0, round(float(value) * 2.0) / 2.0))
        self._updating_ui = True
        try:
            self._tooltip_var.set(snapped)
            self._tooltip_value_var.set(f"{snapped:.1f}s")
        finally:
            self._updating_ui = False

        if abs(snapped - self._last_tooltip_value) < 0.001:
            return

        self._last_tooltip_value = snapped
        self._on_tooltip_duration_changed(snapped)

    def _handle_blacklist_modified(self, _event: object = None) -> None:
        if self._updating_ui or self._blacklist_text is None:
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
