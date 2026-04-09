"""Entry point for TokenCounter.

Ensures single-instance via a Win32 named mutex, then starts the app.
Run with: python -m tokencounter
"""

from __future__ import annotations

import ctypes
import logging
import sys
import traceback

from tokencounter.utils import setup_logging, set_dpi_aware


def _ensure_single_instance() -> bool:
    """Create a named mutex. Returns True if this is the first instance."""
    try:
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\TokenCounterMutex_v1"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = kernel32.GetLastError()
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            kernel32.CloseHandle(handle)
            return False
        return True
    except (AttributeError, OSError):
        return True


def _show_already_running() -> None:
    """Show a message box indicating the app is already running."""
    try:
        ctypes.windll.user32.MessageBoxW(
            None,
            "TokenCounter is already running.\nCheck the system tray.",
            "TokenCounter",
            0x40,
        )
    except (AttributeError, OSError):
        print("TokenCounter is already running.", file=sys.stderr)


def main() -> None:
    logger = setup_logging()

    try:
        set_dpi_aware()

        if not _ensure_single_instance():
            _show_already_running()
            sys.exit(0)

        logger.info("TokenCounter starting up")

        from tokencounter.app import App
        app = App()
        app.run()

    except Exception:
        logger.critical("Unhandled exception:\n%s", traceback.format_exc())
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"TokenCounter encountered an error:\n{traceback.format_exc()[-500:]}",
                "TokenCounter Error",
                0x10,
            )
        except (AttributeError, OSError):
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
