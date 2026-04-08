"""Tests for the configuration module.

These tests are cross-platform. They use a temporary directory
to avoid touching real %APPDATA%.
"""

import json
import os
import tempfile
from unittest import mock

import pytest
from tokencounter.config import Config, ConfigManager


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Patch CONFIG_DIR and CONFIG_FILE to use a temp directory."""
    config_file = str(tmp_path / "config.json")
    with mock.patch("tokencounter.config.CONFIG_DIR", str(tmp_path)), \
         mock.patch("tokencounter.config.CONFIG_FILE", config_file):
        yield tmp_path, config_file


class TestConfig:
    """Tests for the Config dataclass."""

    def test_defaults(self):
        cfg = Config()
        assert cfg.tokenizer == "o200k_base"
        assert cfg.trigger_mode == "auto"
        assert cfg.hotkey_vk == 0xA2
        assert cfg.enabled is True
        assert cfg.blacklist == []

    def test_custom_values(self):
        cfg = Config(tokenizer="cl100k_base", enabled=False)
        assert cfg.tokenizer == "cl100k_base"
        assert cfg.enabled is False


class TestConfigManager:
    """Tests for the ConfigManager."""

    def test_load_missing_file(self, tmp_config_dir):
        """When config file doesn't exist, defaults are used."""
        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"
        assert cfg.enabled is True

    def test_save_and_load(self, tmp_config_dir):
        tmp_path, config_file = tmp_config_dir
        mgr = ConfigManager()
        mgr.update(tokenizer="cl100k_base", enabled=False)

        # Verify file was written
        assert os.path.isfile(config_file)
        with open(config_file, "r") as f:
            data = json.load(f)
        assert data["tokenizer"] == "cl100k_base"
        assert data["enabled"] is False

        # Load again from disk
        mgr2 = ConfigManager()
        cfg2 = mgr2.config
        assert cfg2.tokenizer == "cl100k_base"
        assert cfg2.enabled is False

    def test_update_returns_new_config(self, tmp_config_dir):
        mgr = ConfigManager()
        new_cfg = mgr.update(trigger_mode="hotkey")
        assert new_cfg.trigger_mode == "hotkey"
        # Verify internal state also updated
        assert mgr.config.trigger_mode == "hotkey"

    def test_update_invalid_key(self, tmp_config_dir):
        mgr = ConfigManager()
        with pytest.raises(ValueError, match="Unknown config key"):
            mgr.update(nonexistent_key="value")

    def test_corrupt_file_fallback(self, tmp_config_dir):
        """Corrupt JSON should fall back to defaults."""
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            f.write("{this is not valid json!!!")

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"  # Default

    def test_partial_config(self, tmp_config_dir):
        """Config with only some fields should fill in defaults for the rest."""
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            json.dump({"tokenizer": "cl100k_base"}, f)

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "cl100k_base"
        assert cfg.enabled is True  # Default
        assert cfg.trigger_mode == "auto"  # Default

    def test_unknown_keys_ignored(self, tmp_config_dir):
        """Config with unknown keys should load without error."""
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            json.dump({"tokenizer": "o200k_base", "future_key": "future_value"}, f)

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"

    def test_config_is_copy(self, tmp_config_dir):
        """Returned config should be a copy, not the internal reference."""
        mgr = ConfigManager()
        cfg1 = mgr.config
        cfg1.tokenizer = "changed"
        cfg2 = mgr.config
        assert cfg2.tokenizer == "o200k_base"  # Not affected
