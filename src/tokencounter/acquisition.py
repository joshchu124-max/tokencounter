"""Module 2: Text acquisition strategy chain.

Attempts to read the currently selected text from the foreground application
using multiple strategies in order of preference:

1. UI Automation (comtypes IUIAutomation)
2. Win32 messages (EM_GETSEL / WM_GETTEXT for classic controls)
3. Clipboard fallback (simulate Ctrl+C, read clipboard, restore)

Each strategy has a timeout. If all fail, returns None (silent failure).
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import time

from tokencounter.constants import (
    CF_UNICODETEXT,
    CLIPBOARD_SETTLE_S,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    STRATEGY_TIMEOUT_S,
    VK_C,
    VK_CONTROL,
    WM_GETTEXT,
    WM_GETTEXTLENGTH,
)

logger = logging.getLogger("tokencounter")


class TextAcquirer:
    """Orchestrates the text acquisition strategy chain."""

    def acquire(self) -> str | None:
        """Try each strategy in order. Returns selected text or None."""
        for strategy_name, strategy_fn in [
            ("UIA", self._try_uia),
            ("Win32Msg", self._try_win32msg),
            ("Clipboard", self._try_clipboard),
        ]:
            try:
                text = strategy_fn()
                if text and text.strip():
                    logger.debug("Acquired text via %s (%d chars)", strategy_name, len(text))
                    return text
            except Exception:
                logger.debug("Strategy %s failed", strategy_name, exc_info=True)
        return None

    # -- Strategy 1: UI Automation -------------------------------------------

    def _try_uia(self) -> str | None:
        """Use Windows UI Automation to get the focused element's selected text."""
        try:
            import comtypes
            import comtypes.client
        except ImportError:
            return None

        try:
            # Ensure COM is initialized on this thread
            try:
                comtypes.CoInitialize()
            except OSError:
                pass  # Already initialized

            # Create IUIAutomation instance
            uia = comtypes.CoCreateInstance(
                comtypes.GUID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}"),  # CLSID_CUIAutomation
                interface=comtypes.gen.UIAutomationClient.IUIAutomation,
            )

            focused = uia.GetFocusedElement()
            if not focused:
                return None

            # Try TextPattern first (supports selection)
            try:
                text_pattern = focused.GetCurrentPatternAs(
                    10014,  # UIA_TextPatternId
                    comtypes.gen.UIAutomationClient.IUIAutomationTextPattern,
                )
                if text_pattern:
                    selection = text_pattern.GetSelection()
                    if selection and selection.Length > 0:
                        text_range = selection.GetElement(0)
                        text = text_range.GetText(-1)  # -1 = no length limit
                        if text:
                            return text
            except (AttributeError, comtypes.COMError):
                pass

            # Try ValuePattern (gets full control value, not selection)
            try:
                value_pattern = focused.GetCurrentPatternAs(
                    10002,  # UIA_ValuePatternId
                    comtypes.gen.UIAutomationClient.IUIAutomationValuePattern,
                )
                if value_pattern:
                    value = value_pattern.CurrentValue
                    if value:
                        return value
            except (AttributeError, comtypes.COMError):
                pass

            return None

        except Exception:
            logger.debug("UIA strategy error", exc_info=True)
            return None

    # -- Strategy 2: Win32 Messages ------------------------------------------

    def _try_win32msg(self) -> str | None:
        """Use Win32 SendMessage to get selected text from classic controls."""
        try:
            user32 = ctypes.windll.user32

            # Get foreground window and its thread
            fg_hwnd = user32.GetForegroundWindow()
            if not fg_hwnd:
                return None

            fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()

            # Attach to foreground thread to access its focus
            attached = False
            if fg_thread != current_thread:
                attached = bool(user32.AttachThreadInput(current_thread, fg_thread, True))

            try:
                focus_hwnd = user32.GetFocus()
                if not focus_hwnd:
                    return None

                # Get window class name
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(focus_hwnd, class_buf, 256)
                class_name = class_buf.value.lower()

                # Check for Edit-like controls
                if "edit" in class_name or "richedit" in class_name or "scintilla" in class_name:
                    return self._get_edit_selection(focus_hwnd, class_name)

                # Try generic WM_GETTEXT as fallback
                text_len = user32.SendMessageW(focus_hwnd, WM_GETTEXTLENGTH, 0, 0)
                if 0 < text_len < 100000:  # Sanity limit
                    buf = ctypes.create_unicode_buffer(text_len + 1)
                    user32.SendMessageW(focus_hwnd, WM_GETTEXT, text_len + 1, buf)
                    return buf.value or None

                return None
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, fg_thread, False)

        except Exception:
            logger.debug("Win32Msg strategy error", exc_info=True)
            return None

    def _get_edit_selection(self, hwnd: int, class_name: str) -> str | None:
        """Extract selected text from an Edit or RichEdit control."""
        user32 = ctypes.windll.user32

        # EM_GETSEL: wParam = &start, lParam = &end
        EM_GETSEL = 0x00B0
        start = ctypes.wintypes.DWORD()
        end = ctypes.wintypes.DWORD()
        user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))

        sel_start = start.value
        sel_end = end.value

        if sel_start == sel_end:
            return None  # Nothing selected

        # Get the full text
        text_len = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
        if text_len <= 0 or text_len > 1_000_000:
            return None

        buf = ctypes.create_unicode_buffer(text_len + 1)
        user32.SendMessageW(hwnd, WM_GETTEXT, text_len + 1, buf)
        full_text = buf.value

        if sel_end > len(full_text):
            sel_end = len(full_text)

        return full_text[sel_start:sel_end] or None

    # -- Strategy 3: Clipboard Fallback --------------------------------------

    def _try_clipboard(self) -> str | None:
        """Simulate Ctrl+C, read clipboard, restore original content."""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # Save current clipboard content
            original_text = self._read_clipboard()

            # Simulate Ctrl+C using SendInput
            self._send_ctrl_c()

            # Wait for the copy to complete
            time.sleep(CLIPBOARD_SETTLE_S)

            # Read the new clipboard content
            new_text = self._read_clipboard()

            # Restore original clipboard
            if original_text is not None:
                self._write_clipboard(original_text)

            # If clipboard changed, return the new content
            if new_text and new_text != original_text:
                return new_text

            # If clipboard didn't change, the text might already have been
            # the same as the selection, so return it anyway if non-empty
            if new_text:
                return new_text

            return None

        except Exception:
            logger.debug("Clipboard strategy error", exc_info=True)
            return None

    def _read_clipboard(self) -> str | None:
        """Read Unicode text from the clipboard."""
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
        """Write Unicode text to the clipboard."""
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(None):
            return
        try:
            user32.EmptyClipboard()
            byte_len = (len(text) + 1) * 2  # UTF-16 + null terminator
            h_mem = kernel32.GlobalAlloc(0x0042, byte_len)  # GMEM_MOVEABLE | GMEM_ZEROINIT
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

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", ctypes.wintypes.WORD),
                ("wScan", ctypes.wintypes.WORD),
                ("dwFlags", ctypes.wintypes.DWORD),
                ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
            ]

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = [("ki", KEYBDINPUT)]
            _fields_ = [
                ("type", ctypes.wintypes.DWORD),
                ("union", _INPUT_UNION),
            ]

        inputs = (INPUT * 4)()

        # Ctrl down
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].union.ki.wVk = VK_CONTROL

        # C down
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].union.ki.wVk = VK_C

        # C up
        inputs[2].type = INPUT_KEYBOARD
        inputs[2].union.ki.wVk = VK_C
        inputs[2].union.ki.dwFlags = KEYEVENTF_KEYUP

        # Ctrl up
        inputs[3].type = INPUT_KEYBOARD
        inputs[3].union.ki.wVk = VK_CONTROL
        inputs[3].union.ki.dwFlags = KEYEVENTF_KEYUP

        ctypes.windll.user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))
