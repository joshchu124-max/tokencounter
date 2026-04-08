"""Module 5 (UI part): System tray icon with right-click context menu.

The tray icon is the main user interface for TokenCounter.
Menu items: Enable/Disable, Trigger mode, Tokenizer selection,
Calculate from clipboard, Exit.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import struct
import sys
from typing import TYPE_CHECKING

from tokencounter.constants import WM_APP_TRAY_CALLBACK

if TYPE_CHECKING:
    from tokencounter.app import App

logger = logging.getLogger("tokencounter")

# Win32 constants for Shell_NotifyIcon
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

WM_RBUTTONUP = 0x0205
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203

TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
MF_UNCHECKED = 0x0000
MF_POPUP = 0x0010

# Menu item IDs
ID_ENABLE = 1001
ID_MODE_AUTO = 1010
ID_MODE_HOTKEY = 1011
ID_TOK_O200K = 1020
ID_TOK_CL100K = 1021
ID_CLIPBOARD = 1030
ID_EXIT = 1099


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
    """System tray icon with right-click menu."""

    def __init__(self, app: App) -> None:
        self._app = app
        self._nid: NOTIFYICONDATAW | None = None
        self._icon_handle = None

    def create(self) -> None:
        """Add the tray icon. Must be called from the main thread."""
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
        """Remove the tray icon."""
        if self._nid:
            ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            self._nid = None
            logger.info("Tray icon destroyed")

    def show_balloon(self, title: str, message: str) -> None:
        """Show a balloon notification from the tray icon."""
        if not self._nid:
            return
        nid = self._nid
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = message[:255]
        nid.dwInfoFlags = 0x01  # NIIF_INFO
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        # Restore flags
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP

    def handle_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> None:
        """Handle tray icon callback messages."""
        if lparam == WM_RBUTTONUP:
            self._show_context_menu(hwnd)
        elif lparam == WM_LBUTTONDBLCLK:
            # Double-click tray icon: toggle enabled
            cfg = self._app.config_mgr.config
            self._app.on_config_changed("enabled", not cfg.enabled)

    # -- context menu --------------------------------------------------------

    def _show_context_menu(self, hwnd: int) -> None:
        """Build and display the right-click context menu."""
        user32 = ctypes.windll.user32
        cfg = self._app.config_mgr.config

        menu = user32.CreatePopupMenu()

        # Enable / Disable toggle
        enable_text = "Disable" if cfg.enabled else "Enable"
        flags = MF_STRING | (MF_CHECKED if cfg.enabled else MF_UNCHECKED)
        user32.AppendMenuW(menu, flags, ID_ENABLE, f"✓  {enable_text}" if cfg.enabled else f"    {enable_text}")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

        # Trigger mode submenu
        mode_menu = user32.CreatePopupMenu()
        auto_flags = MF_STRING | (MF_CHECKED if cfg.trigger_mode == "auto" else MF_UNCHECKED)
        hotkey_flags = MF_STRING | (MF_CHECKED if cfg.trigger_mode == "hotkey" else MF_UNCHECKED)
        user32.AppendMenuW(mode_menu, auto_flags, ID_MODE_AUTO, "Auto-detect (mouse selection)")
        user32.AppendMenuW(mode_menu, hotkey_flags, ID_MODE_HOTKEY, "Double-press hotkey")
        user32.AppendMenuW(menu, MF_POPUP, mode_menu, "Trigger Mode")

        # Tokenizer submenu
        tok_menu = user32.CreatePopupMenu()
        active_enc = self._app.registry.active.encoding_name
        for enc_name, provider in self._app.registry.providers.items():
            item_id = ID_TOK_O200K if enc_name == "o200k_base" else ID_TOK_CL100K
            flags = MF_STRING | (MF_CHECKED if enc_name == active_enc else MF_UNCHECKED)
            user32.AppendMenuW(tok_menu, flags, item_id, provider.name)
        user32.AppendMenuW(menu, MF_POPUP, tok_menu, "Tokenizer")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

        # Calculate from clipboard
        user32.AppendMenuW(menu, MF_STRING, ID_CLIPBOARD, "Calculate from Clipboard")

        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

        # Exit
        user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Exit")

        # Show menu at cursor
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # SetForegroundWindow is required for the menu to close properly
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(
            menu, TPM_LEFTALIGN | TPM_RETURNCMD | TPM_NONOTIFY,
            pt.x, pt.y, 0, hwnd, None
        )
        user32.DestroyMenu(menu)

        self._handle_menu_command(cmd)

    def _handle_menu_command(self, cmd: int) -> None:
        """Dispatch menu item selection."""
        if cmd == ID_ENABLE:
            cfg = self._app.config_mgr.config
            self._app.on_config_changed("enabled", not cfg.enabled)
        elif cmd == ID_MODE_AUTO:
            self._app.on_config_changed("trigger_mode", "auto")
        elif cmd == ID_MODE_HOTKEY:
            self._app.on_config_changed("trigger_mode", "hotkey")
        elif cmd == ID_TOK_O200K:
            self._app.on_config_changed("tokenizer", "o200k_base")
        elif cmd == ID_TOK_CL100K:
            self._app.on_config_changed("tokenizer", "cl100k_base")
        elif cmd == ID_CLIPBOARD:
            self._app.on_clipboard_calculate()
        elif cmd == ID_EXIT:
            self._app.shutdown()

    # -- icon loading --------------------------------------------------------

    def _load_icon(self) -> int:
        """Load the tray icon. Uses bundled .ico if available, else default."""
        # Try loading custom icon from assets/
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
                    None, path, 1, 16, 16, 0x0010  # IMAGE_ICON, LR_LOADFROMFILE
                )
                if icon:
                    return icon

        # Fallback: use default application icon
        return ctypes.windll.user32.LoadIconW(None, 32512)  # IDI_APPLICATION
