# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-09

### Added

- Double-press Ctrl hotkey to trigger token counting on selected text
- Simulated Ctrl+C clipboard acquisition with automatic clipboard restoration
- GPT-4o (`o200k_base`) and GPT-4 (`cl100k_base`) tokenizer support via tiktoken
- Extensible tokenizer registry with abstract provider pattern
- Modern dark-themed floating tooltip with auto-fade animation
- Tooltip displays token count, character count, and active tokenizer name
- Mouse hover pauses tooltip fade-out
- Configurable tooltip display duration (1 / 2 / 3 / 5 seconds)
- Smart tooltip positioning with screen-edge clamping
- System tray icon with right-click context menu (enable/disable, tokenizer, duration, exit)
- Double-click tray icon to toggle enable/disable
- Calculate from clipboard option in tray menu
- Process blacklist support to exclude specific applications
- Injected keystroke filtering to ignore synthetic key events
- Duplicate text detection within 2-second window to prevent repeated counts
- 1-second throttle between triggers
- Single-instance enforcement via Win32 named mutex
- DPI awareness for crisp rendering on high-DPI displays
- Configuration persistence to `%APPDATA%\TokenCounter\config.json` with atomic writes
- File logging to `%APPDATA%\TokenCounter\tokencounter.log`
- PyInstaller single-file exe packaging with bundled tiktoken data
- Bilingual documentation (English and Chinese)

[Unreleased]: https://github.com/joshchu124-max/tokencounter/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/joshchu124-max/tokencounter/releases/tag/v0.1.0
