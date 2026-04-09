# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-04-09

### Added

- Double-press Ctrl hotkey to trigger token counting on selected text
- Simulated Ctrl+C clipboard acquisition with automatic clipboard restoration
- GPT-4o (`o200k_base`) and GPT-4 (`cl100k_base`) tokenizer support via tiktoken
- Modern dark-themed floating tooltip with auto-fade animation
- Configurable tooltip display duration (1 / 2 / 3 / 5 seconds)
- System tray icon with right-click context menu
- Calculate from clipboard option in tray menu
- Process blacklist support
- Single-instance enforcement via Win32 named mutex
- Configuration persistence to `%APPDATA%\TokenCounter\config.json`
- PyInstaller single-file exe packaging with bundled tiktoken data
