"""Selection acquisition via explicit clipboard copy.

The app no longer tries to infer selection changes automatically.
When the user explicitly triggers a count, we simulate Ctrl+C and wait
for the clipboard sequence number to advance before accepting text.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

from tokencounter.constants import (
    CF_UNICODETEXT,
    CLIPBOARD_COPY_TIMEOUT_S,
    CLIPBOARD_POLL_INTERVAL_S,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    VK_C,
    VK_CONTROL,
)

logger = logging.getLogger("tokencounter")


class TextAcquirer:
    """Explicitly copies the current selection and reads it from the clipboard."""

    def acquire(self) -> str | None:
        return self._copy_selection_via_clipboard()

    def _copy_selection_via_clipboard(self) -> str | None:
        try:
            original_seq = self._get_clipboard_sequence_number()
            original_text = self._read_clipboard()

            self._send_ctrl_c()

            deadline = time.monotonic() + CLIPBOARD_COPY_TIMEOUT_S
            copied_text: str | None = None

            while time.monotonic() < deadline:
                current_seq = self._get_clipboard_sequence_number()
                if current_seq != original_seq:
                    copied_text = self._read_clipboard()
                    if copied_text and copied_text.strip():
                        logger.debug("Acquired text via clipboard (%d chars)", len(copied_text))
                        break
                time.sleep(CLIPBOARD_POLL_INTERVAL_S)

            if original_text is not None:
                self._write_clipboard(original_text)

            if copied_text and copied_text.strip():
                return copied_text

            logger.debug("Clipboard copy did not produce a new text payload")
            return None

        except Exception:
            logger.debug("Clipboard acquisition error", exc_info=True)
            return None

    def _get_clipboard_sequence_number(self) -> int:
        try:
            return int(ctypes.windll.user32.GetClipboardSequenceNumber())
        except (AttributeError, OSError):
            return 0

    def _read_clipboard(self) -> str | None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            return None
        try:
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            h_data = user32.GetClipboardData(CF_UNICODETEXT)
            if not h_data:
                return None
            p_data = kernel32.GlobalLock(h_data)
            if not p_data:
                return None
            try:
                return ctypes.wstring_at(p_data)
            finally:
                kernel32.GlobalUnlock(h_data)
        finally:
            user32.CloseClipboard()

    def _write_clipboard(self, text: str) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            return
        try:
            user32.EmptyClipboard()
            byte_len = (len(text) + 1) * 2
            h_mem = kernel32.GlobalAlloc(0x0042, byte_len)
            if not h_mem:
                return
            p_mem = kernel32.GlobalLock(h_mem)
            if p_mem:
                ctypes.memmove(p_mem, text, len(text) * 2)
                kernel32.GlobalUnlock(h_mem)
                user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        finally:
            user32.CloseClipboard()

    def _send_ctrl_c(self) -> None:
        """Simulate Ctrl+C keypress via SendInput."""

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.wintypes.DWORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", ctypes.wintypes.DWORD),
                ("wParamL", ctypes.wintypes.WORD),
                ("wParamH", ctypes.wintypes.WORD),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [
                    ("mi", MOUSEINPUT),
                    ("ki", KEYBDINPUT),
                    ("hi", HARDWAREINPUT),
                ]
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("union", _INPUT_UNION),
            ]

        inputs = (INPUT * 4)()

        inputs[0].type = INPUT_KEYBOARD
        inputs[0].union.ki.wVk = VK_CONTROL

        inputs[1].type = INPUT_KEYBOARD
        inputs[1].union.ki.wVk = VK_C

        inputs[2].type = INPUT_KEYBOARD
        inputs[2].union.ki.wVk = VK_C
        inputs[2].union.ki.dwFlags = KEYEVENTF_KEYUP

        inputs[3].type = INPUT_KEYBOARD
        inputs[3].union.ki.wVk = VK_CONTROL
        inputs[3].union.ki.dwFlags = KEYEVENTF_KEYUP

        ctypes.windll.user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
