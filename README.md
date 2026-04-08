# TokenCounter

A lightweight Windows desktop tool for local token counting. Select text in any application and instantly see the token count.

## Features

- **Auto-detect text selection** — Automatically detects when you select text with your mouse and shows token count
- **Double-press hotkey mode** — Alternative trigger via double-pressing Ctrl
- **100% local** — All tokenization happens locally, no API calls
- **Multiple tokenizers** — Switch between GPT-4o (o200k_base) and GPT-4 (cl100k_base)
- **Lightweight tooltip** — Non-intrusive floating tooltip that auto-fades
- **System tray** — Lives in your system tray with easy access to settings

## Requirements

- Windows 10 or later
- Python 3.11+ (for development)

## Quick Start

### Run from source

```bash
pip install -r requirements.txt
python -m tokencounter
```

### Build standalone exe

```bash
pip install -r requirements-dev.txt
# Ensure tiktoken data is cached first:
python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"
# Build:
pyinstaller tokencounter.spec
# Output: dist/TokenCounter.exe
```

## Usage

1. Launch TokenCounter — it appears as an icon in your system tray
2. Select text in any application
3. A floating tooltip shows: token count, character count, and current tokenizer
4. Right-click the tray icon to:
   - Enable/disable the tool
   - Switch trigger mode (auto-detect / double-press hotkey)
   - Switch tokenizer
   - Calculate from clipboard
   - Exit

## Configuration

Settings are stored in `%APPDATA%/TokenCounter/config.json`:

- `tokenizer`: Active encoding (`"o200k_base"` or `"cl100k_base"`)
- `trigger_mode`: `"auto"` (mouse selection) or `"hotkey"` (double-press key)
- `enabled`: Master on/off switch
- `blacklist`: List of process names to ignore (e.g. `["game.exe"]`)

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Architecture

```
tokencounter/
├── hooks.py              # Global mouse/keyboard hooks for trigger detection
├── acquisition.py        # Text acquisition strategy chain (UIA → Win32 → Clipboard)
├── tokenizer_adapter.py  # Tokenizer abstraction + tiktoken implementation
├── tooltip.py            # Floating tooltip window (Win32 API)
├── tray.py               # System tray icon and menu
├── config.py             # Configuration persistence
├── app.py                # Application orchestrator and threading model
└── __main__.py           # Entry point
```
