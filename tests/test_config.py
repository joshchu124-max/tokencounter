"""Tests for the configuration module."""

import json
import os
from unittest import mock

import pytest
from tokencounter.config import Config, ConfigManager


@pytest.fixture
def tmp_config_dir(tmp_path):
    config_file = str(tmp_path / "config.json")
    with mock.patch("tokencounter.config.CONFIG_DIR", str(tmp_path)), \
         mock.patch("tokencounter.config.CONFIG_FILE", config_file):
        yield tmp_path, config_file


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.tokenizer == "o200k_base"
        assert cfg.trigger_mode == "hotkey"
        assert cfg.hotkey_vk == 0xA2
        assert cfg.enabled is True
        assert cfg.blacklist == []

    def test_custom_values(self):
        cfg = Config(tokenizer="cl100k_base", enabled=False)
        assert cfg.tokenizer == "cl100k_base"
        assert cfg.enabled is False


class TestConfigManager:
    def test_load_missing_file(self, tmp_config_dir):
        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"
        assert cfg.enabled is True

    def test_save_and_load(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        mgr = ConfigManager()
        mgr.update(tokenizer="cl100k_base", enabled=False)

        assert os.path.isfile(config_file)
        with open(config_file, "r") as f:
            data = json.load(f)
        assert data["tokenizer"] == "cl100k_base"
        assert data["enabled"] is False

        mgr2 = ConfigManager()
        cfg2 = mgr2.config
        assert cfg2.tokenizer == "cl100k_base"
        assert cfg2.enabled is False

    def test_update_returns_new_config(self, tmp_config_dir):
        mgr = ConfigManager()
        new_cfg = mgr.update(trigger_mode="hotkey")
        assert new_cfg.trigger_mode == "hotkey"
        assert mgr.config.trigger_mode == "hotkey"

    def test_update_invalid_key(self, tmp_config_dir):
        mgr = ConfigManager()
        with pytest.raises(ValueError, match="Unknown config key"):
            mgr.update(nonexistent_key="value")

    def test_corrupt_file_fallback(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            f.write("{this is not valid json!!!")

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"

    def test_partial_config_forces_hotkey_mode(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            json.dump({"tokenizer": "cl100k_base", "trigger_mode": "auto"}, f)

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "cl100k_base"
        assert cfg.enabled is True
        assert cfg.trigger_mode == "hotkey"

    def test_unknown_keys_ignored(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        with open(config_file, "w") as f:
            json.dump({"tokenizer": "o200k_base", "future_key": "future_value"}, f)

        mgr = ConfigManager()
        cfg = mgr.config
        assert cfg.tokenizer == "o200k_base"

    def test_config_is_copy(self, tmp_config_dir):
        mgr = ConfigManager()
        cfg1 = mgr.config
        cfg1.tokenizer = "changed"
        cfg2 = mgr.config
        assert cfg2.tokenizer == "o200k_base"
