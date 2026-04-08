"""Configuration management for TokenCounter.

Persists user settings to %APPDATA%/TokenCounter/config.json with
atomic writes and fault-tolerant loading.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading
from pathlib import Path

from tokencounter.constants import CONFIG_DIR, CONFIG_FILE


@dataclasses.dataclass
class Config:
    """User-facing configuration. All fields have safe defaults."""

    # Which tokenizer encoding to use (tiktoken encoding name)
    tokenizer: str = "o200k_base"

    # Trigger mode: "auto" (mouse selection detect) or "hotkey" (double-press key)
    trigger_mode: str = "auto"

    # Virtual key code for double-tap hotkey mode (default: left Ctrl = 0xA2)
    hotkey_vk: int = 0xA2

    # Master on/off switch
    enabled: bool = True

    # Process names to ignore (e.g. ["game.exe", "vlc.exe"])
    blacklist: list[str] = dataclasses.field(default_factory=list)


class ConfigManager:
    """Thread-safe configuration loader/saver.

    Usage::

        mgr = ConfigManager()
        cfg = mgr.config          # read current config
        mgr.update(tokenizer="cl100k_base")   # change & persist
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config = self._load()

    # -- public API ----------------------------------------------------------

    @property
    def config(self) -> Config:
        with self._lock:
            return dataclasses.replace(self._config)  # return a copy

    def update(self, **kwargs: object) -> Config:
        """Update one or more config fields and persist to disk."""
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self._config, key):
                    raise ValueError(f"Unknown config key: {key}")
                setattr(self._config, key, value)
            self._save(self._config)
            return dataclasses.replace(self._config)

    # -- persistence ---------------------------------------------------------

    @staticmethod
    def _load() -> Config:
        """Load config from disk. Returns defaults on any error."""
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return Config()
            # Only apply known fields, ignore unknown keys
            valid_fields = {field.name for field in dataclasses.fields(Config)}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return Config(**filtered)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return Config()

    @staticmethod
    def _save(config: Config) -> None:
        """Atomic save: write to temp file then rename."""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_path = CONFIG_FILE + ".tmp"
        data = dataclasses.asdict(config)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_FILE)
