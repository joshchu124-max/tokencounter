"""Application orchestrator: wires all modules, manages threading, runs the message pump."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import logging
import queue
import threading
import time

from tokencounter.config import ConfigManager
from tokencounter.constants import (
    DEDUP_WINDOW_S,
    WM_APP_RESULT_READY,
    WM_APP_TRAY_CALLBACK,
)
from tokencounter.tokenizer_adapter import TokenizerRegistry

logger = logging.getLogger("tokencounter")


class App:
    """Central application class."""

    def __init__(self) -> None:
        self.config_mgr = ConfigManager()

        self.registry = TokenizerRegistry()
        cfg = self.config_mgr.config
        try:
            self.registry.set_active(cfg.tokenizer)
        except ValueError:
            logger.warning("Unknown tokenizer %r in config, using default", cfg.tokenizer)

        self._work_queue: queue.Queue[tuple[int, int] | None] = queue.Queue()
        self._result_lock = threading.Lock()
        self._last_result: dict | None = None

        self._last_text_hash: str = ""
        self._last_text_time: float = 0.0
        self._main_hwnd: int = 0

        self._tray = None
        self._tooltip = None
        self._hooks = None
        self._acquirer = None
        self._worker_thread: threading.Thread | None = None
        self._tooltip_thread: threading.Thread | None = None

    def run(self) -> None:
        from tokencounter.acquisition import TextAcquirer
        from tokencounter.hooks import HookManager
        from tokencounter.tooltip import TooltipWindow
        from tokencounter.tray import TrayIcon

        self._main_hwnd = self._create_message_window()
        logger.info("Message window created: hwnd=%s", self._main_hwnd)

        self._acquirer = TextAcquirer()
        self._tooltip = TooltipWindow(config_mgr=self.config_mgr)
        self._tray = TrayIcon(self)
        self._hooks = HookManager(on_trigger=self.on_trigger, config=self.config_mgr.config)

        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="TokenWorker", daemon=True
        )
        self._worker_thread.start()

        self._tooltip_thread = threading.Thread(
            target=self._tooltip.run, name="TooltipThread", daemon=True
        )
        self._tooltip_thread.start()

        self._tray.create()
        self._hooks.install()
        logger.info("All subsystems started, entering message pump")

        self._message_pump()

    def shutdown(self) -> None:
        logger.info("Shutting down")

        if self._hooks:
            self._hooks.uninstall()

        if self._tray:
            self._tray.destroy()

        if self._tooltip:
            self._tooltip.stop()

        self._work_queue.put(None)

        try:
            ctypes.windll.user32.PostQuitMessage(0)
        except (AttributeError, OSError):
            pass

    def on_trigger(self, mouse_x: int, mouse_y: int) -> None:
        cfg = self.config_mgr.config
        if not cfg.enabled:
            return

        from tokencounter.utils import get_foreground_process_name

        proc = get_foreground_process_name()
        if proc and proc.lower() in [b.lower() for b in cfg.blacklist]:
            logger.debug("Skipped: foreground process %s is blacklisted", proc)
            return

        self._work_queue.put((mouse_x, mouse_y))

    def on_clipboard_calculate(self) -> None:
        try:
            import win32clipboard

            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(13):
                    text = win32clipboard.GetClipboardData(13)
                else:
                    text = None
            finally:
                win32clipboard.CloseClipboard()

            if text:
                token_count = self.registry.active.count_tokens(text)
                cursor = ctypes.wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
                self._show_result(text, token_count, cursor.x, cursor.y)
        except Exception:
            logger.exception("Clipboard calculate failed")

    def on_config_changed(self, key: str, value: object) -> None:
        if key == "trigger_mode":
            value = "hotkey"

        self.config_mgr.update(**{key: value})

        if key == "tokenizer":
            try:
                self.registry.set_active(str(value))
            except ValueError:
                logger.warning("Unknown tokenizer: %s", value)

        logger.info("Config changed: %s = %r", key, value)

    def _worker_loop(self) -> None:
        logger.debug("Worker thread started")
        while True:
            item = self._work_queue.get()
            if item is None:
                logger.debug("Worker thread exiting")
                break

            mouse_x, mouse_y = item
            try:
                text = self._acquirer.acquire()
                if not text or not text.strip():
                    logger.info("Worker: no text acquired from clipboard (nothing selected?)")
                    continue

                text_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
                now = time.monotonic()
                if text_hash == self._last_text_hash and (now - self._last_text_time) < DEDUP_WINDOW_S:
                    continue
                self._last_text_hash = text_hash
                self._last_text_time = now

                token_count = self.registry.active.count_tokens(text)

                with self._result_lock:
                    self._last_result = {
                        "text": text,
                        "token_count": token_count,
                        "char_count": len(text),
                        "tokenizer_name": self.registry.active.name,
                        "mouse_x": mouse_x,
                        "mouse_y": mouse_y,
                    }

                try:
                    ctypes.windll.user32.PostMessageW(
                        self._main_hwnd, WM_APP_RESULT_READY, 0, 0
                    )
                except (AttributeError, OSError):
                    pass

            except Exception:
                logger.exception("Worker: error processing trigger at (%d, %d)", mouse_x, mouse_y)

    def _on_result_ready(self) -> None:
        with self._result_lock:
            result = self._last_result
            self._last_result = None

        if result and self._tooltip:
            self._show_result(
                result["text"],
                result["token_count"],
                result["mouse_x"],
                result["mouse_y"],
            )

    def _show_result(self, text: str, token_count: int, x: int, y: int) -> None:
        if self._tooltip:
            self._tooltip.show(
                token_count=token_count,
                char_count=len(text),
                tokenizer_name=self.registry.active.name,
                mouse_x=x,
                mouse_y=y,
            )

    def _create_message_window(self) -> int:
        """Create a message-only window for receiving PostMessage from worker."""
        LRESULT = ctypes.wintypes.LPARAM  # LONG_PTR — pointer-sized
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT,
            ctypes.wintypes.HWND,
            ctypes.c_uint,
            ctypes.wintypes.WPARAM,
            ctypes.wintypes.LPARAM,
        )
        ctypes.windll.user32.DefWindowProcW.argtypes = [
            ctypes.wintypes.HWND, ctypes.c_uint,
            ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM,
        ]
        ctypes.windll.user32.DefWindowProcW.restype = LRESULT

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
            if msg == WM_APP_RESULT_READY:
                self._on_result_ready()
                return 0
            if msg == WM_APP_TRAY_CALLBACK:
                if self._tray:
                    self._tray.handle_message(hwnd, msg, wparam, lparam)
                return 0
            return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc = WNDPROC(wnd_proc)

        class_name = "TokenCounterMsgWindow"
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._wnd_proc
        wc.lpszClassName = class_name
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)

        ctypes.windll.user32.RegisterClassW(ctypes.byref(wc))

        # HWND_MESSAGE = (HWND)(-3) — must use proper ctypes HWND cast
        # because -3 as a raw Python int overflows on 64-bit pointer args
        HWND_MESSAGE = ctypes.wintypes.HWND(-3)

        # Declare argtypes so ctypes marshals all 12 arguments correctly
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
            0,
            class_name,
            "TokenCounter",
            0,
            0, 0, 0, 0,
            HWND_MESSAGE,
            None,
            wc.hInstance,
            None,
        )
        return hwnd

    def _message_pump(self) -> None:
        msg = ctypes.wintypes.MSG()
        while ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        logger.info("Message pump exited")
