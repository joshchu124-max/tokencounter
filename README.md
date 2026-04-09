# TokenCounter

A lightweight Windows desktop tool for local token counting. Select text, then double-press Ctrl to copy the selection in the background and instantly see the token count.

## Features

- **Double-press hotkey trigger** — No automatic popups while selecting; calculation starts only when you double-press Ctrl
- **Clipboard-driven acquisition** — Explicitly copies the current selection on trigger, which is more reliable than passive selection detection
- **Stale-result protection** — Waits for a real clipboard sequence change before accepting copied text, preventing old results from being shown again
- **100% local** — All tokenization happens locally, no API calls
- **Multiple tokenizers** — Switch between GPT-4o (`o200k_base`) and GPT-4 (`cl100k_base`)
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
3. Double-press Ctrl
4. A floating tooltip shows: token count, character count, and current tokenizer
5. Right-click the tray icon to:
   - Enable/disable the tool
   - Switch tokenizer
   - Calculate from clipboard
   - Exit

## Configuration

Settings are stored in `%APPDATA%/TokenCounter/config.json`:

- `tokenizer`: Active encoding (`"o200k_base"` or `"cl100k_base"`)
- `trigger_mode`: Stored as `"hotkey"` for compatibility; automatic mode is no longer used
- `enabled`: Master on/off switch
- `blacklist`: List of process names to ignore (e.g. `["game.exe"]`)

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## Architecture

```text
tokencounter/
├── hooks.py              # Global double-press Ctrl detection
├── acquisition.py        # Explicit Ctrl+C + clipboard sequence validation
├── tokenizer_adapter.py  # Tokenizer abstraction + tiktoken implementation
├── tooltip.py            # Floating tooltip window (Win32 API)
├── tray.py               # System tray icon and menu
├── config.py             # Configuration persistence
├── app.py                # Application orchestrator and threading model
└── __main__.py           # Entry point
```
