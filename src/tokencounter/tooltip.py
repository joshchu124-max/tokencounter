"""Module 4: Floating tooltip window for displaying token count results.

Runs on a dedicated thread with its own message pump.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import queue

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
from tokencounter.utils import clamp_tooltip_position

logger = logging.getLogger("tokencounter")

DT_SINGLELINE = 0x0020
DT_LEFT = 0x0000
PS_SOLID = 0
TRANSPARENT = 1
FW_NORMAL = 400
FW_BOLD = 700
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


def _rgb(r: int, g: int, b: int) -> int:
    return (b << 16) | (g << 8) | r


COLOR_BG = _rgb(31, 43, 57)
COLOR_TEXT = _rgb(240, 240, 240)
COLOR_ACCENT = _rgb(86, 160, 212)
COLOR_BORDER = _rgb(64, 80, 96)


class TooltipWindow:
    def __init__(self) -> None:
        self._queue: queue.Queue[dict | None] = queue.Queue()
        self._hwnd: int = 0
        self._running = False
        self._current_data: dict | None = None
        self._fade_alpha: int = 255
        self._mouse_hovering = False
        self._font_main = None
        self._font_small = None
        self._wnd_proc_ref = None

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
            16, 0, 0, 0, FW_BOLD, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH, "Segoe UI"
        )
        self._font_small = gdi32.CreateFontW(
            13, 0, 0, 0, FW_NORMAL, 0, 0, 0,
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

        rect = ctypes.wintypes.RECT(0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT)
        brush = gdi32.CreateSolidBrush(COLOR_BG)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

        pen = gdi32.CreatePen(PS_SOLID, 1, COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, pen)
        old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))
        gdi32.RoundRect(hdc, 0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
                        TOOLTIP_CORNER_RADIUS, TOOLTIP_CORNER_RADIUS)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(pen)

        gdi32.SetBkMode(hdc, TRANSPARENT)

        old_font = gdi32.SelectObject(hdc, self._font_main)
        gdi32.SetTextColor(hdc, COLOR_TEXT)
        line1 = f"Tokens: {data['token_count']:,}  |  Chars: {data['char_count']:,}"
        r1 = ctypes.wintypes.RECT(12, 12, TOOLTIP_WIDTH - 12, 40)
        user32.DrawTextW(hdc, line1, -1, ctypes.byref(r1), DT_LEFT | DT_SINGLELINE)

        gdi32.SelectObject(hdc, self._font_small)
        gdi32.SetTextColor(hdc, COLOR_ACCENT)
        line2 = f"Model: {data['tokenizer_name']}"
        r2 = ctypes.wintypes.RECT(12, 42, TOOLTIP_WIDTH - 12, 68)
        user32.DrawTextW(hdc, line2, -1, ctypes.byref(r2), DT_LEFT | DT_SINGLELINE)

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

        self._display(data)

    def _display(self, data: dict) -> None:
        user32 = ctypes.windll.user32
        self._current_data = data

        x, y = clamp_tooltip_position(
            data["mouse_x"], data["mouse_y"],
            TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            TOOLTIP_OFFSET_X, TOOLTIP_OFFSET_Y,
        )

        user32.SetWindowPos(
            self._hwnd, -1,
            x, y, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            0x0010 | 0x0040,
        )

        self._fade_alpha = 255
        user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.InvalidateRect(self._hwnd, None, True)

        user32.KillTimer(self._hwnd, TIMER_FADE)
        display_ms = int(TOOLTIP_DISPLAY_S * 1000)
        user32.SetTimer(self._hwnd, TIMER_FADE, display_ms, None)

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

    def _cleanup(self) -> None:
        gdi32 = ctypes.windll.gdi32
        if self._font_main:
            gdi32.DeleteObject(self._font_main)
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
