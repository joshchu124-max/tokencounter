"""Module 1: Global hooks for selection awareness.

Two trigger modes:
- Auto-detect: Low-level mouse hook (WH_MOUSE_LL) detects mouse-up after drag.
- Hotkey: Low-level keyboard hook (WH_KEYBOARD_LL) detects double-press of a key.

Both modes run on the main thread which must pump messages.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import math
import threading
import time
from typing import Callable

from tokencounter.config import Config
from tokencounter.constants import (
    DEBOUNCE_S,
    HOTKEY_DOUBLE_TAP_S,
    MIN_DRAG_DISTANCE_PX,
    THROTTLE_INTERVAL_S,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    WM_KEYUP,
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_SYSKEYUP,
)

logger = logging.getLogger("tokencounter")

# ctypes callback type for low-level hooks
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,     # return: LRESULT
    ctypes.c_int,      # nCode
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)


class MSLLHOOKSTRUCT(ctypes.Structure):
    """Structure passed to WH_MOUSE_LL callback via lParam."""
    _fields_ = [
        ("pt", ctypes.wintypes.POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """Structure passed to WH_KEYBOARD_LL callback via lParam."""
    _fields_ = [
        ("vkCode", ctypes.wintypes.DWORD),
        ("scanCode", ctypes.wintypes.DWORD),
        ("flags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HookManager:
    """Manages global mouse and keyboard hooks for trigger detection.

    Parameters
    ----------
    on_trigger : callable
        Called with (mouse_x, mouse_y) when a valid trigger fires.
    config : Config
        Current configuration (trigger_mode, hotkey_vk).
    """

    def __init__(self, on_trigger: Callable[[int, int], None], config: Config) -> None:
        self._on_trigger = on_trigger
        self._mode = config.trigger_mode
        self._hotkey_vk = config.hotkey_vk

        # Hook handles
        self._mouse_hook: int = 0
        self._keyboard_hook: int = 0

        # Keep references to prevent GC of ctypes callbacks
        self._mouse_proc_ref: HOOKPROC | None = None
        self._keyboard_proc_ref: HOOKPROC | None = None

        # Mouse hook state
        self._press_pos: tuple[int, int] = (0, 0)
        self._press_time: float = 0.0
        self._debounce_timer: threading.Timer | None = None
        self._last_trigger_time: float = 0.0
        self._last_mouseup_pos: tuple[int, int] = (0, 0)

        # Keyboard hook state (for double-tap detection)
        self._last_hotkey_up_time: float = 0.0
        self._other_key_pressed: bool = False

    # -- public API ----------------------------------------------------------

    def install(self) -> None:
        """Install the appropriate hooks based on current mode."""
        if self._mode == "auto":
            self._install_mouse_hook()
        else:
            self._install_keyboard_hook()
        logger.info("Hooks installed in '%s' mode", self._mode)

    def uninstall(self) -> None:
        """Remove all installed hooks."""
        self._cancel_debounce()
        user32 = ctypes.windll.user32
        if self._mouse_hook:
            user32.UnhookWindowsHookEx(self._mouse_hook)
            self._mouse_hook = 0
        if self._keyboard_hook:
            user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._keyboard_hook = 0
        logger.info("Hooks uninstalled")

    def set_mode(self, mode: str) -> None:
        """Switch between 'auto' and 'hotkey' mode at runtime."""
        if mode == self._mode:
            return
        self.uninstall()
        self._mode = mode
        self.install()

    # -- mouse hook (auto-detect mode) ---------------------------------------

    def _install_mouse_hook(self) -> None:
        def mouse_proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0:
                try:
                    self._handle_mouse_event(wParam, lParam)
                except Exception:
                    logger.exception("Error in mouse hook callback")
            return ctypes.windll.user32.CallNextHookEx(0, nCode, wParam, lParam)

        self._mouse_proc_ref = HOOKPROC(mouse_proc)
        self._mouse_hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_proc_ref, None, 0
        )
        if not self._mouse_hook:
            logger.error("Failed to install mouse hook")

    def _handle_mouse_event(self, wParam: int, lParam: int) -> None:
        info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents

        if wParam == WM_LBUTTONDOWN:
            self._press_pos = (info.pt.x, info.pt.y)
            self._press_time = time.monotonic()
            # Cancel any pending debounce (user started a new gesture)
            self._cancel_debounce()

        elif wParam == WM_LBUTTONUP:
            up_x, up_y = info.pt.x, info.pt.y

            # Click-vs-select heuristic: check drag distance
            dx = up_x - self._press_pos[0]
            dy = up_y - self._press_pos[1]
            distance = math.sqrt(dx * dx + dy * dy)

            if distance < MIN_DRAG_DISTANCE_PX:
                # This was just a click, not a text selection
                return

            self._last_mouseup_pos = (up_x, up_y)

            # Cancel previous debounce and start a new one
            self._cancel_debounce()
            self._debounce_timer = threading.Timer(DEBOUNCE_S, self._debounce_fire)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _debounce_fire(self) -> None:
        """Called after debounce delay. Checks throttle, then fires trigger."""
        now = time.monotonic()
        if (now - self._last_trigger_time) < THROTTLE_INTERVAL_S:
            return  # Still within throttle window
        self._last_trigger_time = now
        x, y = self._last_mouseup_pos
        logger.debug("Auto-detect trigger at (%d, %d)", x, y)
        self._on_trigger(x, y)

    def _cancel_debounce(self) -> None:
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

    # -- keyboard hook (hotkey mode) -----------------------------------------

    def _install_keyboard_hook(self) -> None:
        def keyboard_proc(nCode: int, wParam: int, lParam: int) -> int:
            if nCode >= 0:
                try:
                    self._handle_keyboard_event(wParam, lParam)
                except Exception:
                    logger.exception("Error in keyboard hook callback")
            return ctypes.windll.user32.CallNextHookEx(0, nCode, wParam, lParam)

        self._keyboard_proc_ref = HOOKPROC(keyboard_proc)
        self._keyboard_hook = ctypes.windll.user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._keyboard_proc_ref, None, 0
        )
        if not self._keyboard_hook:
            logger.error("Failed to install keyboard hook")

    def _handle_keyboard_event(self, wParam: int, lParam: int) -> None:
        info = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = info.vkCode

        if wParam in (WM_KEYUP, WM_SYSKEYUP):
            if vk == self._hotkey_vk:
                now = time.monotonic()
                if (
                    not self._other_key_pressed
                    and (now - self._last_hotkey_up_time) < HOTKEY_DOUBLE_TAP_S
                ):
                    # Double-tap detected!
                    self._last_hotkey_up_time = 0.0  # Reset to avoid triple-tap
                    self._other_key_pressed = False

                    # Throttle check
                    if (now - self._last_trigger_time) < THROTTLE_INTERVAL_S:
                        return
                    self._last_trigger_time = now

                    # Get current cursor position
                    pt = ctypes.wintypes.POINT()
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
                    logger.debug("Hotkey trigger at (%d, %d)", pt.x, pt.y)
                    self._on_trigger(pt.x, pt.y)
                else:
                    self._last_hotkey_up_time = now
                    self._other_key_pressed = False
            else:
                # Another key was involved — invalidate the double-tap sequence
                self._other_key_pressed = True
