"""Module 4: Floating tooltip window for displaying token count results.

Runs on a dedicated thread with its own message pump.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import queue
from typing import TYPE_CHECKING

from tokencounter.constants import (
    TOOLTIP_CORNER_RADIUS,
    TOOLTIP_DISPLAY_S,
    TOOLTIP_FADE_STEP_S,
    TOOLTIP_HEIGHT,
    TOOLTIP_OFFSET_X,
    TOOLTIP_OFFSET_Y,
    TOOLTIP_WIDTH,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_POPUP,
)
from tokencounter.utils import clamp_tooltip_position, get_screen_rect

if TYPE_CHECKING:
    from tokencounter.config import ConfigManager

logger = logging.getLogger("tokencounter")

DT_SINGLELINE = 0x0020
DT_LEFT = 0x0000
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
PS_SOLID = 0
TRANSPARENT = 1
FW_NORMAL = 400
FW_BOLD = 700
FW_SEMIBOLD = 600
DEFAULT_CHARSET = 1
OUT_DEFAULT_PRECIS = 0
CLIP_DEFAULT_PRECIS = 0
CLEARTYPE_QUALITY = 5
DEFAULT_PITCH = 0
LWA_ALPHA = 0x02
SW_SHOWNOACTIVATE = 4
SW_HIDE = 0
WM_PAINT = 0x000F
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_MOUSEMOVE = 0x0200
WM_MOUSELEAVE = 0x02A3

TIMER_FADE = 1
TIMER_CHECK_QUEUE = 2
TIMER_STARTUP_ANIM = 3

STARTUP_ANIMATION_STEPS = 10
STARTUP_ANIMATION_INTERVAL_MS = 16
STARTUP_ANIMATION_OFFSET_Y = 18
STARTUP_HOLD_MS = 900


def _lerp(start: int, end: int, progress: float) -> int:
    return round(start + (end - start) * progress)


def get_startup_banner_position(
    width: int,
    height: int,
    *,
    progress: float,
    offset_y: int = STARTUP_ANIMATION_OFFSET_Y,
) -> tuple[int, int, int]:
    """Return centered startup banner position and alpha for animation progress."""

    left, top, right, bottom = get_screen_rect()
    target_x = left + max(0, (right - left - width) // 2)
    target_y = top + max(0, (bottom - top - height) // 2)
    start_y = target_y + offset_y

    clamped = max(0.0, min(progress, 1.0))
    eased = 1.0 - (1.0 - clamped) ** 3

    x = target_x
    y = _lerp(start_y, target_y, eased)
    alpha = _lerp(0, 255, eased)
    return x, y, alpha


def _rgb(r: int, g: int, b: int) -> int:
    return (b << 16) | (g << 8) | r


# Modern dark theme inspired by VS Code / GitHub Copilot
COLOR_BG = _rgb(30, 30, 30)           # Near-black background
COLOR_BG_HEADER = _rgb(38, 38, 38)    # Slightly lighter header area
COLOR_TEXT = _rgb(228, 228, 228)       # Soft white text
COLOR_TOKEN_NUM = _rgb(78, 201, 176)   # Teal/mint for token number (eye-catching)
COLOR_CHAR_NUM = _rgb(156, 220, 254)   # Light blue for char count
COLOR_LABEL = _rgb(128, 128, 128)      # Gray for labels
COLOR_MODEL = _rgb(206, 145, 120)      # Warm orange for model name
COLOR_BORDER = _rgb(60, 60, 60)        # Subtle border
COLOR_ACCENT_LINE = _rgb(78, 201, 176) # Teal accent bar on left


class TooltipWindow:
    def __init__(self, config_mgr: ConfigManager | None = None) -> None:
        self._config_mgr = config_mgr
        self._queue: queue.Queue[dict | None] = queue.Queue()
        self._hwnd: int = 0
        self._running = False
        self._current_data: dict | None = None
        self._fade_alpha: int = 255
        self._mouse_hovering = False
        self._font_main = None
        self._font_label = None
        self._font_small = None
        self._wnd_proc_ref = None
        self._startup_anim_step = 0

    def show(
        self,
        token_count: int,
        char_count: int,
        tokenizer_name: str,
        mouse_x: int,
        mouse_y: int,
    ) -> None:
        self._queue.put({
            "token_count": token_count,
            "char_count": char_count,
            "tokenizer_name": tokenizer_name,
            "mouse_x": mouse_x,
            "mouse_y": mouse_y,
        })

    def show_startup(self) -> None:
        self._queue.put({
            "kind": "startup",
            "title": "TokenCounter",
            "message": "Running in system tray",
        })

    def stop(self) -> None:
        self._queue.put(None)

    def run(self) -> None:
        self._running = True
        self._hwnd = self._create_window()
        self._create_fonts()

        logger.debug("Tooltip window created: hwnd=%s", self._hwnd)
        ctypes.windll.user32.SetTimer(self._hwnd, TIMER_CHECK_QUEUE, 50, None)

        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        self._cleanup()

    def _create_window(self) -> int:
        LRESULT = ctypes.wintypes.LPARAM  # LONG_PTR — pointer-sized
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        )

        # WNDCLASSW is not in ctypes.wintypes — define it here
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_PAINT:
                self._on_paint(hwnd)
                return 0
            if msg == WM_TIMER:
                if wparam == TIMER_FADE:
                    self._on_fade_tick()
                elif wparam == TIMER_STARTUP_ANIM:
                    self._on_startup_anim_tick()
                elif wparam == TIMER_CHECK_QUEUE:
                    self._check_queue()
                return 0
            if msg == WM_MOUSEMOVE:
                self._mouse_hovering = True
                tme = _TRACKMOUSEEVENT()
                tme.cbSize = ctypes.sizeof(_TRACKMOUSEEVENT)
                tme.dwFlags = 0x02
                tme.hwndTrack = hwnd
                tme.dwHoverTime = 0
                ctypes.windll.user32.TrackMouseEvent(ctypes.byref(tme))
                return 0
            if msg == WM_MOUSELEAVE:
                self._mouse_hovering = False
                return 0
            if msg == WM_DESTROY:
                self._running = False
                return 0
            return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = WNDPROC(wnd_proc)

        class_name = "TokenCounterTooltip"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wnd_proc_ref
        wc.lpszClassName = class_name
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        wc.hbrBackground = ctypes.windll.gdi32.CreateSolidBrush(COLOR_BG)
        wc.hCursor = ctypes.windll.user32.LoadCursorW(None, 32512)

        ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

        ex_style = WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
        ctypes.windll.user32.CreateWindowExW.argtypes = [
            ctypes.wintypes.DWORD,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.wintypes.HWND,
            ctypes.wintypes.HMENU,
            ctypes.wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        ctypes.windll.user32.CreateWindowExW.restype = ctypes.wintypes.HWND

        # Declare argtypes to ensure correct marshalling on 64-bit Windows
        ctypes.windll.user32.CreateWindowExW.argtypes = [
            ctypes.wintypes.DWORD,   # dwExStyle
            ctypes.c_wchar_p,        # lpClassName
            ctypes.c_wchar_p,        # lpWindowName
            ctypes.wintypes.DWORD,   # dwStyle
            ctypes.c_int,            # x
            ctypes.c_int,            # y
            ctypes.c_int,            # nWidth
            ctypes.c_int,            # nHeight
            ctypes.wintypes.HWND,    # hWndParent
            ctypes.wintypes.HMENU,   # hMenu
            ctypes.wintypes.HINSTANCE,  # hInstance
            ctypes.c_void_p,         # lpParam
        ]
        ctypes.windll.user32.CreateWindowExW.restype = ctypes.wintypes.HWND

        hwnd = ctypes.windll.user32.CreateWindowExW(
            ex_style,
            class_name,
            "",
            WS_POPUP,
            0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            None, None, wc.hInstance, None,
        )
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)
        return hwnd

    def _create_fonts(self) -> None:
        gdi32 = ctypes.windll.gdi32
        self._font_main = gdi32.CreateFontW(
            20, 0, 0, 0, FW_BOLD, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH, "Segoe UI"
        )
        self._font_label = gdi32.CreateFontW(
            13, 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH, "Segoe UI"
        )
        self._font_small = gdi32.CreateFontW(
            12, 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH, "Segoe UI"
        )

    def _on_paint(self, hwnd: int) -> None:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        if not self._current_data:
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return

        data = self._current_data
        W, H = TOOLTIP_WIDTH, TOOLTIP_HEIGHT

        # Fill background
        rect = ctypes.wintypes.RECT(0, 0, W, H)
        brush = gdi32.CreateSolidBrush(COLOR_BG)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

        # Rounded border
        pen = gdi32.CreatePen(PS_SOLID, 1, COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, pen)
        old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # NULL_BRUSH
        gdi32.RoundRect(hdc, 0, 0, W, H, TOOLTIP_CORNER_RADIUS, TOOLTIP_CORNER_RADIUS)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(pen)

        # Left accent bar (3px wide teal strip)
        accent_brush = gdi32.CreateSolidBrush(COLOR_ACCENT_LINE)
        accent_rect = ctypes.wintypes.RECT(0, 4, 3, H - 4)
        user32.FillRect(hdc, ctypes.byref(accent_rect), accent_brush)
        gdi32.DeleteObject(accent_brush)

        gdi32.SetBkMode(hdc, TRANSPARENT)

        if data.get("kind") == "startup":
            self._paint_startup(hdc, data)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return

        # Row 1: Token count (large, teal)
        old_font = gdi32.SelectObject(hdc, self._font_main)
        gdi32.SetTextColor(hdc, COLOR_TOKEN_NUM)
        token_text = f"{data['token_count']:,}"
        r1 = ctypes.wintypes.RECT(14, 10, W - 12, 34)
        user32.DrawTextW(hdc, token_text, -1, ctypes.byref(r1), DT_LEFT | DT_SINGLELINE)

        # "tokens" label next to the number
        gdi32.SelectObject(hdc, self._font_label)
        gdi32.SetTextColor(hdc, COLOR_LABEL)
        # Measure token number width to place label after it
        size = ctypes.wintypes.SIZE()
        gdi32.SelectObject(hdc, self._font_main)
        gdi32.GetTextExtentPoint32W(hdc, token_text, len(token_text), ctypes.byref(size))
        label_x = 14 + size.cx + 6
        gdi32.SelectObject(hdc, self._font_label)
        r1_label = ctypes.wintypes.RECT(label_x, 16, W - 12, 34)
        user32.DrawTextW(hdc, "tokens", -1, ctypes.byref(r1_label), DT_LEFT | DT_SINGLELINE)

        # Row 2: Chars count (light blue) + model name (orange)
        gdi32.SetTextColor(hdc, COLOR_CHAR_NUM)
        chars_text = f"{data['char_count']:,} chars"
        r2 = ctypes.wintypes.RECT(14, 38, 130, 54)
        user32.DrawTextW(hdc, chars_text, -1, ctypes.byref(r2), DT_LEFT | DT_SINGLELINE)

        # Separator dot
        gdi32.SetTextColor(hdc, COLOR_LABEL)
        r_dot = ctypes.wintypes.RECT(132, 38, 142, 54)
        user32.DrawTextW(hdc, "·", -1, ctypes.byref(r_dot), DT_LEFT | DT_SINGLELINE)

        # Model name
        gdi32.SetTextColor(hdc, COLOR_MODEL)
        r3 = ctypes.wintypes.RECT(144, 38, W - 12, 54)
        user32.DrawTextW(hdc, data['tokenizer_name'], -1, ctypes.byref(r3), DT_LEFT | DT_SINGLELINE)

        gdi32.SelectObject(hdc, old_font)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    def _check_queue(self) -> None:
        try:
            data = self._queue.get_nowait()
        except queue.Empty:
            return

        if data is None:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
            ctypes.windll.user32.PostQuitMessage(0)
            return

        if data.get("kind") == "startup":
            self._display_startup(data)
            return

        self._display(data)

    def _display(self, data: dict) -> None:
        user32 = ctypes.windll.user32
        self._current_data = data

        x, y = clamp_tooltip_position(
            data["mouse_x"], data["mouse_y"],
            TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            TOOLTIP_OFFSET_X, TOOLTIP_OFFSET_Y,
        )

        self._set_window_pos(x, y)

        self._fade_alpha = 255
        user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.InvalidateRect(self._hwnd, None, True)

        user32.KillTimer(self._hwnd, TIMER_FADE)
        display_s = TOOLTIP_DISPLAY_S
        if self._config_mgr:
            display_s = self._config_mgr.config.tooltip_display_s
        display_ms = int(display_s * 1000)
        user32.SetTimer(self._hwnd, TIMER_FADE, display_ms, None)

    def _display_startup(self, data: dict) -> None:
        user32 = ctypes.windll.user32
        self._current_data = data
        self._startup_anim_step = 0
        user32.KillTimer(self._hwnd, TIMER_FADE)
        user32.KillTimer(self._hwnd, TIMER_STARTUP_ANIM)

        x, y, alpha = get_startup_banner_position(TOOLTIP_WIDTH, TOOLTIP_HEIGHT, progress=0.0)
        self._fade_alpha = alpha
        self._set_window_pos(x, y)
        user32.SetLayeredWindowAttributes(self._hwnd, 0, alpha, LWA_ALPHA)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.InvalidateRect(self._hwnd, None, True)
        user32.SetTimer(self._hwnd, TIMER_STARTUP_ANIM, STARTUP_ANIMATION_INTERVAL_MS, None)

    def _on_fade_tick(self) -> None:
        user32 = ctypes.windll.user32

        if self._mouse_hovering:
            self._fade_alpha = 255
            user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
            return

        if self._fade_alpha >= 255:
            self._fade_alpha = 240
            user32.KillTimer(self._hwnd, TIMER_FADE)
            fade_ms = int(TOOLTIP_FADE_STEP_S * 1000)
            user32.SetTimer(self._hwnd, TIMER_FADE, fade_ms, None)
            user32.SetLayeredWindowAttributes(self._hwnd, 0, self._fade_alpha, LWA_ALPHA)
            return

        self._fade_alpha -= 15
        if self._fade_alpha <= 0:
            user32.KillTimer(self._hwnd, TIMER_FADE)
            user32.ShowWindow(self._hwnd, SW_HIDE)
            self._fade_alpha = 255
        else:
            user32.SetLayeredWindowAttributes(self._hwnd, 0, self._fade_alpha, LWA_ALPHA)

    def _on_startup_anim_tick(self) -> None:
        user32 = ctypes.windll.user32

        self._startup_anim_step += 1
        progress = self._startup_anim_step / STARTUP_ANIMATION_STEPS
        x, y, alpha = get_startup_banner_position(
            TOOLTIP_WIDTH,
            TOOLTIP_HEIGHT,
            progress=progress,
        )
        self._fade_alpha = alpha
        self._set_window_pos(x, y)
        user32.SetLayeredWindowAttributes(self._hwnd, 0, alpha, LWA_ALPHA)
        user32.InvalidateRect(self._hwnd, None, True)

        if self._startup_anim_step >= STARTUP_ANIMATION_STEPS:
            self._fade_alpha = 255
            user32.KillTimer(self._hwnd, TIMER_STARTUP_ANIM)
            user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
            user32.SetTimer(self._hwnd, TIMER_FADE, STARTUP_HOLD_MS, None)

    def _paint_startup(self, hdc: int, data: dict) -> None:
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32

        old_font = gdi32.SelectObject(hdc, self._font_main)
        gdi32.SetTextColor(hdc, COLOR_TEXT)
        title_rect = ctypes.wintypes.RECT(16, 10, TOOLTIP_WIDTH - 16, 32)
        user32.DrawTextW(hdc, data["title"], -1, ctypes.byref(title_rect), DT_CENTER | DT_SINGLELINE)

        gdi32.SelectObject(hdc, self._font_label)
        gdi32.SetTextColor(hdc, COLOR_LABEL)
        message_rect = ctypes.wintypes.RECT(16, 36, TOOLTIP_WIDTH - 16, 54)
        user32.DrawTextW(hdc, data["message"], -1, ctypes.byref(message_rect), DT_CENTER | DT_SINGLELINE)
        gdi32.SelectObject(hdc, old_font)

    def _set_window_pos(self, x: int, y: int) -> None:
        user32 = ctypes.windll.user32

        HWND = ctypes.wintypes.HWND
        user32.SetWindowPos.argtypes = [
            HWND, HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_uint,
        ]
        user32.SetWindowPos.restype = ctypes.wintypes.BOOL

        user32.SetWindowPos(
            self._hwnd, HWND(-1),
            x, y, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            0x0010 | 0x0040,
        )

    def _cleanup(self) -> None:
        gdi32 = ctypes.windll.gdi32
        if self._font_main:
            gdi32.DeleteObject(self._font_main)
        if self._font_label:
            gdi32.DeleteObject(self._font_label)
        if self._font_small:
            gdi32.DeleteObject(self._font_small)
        logger.debug("Tooltip thread cleaned up")


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", ctypes.wintypes.HDC),
        ("fErase", ctypes.wintypes.BOOL),
        ("rcPaint", ctypes.wintypes.RECT),
        ("fRestore", ctypes.wintypes.BOOL),
        ("fIncUpdate", ctypes.wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class _TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("hwndTrack", ctypes.wintypes.HWND),
        ("dwHoverTime", ctypes.wintypes.DWORD),
    ]
