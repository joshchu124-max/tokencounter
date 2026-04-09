"""Tests for tray interactions."""

from __future__ import annotations

from tokencounter.tray import ID_ENABLE, ID_OPEN_PANEL, TrayIcon, WM_LBUTTONDBLCLK


class _FakeConfig:
    enabled = True


class _FakeConfigManager:
    @property
    def config(self) -> _FakeConfig:
        return _FakeConfig()


class _FakeApp:
    def __init__(self) -> None:
        self.config_mgr = _FakeConfigManager()
        self.show_control_panel_calls = 0
        self.config_changes: list[tuple[str, object]] = []

    def show_control_panel(self) -> None:
        self.show_control_panel_calls += 1

    def on_config_changed(self, key: str, value: object) -> None:
        self.config_changes.append((key, value))


class TestTrayIcon:
    def test_double_click_opens_control_panel(self):
        app = _FakeApp()
        tray = TrayIcon(app)

        tray.handle_message(0, 0, 0, WM_LBUTTONDBLCLK)

        assert app.show_control_panel_calls == 1

    def test_open_panel_command_opens_control_panel(self):
        app = _FakeApp()
        tray = TrayIcon(app)

        tray._handle_menu_command(ID_OPEN_PANEL)

        assert app.show_control_panel_calls == 1

    def test_enable_command_still_toggles_enabled(self):
        app = _FakeApp()
        tray = TrayIcon(app)

        tray._handle_menu_command(ID_ENABLE)

        assert app.config_changes == [("enabled", False)]
