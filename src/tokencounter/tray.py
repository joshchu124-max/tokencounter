"""System tray icon with right-click context menu."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
from typing import TYPE_CHECKING

from tokencounter.constants import WM_APP_TRAY_CALLBACK

if TYPE_CHECKING:
    from tokencounter.app import App

logger = logging.getLogger("tokencounter")

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000

ID_ENABLE = 1001
ID_TOK_O200K = 1020
ID_TOK_CL100K = 1021
ID_CLIPBOARD = 1030
ID_DURATION_1 = 1040
ID_DURATION_2 = 1041
ID_DURATION_3 = 1042
ID_DURATION_5 = 1043
ID_EXIT = 1099

_DURATION_OPTIONS = [
    (ID_DURATION_1, 1.0, "1 秒"),
    (ID_DURATION_2, 2.0, "2 秒"),
    (ID_DURATION_3, 3.0, "3 秒"),
    (ID_DURATION_5, 5.0, "5 秒"),
]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.wintypes.HICON),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.wintypes.HICON),
    ]


class TrayIcon:
    def __init__(self, app: App) -> None:
        self._app = app
        self._nid: NOTIFYICONDATAW | None = None
        self._icon_handle = None

    def create(self) -> None:
        hwnd = self._app._main_hwnd
        self._icon_handle = self._load_icon()

        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY_CALLBACK
        nid.hIcon = self._icon_handle
        nid.szTip = "TokenCounter"
        self._nid = nid

        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        logger.info("Tray icon created")

    def destroy(self) -> None:
        if self._nid:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
            logger.info("Tray icon destroyed")

    def show_balloon(self, title: str, message: str) -> None:
        if not self._nid:
            return
        nid = self._nid
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = message[:255]
        nid.dwInfoFlags = 0x01
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP

    def handle_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        if lparam == WM_RBUTTONUP:
            self._show_context_menu(hwnd)
        elif lparam == WM_LBUTTONDBLCLK:
            cfg = self._app.config_mgr.config
            self._app.on_config_changed("enabled", not cfg.enabled)

    def _show_context_menu(self, hwnd: int) -> None:
        user32 = ctypes.windll.user32
        cfg = self._app.config_mgr.config

        menu = user32.CreatePopupMenu()

        enable_text = "Disable" if cfg.enabled else "Enable"
        flags = MF_STRING | (MF_CHECKED if cfg.enabled else MF_UNCHECKED)
        user32.AppendMenuW(menu, flags, ID_ENABLE, f"✓  {enable_text}" if cfg.enabled else f"    {enable_text}")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, 0, "Trigger: double-press Ctrl")

        tok_menu = user32.CreatePopupMenu()
        active_enc = self._app.registry.active.encoding_name
        for enc_name, provider in self._app.registry.providers.items():
            item_id = ID_TOK_O200K if enc_name == "o200k_base" else ID_TOK_CL100K
            flags = MF_STRING | (MF_CHECKED if enc_name == active_enc else MF_UNCHECKED)
            user32.AppendMenuW(tok_menu, flags, item_id, provider.name)
        user32.AppendMenuW(menu, 0x0010, tok_menu, "Tokenizer")

        # Display duration submenu
        dur_menu = user32.CreatePopupMenu()
        current_dur = cfg.tooltip_display_s
        for item_id, seconds, label in _DURATION_OPTIONS:
            flags = MF_STRING | (MF_CHECKED if abs(current_dur - seconds) < 0.1 else MF_UNCHECKED)
            user32.AppendMenuW(dur_menu, flags, item_id, label)
        user32.AppendMenuW(menu, 0x0010, dur_menu, "Display Duration")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_CLIPBOARD, "Calculate from Clipboard")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Exit")

        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_LEFTALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, hwnd, None
        )
        user32.DestroyMenu(menu)

        self._handle_menu_command(cmd)

    def _handle_menu_command(self, cmd: int) -> None:
        if cmd == ID_ENABLE:
            cfg = self._app.config_mgr.config
            self._app.on_config_changed("enabled", not cfg.enabled)
        elif cmd == ID_TOK_O200K:
            self._app.on_config_changed("tokenizer", "o200k_base")
        elif cmd == ID_TOK_CL100K:
            self._app.on_config_changed("tokenizer", "cl100k_base")
        elif cmd == ID_CLIPBOARD:
            self._app.on_clipboard_calculate()
        elif cmd in (ID_DURATION_1, ID_DURATION_2, ID_DURATION_3, ID_DURATION_5):
            for item_id, seconds, _ in _DURATION_OPTIONS:
                if cmd == item_id:
                    self._app.on_config_changed("tooltip_display_s", seconds)
                    break
        elif cmd == ID_EXIT:
            self._app.shutdown()

    def _load_icon(self) -> int:
        icon_paths = []
        if getattr(sys, "_MEIPASS", None):
            icon_paths.append(os.path.join(sys._MEIPASS, "assets", "icon.ico"))
        icon_paths.append(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "icon.ico")
        )

        for path in icon_paths:
            path = os.path.normpath(path)
            if os.path.isfile(path):
                icon = ctypes.windll.user32.LoadImageW(
                    None, path, 1, 16, 16, 0x0010
                )
                if icon:
                    return icon

        return ctypes.windll.user32.LoadIconW(None, 32512)
