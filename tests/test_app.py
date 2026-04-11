"""Tests for app/control-panel integration."""

from __future__ import annotations

from unittest import mock

import pytest

from tokencounter.config import Config
from tokencounter.constants import WM_APP_REQUEST_SHUTDOWN


class _FakeProvider:
    def __init__(self, encoding_name: str, name: str) -> None:
        self.encoding_name = encoding_name
        self.name = name


class _FakeTokenizerRegistry:
    def __init__(self) -> None:
        self._providers = {
            "o200k_base": _FakeProvider("o200k_base", "GPT-4o (o200k_base)"),
            "cl100k_base": _FakeProvider("cl100k_base", "GPT-4 (cl100k_base)"),
        }
        self._active = self._providers["o200k_base"]

    @property
    def providers(self):
        return dict(self._providers)

    @property
    def active(self):
        return self._active

    def set_active(self, encoding_name: str) -> None:
        self._active = self._providers[encoding_name]


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.json")
    monkeypatch.setattr("tokencounter.config.CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("tokencounter.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("tokencounter.app.TokenizerRegistry", _FakeTokenizerRegistry)

    from tokencounter.app import App

    return App()


class TestAppControlPanelIntegration:
    def test_show_control_panel_delegates_to_panel(self, app_env):
        app = app_env
        app._control_panel = mock.Mock()

        app.show_control_panel()

        app._control_panel.show.assert_called_once_with()

    def test_on_blacklist_changed_persists_and_refreshes(self, app_env):
        app = app_env
        app._control_panel = mock.Mock()

        app.on_blacklist_changed(["Code.exe", "notepad.exe"])

        assert app.config_mgr.config.blacklist == ["Code.exe", "notepad.exe"]
        app._control_panel.refresh.assert_called_once_with()

    def test_on_startup_changed_updates_registry_and_refreshes(self, app_env):
        app = app_env
        app._control_panel = mock.Mock()
        app.startup_mgr = mock.Mock()

        app.on_startup_changed(True)

        app.startup_mgr.set_enabled.assert_called_once_with(True)
        app._control_panel.refresh.assert_called_once_with()

    def test_build_control_panel_state_reflects_runtime_state(self, app_env):
        app = app_env
        app.startup_mgr = mock.Mock()
        app.startup_mgr.is_enabled.return_value = True
        app.config_mgr.update(
            enabled=False,
            tokenizer="cl100k_base",
            tooltip_display_s=4.0,
            blacklist=["Code.exe"],
        )

        state = app._build_control_panel_state()

        assert state.enabled is False
        assert state.startup_enabled is True
        assert state.tokenizer == "cl100k_base"
        assert state.tooltip_display_s == 4.0
        assert state.blacklist_text == "Code.exe"

    def test_request_shutdown_posts_message_to_main_thread(self, app_env, monkeypatch):
        app = app_env
        app._main_hwnd = 123

        post_message = mock.Mock()
        user32 = mock.Mock(PostMessageW=post_message)
        windll = mock.Mock(user32=user32)
        monkeypatch.setattr("tokencounter.app.ctypes.windll", windll)

        app.request_shutdown()

        post_message.assert_called_once()
        assert post_message.call_args.args[:2] == (123, WM_APP_REQUEST_SHUTDOWN)

    def test_request_shutdown_falls_back_to_direct_shutdown_without_message_window(self, app_env):
        app = app_env
        app.shutdown = mock.Mock()

        app.request_shutdown()

        app.shutdown.assert_called_once_with()
