"""Windows startup integration via the current user's Run registry key."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

from tokencounter.constants import APP_NAME

logger = logging.getLogger("tokencounter")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def build_startup_command(
    *,
    executable: str | None = None,
    argv0: str | None = None,
    is_frozen: bool | None = None,
    module_name: str = "tokencounter",
) -> str:
    """Build the command line stored in the Run registry key."""

    executable = executable or sys.executable
    argv0 = argv0 or sys.argv[0]
    if is_frozen is None:
        is_frozen = bool(getattr(sys, "frozen", False))

    if is_frozen:
        args = [executable]
    elif os.path.splitext(argv0)[1].lower() == ".exe" and os.path.isabs(argv0):
        args = [argv0]
    else:
        args = [_prefer_windowless_python(executable), "-m", module_name]

    return subprocess.list2cmdline(args)


def _prefer_windowless_python(executable: str) -> str:
    """Use pythonw.exe when available to avoid a console window on login."""

    if os.path.basename(executable).lower() != "python.exe":
        return executable

    pythonw = os.path.join(os.path.dirname(executable), "pythonw.exe")
    return pythonw if os.path.isfile(pythonw) else executable


class StartupManager:
    """Manage the app's Windows startup registration."""

    def __init__(self, *, registry: Any | None = None, value_name: str = APP_NAME) -> None:
        self._registry = registry
        self._value_name = value_name

    def is_enabled(self) -> bool:
        registry = self._get_registry()
        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                registry.KEY_READ,
            ) as key:
                value, _ = registry.QueryValueEx(key, self._value_name)
        except FileNotFoundError:
            return False

        return bool(str(value).strip())

    def set_enabled(self, enabled: bool) -> None:
        registry = self._get_registry()

        if enabled:
            command = build_startup_command()
            with registry.CreateKey(registry.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
                registry.SetValueEx(key, self._value_name, 0, registry.REG_SZ, command)
            logger.info("Startup registration enabled")
            return

        try:
            with registry.OpenKey(
                registry.HKEY_CURRENT_USER,
                RUN_KEY_PATH,
                0,
                registry.KEY_SET_VALUE,
            ) as key:
                registry.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            pass

        logger.info("Startup registration disabled")

    def _get_registry(self) -> Any:
        if self._registry is None:
            import winreg

            self._registry = winreg
        return self._registry
