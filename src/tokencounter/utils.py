"""Utility helpers: DPI awareness, screen geometry, logging."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os

from tokencounter.constants import CONFIG_DIR, LOG_FILE


def setup_logging(debug: bool = False) -> logging.Logger:
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


def set_dpi_aware() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def get_screen_rect() -> tuple[int, int, int, int]:
    try:
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, OSError):
        return (0, 0, 1920, 1080)


def clamp_tooltip_position(
    x: int, y: int, width: int, height: int, offset_x: int, offset_y: int
) -> tuple[int, int]:
    left, top, right, bottom = get_screen_rect()

    tx = x + offset_x
    ty = y + offset_y

    if tx + width > right:
        tx = x - offset_x - width

    if ty + height > bottom:
        ty = y - offset_y - height

    tx = max(left, min(tx, right - width))
    ty = max(top, min(ty, bottom - height))

    return (tx, ty)


def get_foreground_process_name() -> str | None:
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

        h_process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h_process:
            return None

        try:
            buf = ctypes.create_unicode_buffer(260)
            size = ctypes.wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(h_process, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return None
        finally:
            kernel32.CloseHandle(h_process)
    except (AttributeError, OSError):
        return None
