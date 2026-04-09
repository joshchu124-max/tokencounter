"""Global double-press hotkey detection.

TokenCounter uses explicit triggering only: double-press Ctrl to
request a token calculation for the current selection.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time
from typing import Callable

from tokencounter.config import Config
from tokencounter.constants import (
    HOTKEY_DOUBLE_TAP_S,
    THROTTLE_INTERVAL_S,
    WH_KEYBOARD_LL,
    WM_KEYUP,
    WM_SYSKEYUP,
)

logger = logging.getLogger("tokencounter")

# LRESULT is LONG_PTR (8 bytes on 64-bit Windows).
LRESULT = ctypes.wintypes.LPARAM

# ctypes callback type for low-level hooks
HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

# Declare argtypes/restype for hook-related Win32 APIs so that ctypes
# marshals pointer-sized handles and return values correctly on 64-bit.
_user32 = ctypes.windll.user32
_user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int, HOOKPROC, ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD,
]
_user32.SetWindowsHookExW.restype = LRESULT
_user32.UnhookWindowsHookEx.argtypes = [LRESULT]
_user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL
_user32.CallNextHookEx.argtypes = [
    LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
]
_user32.CallNextHookEx.restype = LRESULT


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HookManager:
    """Manages the global keyboard hook for double-tap detection."""

    def __init__(self, on_trigger: Callable[[int, int], None], config: Config) -> None:
        self._on_trigger = on_trigger
        self._hotkey_vk = config.hotkey_vk
        self._keyboard_hook: int = 0
        self._keyboard_proc_ref: HOOKPROC | None = None
        self._last_hotkey_up_time: float = 0.0
        self._other_key_pressed: bool = False
        self._last_trigger_time: float = 0.0

    def install(self) -> None:
        """Install the keyboard hook for hotkey detection."""
        def keyboard_proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0:
                try:
                    self._handle_keyboard_event(wParam, lParam)
                except Exception:
                    logger.exception("Error in keyboard hook callback")
            return _user32.CallNextHookEx(0, nCode, wParam, lParam)

        self._keyboard_proc_ref = HOOKPROC(keyboard_proc)

        # WH_KEYBOARD_LL is a global hook that runs in the installing
        # thread's context, so hMod=NULL (0) is valid and avoids issues
        # with module handles being truncated/invalid in PyInstaller.
        self._keyboard_hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._keyboard_proc_ref, 0, 0
        )
        if not self._keyboard_hook:
            logger.error("Failed to install keyboard hook (GetLastError=%d)",
                         ctypes.windll.kernel32.GetLastError())
        else:
            logger.info("Keyboard hook installed (hotkey vk=0x%02X)", self._hotkey_vk)

    def uninstall(self) -> None:
        if self._keyboard_hook:
            _user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = 0
        logger.info("Hooks uninstalled")

    def set_mode(self, mode: str) -> None:
        if mode == "hotkey":
            return
        logger.info("Ignoring unsupported trigger mode %r; hotkey mode is always used", mode)

    def _handle_keyboard_event(self, wParam: int, lParam: int) -> None:
        info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = info.vkCode

        # Ignore injected/synthetic keystrokes (e.g., our own SendInput for Ctrl+C)
        # LLKHF_INJECTED = 0x10
        if info.flags & 0x10:
            return

        if wParam in (WM_KEYUP, WM_SYSKEYUP):
            if vk == self._hotkey_vk:
                now = time.monotonic()
                if (
                    not self._other_key_pressed
                    and (now - self._last_hotkey_up_time) < HOTKEY_DOUBLE_TAP_S
                ):
                    self._last_hotkey_up_time = 0.0
                    self._other_key_pressed = False

                    if (now - self._last_trigger_time) < THROTTLE_INTERVAL_S:
                        return
                    self._last_trigger_time = now

                    pt = ctypes.wintypes.POINT()
                    _user32.GetCursorPos(ctypes.byref(pt))
                    logger.info("Hotkey double-tap triggered at (%d, %d)", pt.x, pt.y)
                    self._on_trigger(pt.x, pt.y)
                else:
                    self._last_hotkey_up_time = now
                    self._other_key_pressed = False
            else:
                self._other_key_pressed = True
