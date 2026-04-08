"""Centralized constants for TokenCounter."""

import os

# ---------------------------------------------------------------------------
# Timing (seconds unless noted)
# ---------------------------------------------------------------------------
DEBOUNCE_S = 0.35                   # Wait after mouse-up before acquiring text
THROTTLE_INTERVAL_S = 1.0           # Min interval between consecutive triggers
DEDUP_WINDOW_S = 2.0                # Suppress repeated popup for identical text
STRATEGY_TIMEOUT_S = 0.2            # Per-strategy timeout in acquisition chain
HOTKEY_DOUBLE_TAP_S = 0.5           # Max gap for double-tap hotkey detection
TOOLTIP_DISPLAY_S = 3.5             # Auto-dismiss delay for floating tooltip
TOOLTIP_FADE_STEP_S = 0.05          # Interval for each fade-out step
CLIPBOARD_SETTLE_S = 0.1            # Wait after simulated Ctrl+C

# ---------------------------------------------------------------------------
# Tooltip geometry (pixels)
# ---------------------------------------------------------------------------
TOOLTIP_WIDTH = 280
TOOLTIP_HEIGHT = 80
TOOLTIP_OFFSET_X = 20               # Cursor offset for placement
TOOLTIP_OFFSET_Y = 20
TOOLTIP_CORNER_RADIUS = 8

# ---------------------------------------------------------------------------
# Mouse selection heuristic
# ---------------------------------------------------------------------------
MIN_DRAG_DISTANCE_PX = 5            # Below this, treat as click not selection

# ---------------------------------------------------------------------------
# Win32 hook types
# ---------------------------------------------------------------------------
WH_MOUSE_LL = 14
WH_KEYBOARD_LL = 13

# ---------------------------------------------------------------------------
# Win32 mouse messages
# ---------------------------------------------------------------------------
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_MOUSEMOVE = 0x0200

# ---------------------------------------------------------------------------
# Win32 keyboard messages
# ---------------------------------------------------------------------------
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# ---------------------------------------------------------------------------
# Virtual key codes
# ---------------------------------------------------------------------------
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_CONTROL = 0x11

# ---------------------------------------------------------------------------
# Win32 text messages
# ---------------------------------------------------------------------------
EM_GETSEL = 0x00B0
EM_GETSELTEXT = 0x0434
EM_EXGETSEL = 0x0434      # RichEdit extended get-selection (WM_USER+52 = 0x0434)
WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_COPY = 0x0301

# ---------------------------------------------------------------------------
# Win32 window styles
# ---------------------------------------------------------------------------
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000

# ---------------------------------------------------------------------------
# Custom window messages (WM_APP = 0x8000)
# ---------------------------------------------------------------------------
WM_APP = 0x8000
WM_APP_SHOW_TOOLTIP = WM_APP + 1
WM_APP_HIDE_TOOLTIP = WM_APP + 2
WM_APP_TRAY_CALLBACK = WM_APP + 10
WM_APP_RESULT_READY = WM_APP + 20

# ---------------------------------------------------------------------------
# Clipboard formats
# ---------------------------------------------------------------------------
CF_UNICODETEXT = 13

# ---------------------------------------------------------------------------
# SendInput constants
# ---------------------------------------------------------------------------
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_C = 0x43

# ---------------------------------------------------------------------------
# UI Automation pattern IDs
# ---------------------------------------------------------------------------
UIA_TextPatternId = 10014
UIA_ValuePatternId = 10002

# ---------------------------------------------------------------------------
# Application paths
# ---------------------------------------------------------------------------
APP_NAME = "TokenCounter"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LOG_FILE = os.path.join(CONFIG_DIR, "tokencounter.log")
