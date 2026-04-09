"""Tests for Windows startup registration."""

from __future__ import annotations

from unittest import mock

from tokencounter.constants import APP_NAME
from tokencounter.startup import RUN_KEY_PATH, StartupManager, build_startup_command


class _FakeKey:
    def __init__(self, registry: "_FakeRegistry", path: str) -> None:
        self._registry = registry
        self.path = path

    def __enter__(self) -> "_FakeKey":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeRegistry:
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}

    def OpenKey(self, root, path: str, reserved: int = 0, access: int = 0) -> _FakeKey:
        if path not in self.values:
            raise FileNotFoundError(path)
        return _FakeKey(self, path)

    def CreateKey(self, root, path: str) -> _FakeKey:
        self.values.setdefault(path, {})
        return _FakeKey(self, path)

    def QueryValueEx(self, key: _FakeKey, value_name: str) -> tuple[str, int]:
        try:
            value = self.values[key.path][value_name]
        except KeyError as exc:
            raise FileNotFoundError(value_name) from exc
        return value, self.REG_SZ

    def SetValueEx(self, key: _FakeKey, value_name: str, reserved: int, reg_type: int, value: str) -> None:
        self.values.setdefault(key.path, {})[value_name] = value

    def DeleteValue(self, key: _FakeKey, value_name: str) -> None:
        try:
            del self.values[key.path][value_name]
        except KeyError as exc:
            raise FileNotFoundError(value_name) from exc


class TestBuildStartupCommand:
    def test_prefers_pythonw_for_module_launch(self):
        with mock.patch("tokencounter.startup.os.path.isfile", side_effect=lambda path: path.endswith("pythonw.exe")):
            command = build_startup_command(
                executable=r"C:\Python313\python.exe",
                argv0="tokencounter",
                is_frozen=False,
            )

        assert command == 'C:\\Python313\\pythonw.exe -m tokencounter'

    def test_uses_existing_executable_wrapper(self):
        command = build_startup_command(
            executable=r"C:\Python313\python.exe",
            argv0=r"C:\Python313\Scripts\tokencounter.exe",
            is_frozen=False,
        )

        assert command == 'C:\\Python313\\Scripts\\tokencounter.exe'

    def test_uses_frozen_executable(self):
        command = build_startup_command(
            executable=r"C:\Apps\TokenCounter.exe",
            argv0=r"C:\Apps\TokenCounter.exe",
            is_frozen=True,
        )

        assert command == 'C:\\Apps\\TokenCounter.exe'


class TestStartupManager:
    def test_is_disabled_when_value_missing(self):
        registry = _FakeRegistry()
        mgr = StartupManager(registry=registry)

        assert mgr.is_enabled() is False

    def test_enable_writes_run_value(self):
        registry = _FakeRegistry()
        mgr = StartupManager(registry=registry)

        with mock.patch("tokencounter.startup.build_startup_command", return_value='"C:\\Apps\\TokenCounter.exe"'):
            mgr.set_enabled(True)

        assert registry.values[RUN_KEY_PATH][APP_NAME] == '"C:\\Apps\\TokenCounter.exe"'
        assert mgr.is_enabled() is True

    def test_disable_removes_run_value(self):
        registry = _FakeRegistry()
        registry.values[RUN_KEY_PATH] = {APP_NAME: '"C:\\Apps\\TokenCounter.exe"'}
        mgr = StartupManager(registry=registry)

        mgr.set_enabled(False)

        assert mgr.is_enabled() is False
