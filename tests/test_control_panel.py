"""Tests for control panel helpers."""

from __future__ import annotations

from tokencounter.config import Config
from tokencounter.control_panel import (
    PanelState,
    build_panel_state,
    build_tokenizer_display_map,
    duration_to_choice,
    format_duration_label,
    get_system_theme,
    normalize_blacklist,
    toggle_advanced,
)


class _FakeThemeKey:
    def __init__(self, registry: "_FakeThemeRegistry") -> None:
        self._registry = registry

    def __enter__(self) -> "_FakeThemeKey":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeThemeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1

    def __init__(self, *, value: int | None) -> None:
        self._value = value

    def OpenKey(self, root, path: str, reserved: int = 0, access: int = 0) -> _FakeThemeKey:
        if self._value is None:
            raise FileNotFoundError(path)
        return _FakeThemeKey(self)

    def QueryValueEx(self, key: _FakeThemeKey, value_name: str) -> tuple[int, int]:
        return self._value, 1


class _Provider:
    def __init__(self, name: str) -> None:
        self.name = name


class TestNormalizeBlacklist:
    def test_trims_drops_empty_and_deduplicates_case_insensitively(self):
        value = "\n Code.exe \nnotepad.exe\ncode.exe\n   \nNotepad.exe\n"

        assert normalize_blacklist(value) == ["Code.exe", "notepad.exe"]


class TestGetSystemTheme:
    def test_returns_light_for_light_theme(self):
        assert get_system_theme(registry=_FakeThemeRegistry(value=1)) == "light"

    def test_returns_dark_for_dark_theme(self):
        assert get_system_theme(registry=_FakeThemeRegistry(value=0)) == "dark"

    def test_defaults_to_light_when_missing(self):
        assert get_system_theme(registry=_FakeThemeRegistry(value=None)) == "light"


class TestBuildPanelState:
    def test_maps_runtime_state_for_ui(self):
        providers = {
            "o200k_base": _Provider("GPT-4o (o200k_base)"),
            "cl100k_base": _Provider("GPT-4 (cl100k_base)"),
        }
        config = Config(
            tokenizer="cl100k_base",
            enabled=False,
            tooltip_display_s=3.5,
            blacklist=["Code.exe", "notepad.exe"],
        )

        state = build_panel_state(config, startup_enabled=True, providers=providers)

        assert isinstance(state, PanelState)
        assert state.enabled is False
        assert state.startup_enabled is True
        assert state.status_text == "Paused - monitoring disabled"
        assert state.tokenizer == "cl100k_base"
        assert state.tokenizer_options == [
            ("o200k_base", "GPT-4o (o200k_base)"),
            ("cl100k_base", "GPT-4 (cl100k_base)"),
        ]
        assert state.tooltip_display_s == 3.5
        assert state.blacklist_text == "Code.exe\nnotepad.exe"


class TestDisplayDurationHelpers:
    def test_maps_existing_duration_to_nearest_choice(self):
        assert duration_to_choice(1.0) == 1.0
        assert duration_to_choice(2.4) == 2.0
        assert duration_to_choice(3.5) == 3.0
        assert duration_to_choice(4.8) == 5.0

    def test_formats_duration_label(self):
        assert format_duration_label(1.0) == "1 Second"
        assert format_duration_label(2.0) == "2 Seconds"


class TestTokenizerDisplayHelpers:
    def test_builds_encoding_to_label_map(self):
        options = [
            ("o200k_base", "GPT-4o (o200k_base)"),
            ("cl100k_base", "GPT-4 (cl100k_base)"),
        ]

        assert build_tokenizer_display_map(options) == {
            "o200k_base": "GPT-4o (o200k_base)",
            "cl100k_base": "GPT-4 (cl100k_base)",
        }


class TestAdvancedStateHelper:
    def test_toggles_expanded_state(self):
        assert toggle_advanced(False) is True
        assert toggle_advanced(True) is False
