"""Utility helpers: DPI awareness, screen geometry, logging."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
from pathlib import Path

from tokencounter.constants import CONFIG_DIR, LOG_FILE


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(debug: bool = False) -> logging.Logger:
    """Configure a file logger for the application."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    logger = logging.getLogger("tokencounter")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return logger


# ---------------------------------------------------------------------------
# DPI awareness
# ---------------------------------------------------------------------------

def set_dpi_aware() -> None:
    """Enable Per-Monitor DPI awareness (Windows 8.1+)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


# ---------------------------------------------------------------------------
# Screen geometry helpers
# ---------------------------------------------------------------------------

def get_screen_rect() -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) of the primary monitor work area."""
    try:
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError):
        # Fallback: assume 1920x1080
        return (0, 0, 1920, 1080)


def clamp_tooltip_position(
    x: int, y: int, width: int, height: int, offset_x: int, offset_y: int
) -> tuple[int, int]:
    """Compute tooltip position near (x, y) without going off-screen."""
    left, top, right, bottom = get_screen_rect()

    # Default: right-down of cursor
    tx = x + offset_x
    ty = y + offset_y

    # Flip horizontally if too close to right edge
    if tx + width > right:
        tx = x - offset_x - width

    # Flip vertically if too close to bottom edge
    if ty + height > bottom:
        ty = y - offset_y - height

    # Clamp to screen boundaries
    tx = max(left, min(tx, right - width))
    ty = max(top, min(ty, bottom - height))

    return (tx, ty)


# ---------------------------------------------------------------------------
# Process name helper (for blacklist checking)
# ---------------------------------------------------------------------------

def get_foreground_process_name() -> str | None:
    """Return the executable name (e.g. 'notepad.exe') of the foreground window."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None

        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h_process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h_process:
            return None

        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            # QueryFullProcessImageNameW
            if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return None
        finally:
            kernel32.CloseHandle(h_process)
    except (AttributeError, OSError):
        return None
