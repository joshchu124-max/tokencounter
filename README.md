# TokenCounter

<p align="center">
  <strong>A lightweight Windows desktop tool for local token counting.</strong><br>
  Select text in any application, double-press Ctrl, and instantly see the token count.
</p>

<p align="center">
  <a href="https://github.com/JoshChu/tokencounter/releases"><img alt="Release" src="https://img.shields.io/github/v/release/JoshChu/tokencounter?style=flat-square"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-AGPL--3.0-blue?style=flat-square"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010+-0078d4?style=flat-square&logo=windows">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white">
</p>

<p align="center">
  <strong>English</strong> | <a href="README_zh.md">中文</a>
</p>

---

## Features

- **Double-press Ctrl trigger** — Select text in any app, double-press Ctrl to see the token count
- **100% local** — All tokenization happens locally via [tiktoken](https://github.com/openai/tiktoken), zero network calls
- **Multiple tokenizers** — Switch between GPT-4o (`o200k_base`) and GPT-4 (`cl100k_base`)
- **Floating tooltip** — Modern dark-themed tooltip that auto-fades, with configurable display duration
- **System tray** — Lives in your system tray with right-click menu for all settings
- **Single exe** — Distributable as a single portable `.exe` file

## Quick Start

### Option 1: Download the exe

Download `TokenCounter.exe` from the [Releases](https://github.com/JoshChu/tokencounter/releases) page and run it. No installation required.

### Option 2: Run from source

```bash
git clone https://github.com/JoshChu/tokencounter.git
cd tokencounter
pip install -r requirements.txt
python -m tokencounter
```

### Build standalone exe

```bash
pip install -r requirements-dev.txt
# Cache tiktoken data locally:
python -c "import tiktoken; tiktoken.get_encoding('o200k_base'); tiktoken.get_encoding('cl100k_base')"
# Build:
pyinstaller tokencounter.spec
# Output: dist/TokenCounter.exe
```

## Usage

1. Launch `TokenCounter.exe` — an icon appears in the system tray
2. Select text in **any** application
3. **Double-press Ctrl** — a floating tooltip shows token count, character count, and the active tokenizer
4. Right-click the tray icon to:
   - Enable / disable
   - Switch tokenizer (GPT-4o / GPT-4)
   - Adjust tooltip display duration (1–5 s)
   - Calculate from clipboard
   - Exit

## Configuration

Settings are persisted to `%APPDATA%\TokenCounter\config.json`:

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tokenizer` | `string` | `"o200k_base"` | Active encoding name |
| `hotkey_vk` | `int` | `0xA2` | Virtual key code for trigger (left Ctrl) |
| `enabled` | `bool` | `true` | Master on/off switch |
| `tooltip_display_s` | `float` | `2.0` | Tooltip display duration in seconds |
| `blacklist` | `string[]` | `[]` | Process names to ignore |

## Architecture

```
src/tokencounter/
├── __main__.py           # Entry point & single-instance mutex
├── app.py                # Application orchestrator & Win32 message pump
├── hooks.py              # Global keyboard hook (double-press Ctrl detection)
├── acquisition.py        # Text acquisition via simulated Ctrl+C
├── tokenizer_adapter.py  # Tokenizer abstraction + tiktoken backends
├── tooltip.py            # Floating tooltip window (Win32 GDI)
├── tray.py               # System tray icon & context menu
├── config.py             # Configuration persistence (JSON)
├── constants.py          # Shared constants
└── utils.py              # DPI awareness, screen geometry, logging
```

## Development

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).

Copyright (c) 2026 Josh Chu
