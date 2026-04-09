"""Configuration management for TokenCounter.

Persists user settings to %APPDATA%/TokenCounter/config.json with
atomic writes and fault-tolerant loading.
"""

from __future__ import annotations

import dataclasses
import json
import os
import threading

from tokencounter.constants import CONFIG_DIR, CONFIG_FILE


@dataclasses.dataclass
class Config:
    """User-facing configuration. All fields have safe defaults."""

    tokenizer: str = "o200k_base"
    trigger_mode: str = "hotkey"
    hotkey_vk: int = 0xA2
    enabled: bool = True
    blacklist: list[str] = dataclasses.field(default_factory=list)


class ConfigManager:
    """Thread-safe configuration loader/saver."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._config = self._load()

    @property
    def config(self) -> Config:
        with self._lock:
            return dataclasses.replace(self._config)

    def update(self, **kwargs: object) -> Config:
        with self._lock:
            for key, value in kwargs.items():
                if not hasattr(self._config, key):
                    raise ValueError(f"Unknown config key: {key}")
                setattr(self._config, key, value)
            self._save(self._config)
            return dataclasses.replace(self._config)

    @staticmethod
    def _load() -> Config:
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return Config()
            valid_fields = {field.name for field in dataclasses.fields(Config)}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            cfg = Config(**filtered)
            if cfg.trigger_mode != "hotkey":
                cfg.trigger_mode = "hotkey"
            return cfg
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            return Config()

    @staticmethod
    def _save(config: Config) -> None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp_path = CONFIG_FILE + ".tmp"
        data = dataclasses.asdict(config)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_FILE)
