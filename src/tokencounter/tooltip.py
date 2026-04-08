"""Module 4: Floating tooltip window for displaying token count results.

Runs on a dedicated thread (Thread C) with its own message pump.
The tooltip is a layered, topmost, non-activating popup window
that appears near the mouse cursor and auto-fades after a few seconds.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import queue
import threading
import time

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

# GDI constants
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_WORDBREAK = 0x0010
DT_LEFT = 0x0000
DT_TOP = 0x0000
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

# Timer IDs
TIMER_FADE = 1
TIMER_CHECK_QUEUE = 2

# Colors (RGB, note: Win32 GDI uses COLORREF = 0x00BBGGRR)
COLOR_BG = 0x00392B1F          # Dark background (#1F2B39 → BGR)
COLOR_TEXT = 0x00F0F0F0        # Light text
COLOR_ACCENT = 0x00D4A056      # Accent / tokenizer name (#56A0D4 → BGR)
COLOR_BORDER = 0x00605040      # Subtle border


def _rgb(r: int, g: int, b: int) -> int:
    """Convert RGB to Win32 COLORREF (BGR)."""
    return (b << 16) | (g << 8) | r


# Override with proper RGB values
COLOR_BG = _rgb(31, 43, 57)
COLOR_TEXT = _rgb(240, 240, 240)
COLOR_ACCENT = _rgb(86, 160, 212)
COLOR_BORDER = _rgb(64, 80, 96)
COLOR_MODEL_BG = _rgb(41, 55, 72)


class TooltipWindow:
    """Floating tooltip that shows token count results.

    Designed to run on a dedicated thread. Call :meth:`run` to start
    the thread's message pump, and :meth:`show` from any thread to
    trigger a display.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[dict | None] = queue.Queue()
        self._hwnd: int = 0
        self._running = False
        self._current_data: dict | None = None
        self._fade_alpha: int = 255
        self._mouse_hovering = False

        # GDI objects (created once, reused)
        self._font_main = None
        self._font_small = None

        # Store wndproc reference to prevent GC
        self._wnd_proc_ref = None

    # -- public API (thread-safe) -------------------------------------------

    def show(
        self,
        token_count: int,
        char_count: int,
        tokenizer_name: str,
        mouse_x: int,
        mouse_y: int,
    ) -> None:
        """Enqueue a tooltip display request. Can be called from any thread."""
        self._queue.put({
            "token_count": token_count,
            "char_count": char_count,
            "tokenizer_name": tokenizer_name,
            "mouse_x": mouse_x,
            "mouse_y": mouse_y,
        })

    def stop(self) -> None:
        """Signal the tooltip thread to exit."""
        self._queue.put(None)

    # -- thread entry point --------------------------------------------------

    def run(self) -> None:
        """Create the tooltip window and run its message pump.

        Must be called on the dedicated tooltip thread.
        """
        self._running = True
        self._hwnd = self._create_window()
        self._create_fonts()

        logger.debug("Tooltip window created: hwnd=%s", self._hwnd)

        # Set up a timer to poll the queue (every 50ms)
        ctypes.windll.user32.SetTimer(self._hwnd, TIMER_CHECK_QUEUE, 50, None)

        # Message pump
        msg = ctypes.wintypes.MSG()
        while self._running:
            ret = ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))

        self._cleanup()

    # -- window creation -----------------------------------------------------

    def _create_window(self) -> int:
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long,
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
            elif msg == WM_TIMER:
                if wparam == TIMER_FADE:
                    self._on_fade_tick()
                elif wparam == TIMER_CHECK_QUEUE:
                    self._check_queue()
                return 0
            elif msg == WM_MOUSEMOVE:
                self._mouse_hovering = True
                # Request WM_MOUSELEAVE
                tme = _TRACKMOUSEEVENT()
                tme.cbSize = ctypes.sizeof(_TRACKMOUSEEVENT)
                tme.dwFlags = 0x02  # TME_LEAVE
                tme.hwndTrack = hwnd
                tme.dwHoverTime = 0
                ctypes.windll.user32.TrackMouseEvent(ctypes.byref(tme))
                return 0
            elif msg == WM_MOUSELEAVE:
                self._mouse_hovering = False
                return 0
            elif msg == WM_DESTROY:
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
        wc.hCursor = ctypes.windll.user32.LoadCursorW(None, 32512)  # IDC_ARROW

        ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

        ex_style = WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED

        hwnd = ctypes.windll.user32.CreateWindowExW(
            ex_style,
            class_name,
            "",
            WS_POPUP,
            0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            None, None, wc.hInstance, None,
        )

        # Set initial alpha (fully transparent, hidden)
        ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)

        return hwnd

    def _create_fonts(self) -> None:
        gdi32 = ctypes.windll.gdi32
        self._font_main = gdi32.CreateFontW(
            16, 0, 0, 0, FW_BOLD, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH,
            "Segoe UI"
        )
        self._font_small = gdi32.CreateFontW(
            13, 0, 0, 0, FW_NORMAL, 0, 0, 0,
            DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
            CLEARTYPE_QUALITY, DEFAULT_PITCH,
            "Segoe UI"
        )

    # -- painting ------------------------------------------------------------

    def _on_paint(self, hwnd: int) -> None:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        ps = _PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))

        if not self._current_data:
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return

        data = self._current_data

        # Fill background
        rect = ctypes.wintypes.RECT(0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT)
        brush = gdi32.CreateSolidBrush(COLOR_BG)
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

        # Draw border
        pen = gdi32.CreatePen(PS_SOLID, 1, COLOR_BORDER)
        old_pen = gdi32.SelectObject(hdc, pen)
        old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(5))  # HOLLOW_BRUSH
        gdi32.RoundRect(hdc, 0, 0, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
                        TOOLTIP_CORNER_RADIUS, TOOLTIP_CORNER_RADIUS)
        gdi32.SelectObject(hdc, old_pen)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.DeleteObject(pen)

        gdi32.SetBkMode(hdc, TRANSPARENT)

        # Line 1: Token count and char count
        old_font = gdi32.SelectObject(hdc, self._font_main)
        gdi32.SetTextColor(hdc, COLOR_TEXT)
        line1 = f"Tokens: {data['token_count']:,}  |  Chars: {data['char_count']:,}"
        r1 = ctypes.wintypes.RECT(12, 12, TOOLTIP_WIDTH - 12, 40)
        user32.DrawTextW(hdc, line1, -1, ctypes.byref(r1), DT_LEFT | DT_SINGLELINE)

        # Line 2: Tokenizer name
        gdi32.SelectObject(hdc, self._font_small)
        gdi32.SetTextColor(hdc, COLOR_ACCENT)
        line2 = f"Model: {data['tokenizer_name']}"
        r2 = ctypes.wintypes.RECT(12, 42, TOOLTIP_WIDTH - 12, 68)
        user32.DrawTextW(hdc, line2, -1, ctypes.byref(r2), DT_LEFT | DT_SINGLELINE)

        gdi32.SelectObject(hdc, old_font)
        user32.EndPaint(hwnd, ctypes.byref(ps))

    # -- show / fade logic ---------------------------------------------------

    def _check_queue(self) -> None:
        """Check for new display requests from the queue."""
        try:
            data = self._queue.get_nowait()
        except queue.Empty:
            return

        if data is None:
            # Stop signal
            ctypes.windll.user32.DestroyWindow(self._hwnd)
            ctypes.windll.user32.PostQuitMessage(0)
            return

        self._display(data)

    def _display(self, data: dict) -> None:
        """Position, populate, and show the tooltip."""
        user32 = ctypes.windll.user32

        self._current_data = data

        # Compute position
        x, y = clamp_tooltip_position(
            data["mouse_x"], data["mouse_y"],
            TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            TOOLTIP_OFFSET_X, TOOLTIP_OFFSET_Y,
        )

        # Move and show
        user32.SetWindowPos(
            self._hwnd, -1,  # HWND_TOPMOST
            x, y, TOOLTIP_WIDTH, TOOLTIP_HEIGHT,
            0x0010 | 0x0040,  # SWP_NOACTIVATE | SWP_SHOWWINDOW
        )

        # Set fully opaque
        self._fade_alpha = 255
        user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)

        # Force repaint
        user32.InvalidateRect(self._hwnd, None, True)

        # Cancel any existing fade timer, start a new display timer
        user32.KillTimer(self._hwnd, TIMER_FADE)
        display_ms = int(TOOLTIP_DISPLAY_S * 1000)
        user32.SetTimer(self._hwnd, TIMER_FADE, display_ms, None)

    def _on_fade_tick(self) -> None:
        """Handle fade-out: reduce alpha each tick until hidden."""
        user32 = ctypes.windll.user32

        if self._mouse_hovering:
            # Reset: keep showing while hovered
            self._fade_alpha = 255
            user32.SetLayeredWindowAttributes(self._hwnd, 0, 255, LWA_ALPHA)
            return

        if self._fade_alpha >= 255:
            # First tick after display period: start fading
            self._fade_alpha = 240
            # Switch to frequent timer for smooth fade
            user32.KillTimer(self._hwnd, TIMER_FADE)
            fade_ms = int(TOOLTIP_FADE_STEP_S * 1000)
            user32.SetTimer(self._hwnd, TIMER_FADE, fade_ms, None)
            user32.SetLayeredWindowAttributes(self._hwnd, 0, self._fade_alpha, LWA_ALPHA)
            return

        self._fade_alpha -= 15
        if self._fade_alpha <= 0:
            # Fully faded: hide
            user32.KillTimer(self._hwnd, TIMER_FADE)
            user32.ShowWindow(self._hwnd, SW_HIDE)
            self._fade_alpha = 255
        else:
            user32.SetLayeredWindowAttributes(self._hwnd, 0, self._fade_alpha, LWA_ALPHA)

    # -- cleanup -------------------------------------------------------------

    def _cleanup(self) -> None:
        gdi32 = ctypes.windll.gdi32
        if self._font_main:
            gdi32.DeleteObject(self._font_main)
        if self._font_small:
            gdi32.DeleteObject(self._font_small)
        logger.debug("Tooltip thread cleaned up")


# ---------------------------------------------------------------------------
# Win32 structs needed for painting / mouse tracking
# ---------------------------------------------------------------------------

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
