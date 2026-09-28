"""Полное покрытие ``commands/tray_cmd.py`` без GUI и без настоящего ``rumps``.

Реальный ``rumps`` доступен только на macOS; здесь подменяется лёгкий двойник
(``FakeRumps``/``FakeAppBase``), а ``subprocess.Popen`` — шпионом. Ни один тест
не запускает меню-бар, ``osascript`` и не ходит в сеть.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from click.testing import CliRunner

from aiyoutubehands.commands import tray_cmd
from aiyoutubehands.main import cli

if TYPE_CHECKING:
    from collections.abc import Callable


# --------------------------------------------------------------------------
# Двойник rumps
# --------------------------------------------------------------------------


class FakeAppBase:
    """Минимальная замена ``rumps.App``."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name = name
        self.kwargs = kwargs
        self.menu: list[Any] = []
        self.ran = False

    def run(self) -> None:
        self.ran = True


class FakeMenuItem:
    """Минимальная замена ``rumps.MenuItem``."""

    def __init__(self, title: str, callback: Any = None) -> None:
        self.title = title
        self.callback = callback


class FakeRumps:
    """``SimpleNamespace``-совместимый двойник модуля ``rumps`` с захватом вызовов."""

    def __init__(self) -> None:
        self.App = FakeAppBase
        self.MenuItem = FakeMenuItem
        self.separator = object()
        self.notifications: list[tuple[Any, ...]] = []
        self.quit_called = False

    def notification(self, *args: Any) -> None:
        self.notifications.append(args)

    def quit_application(self) -> None:
        self.quit_called = True


# --------------------------------------------------------------------------
# Фикстуры
# --------------------------------------------------------------------------


@pytest.fixture
def fake_rumps() -> FakeRumps:
    return FakeRumps()


@pytest.fixture
def popen_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """Подменить ``subprocess.Popen`` и вернуть список вызовов."""
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class _Spy:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))

    monkeypatch.setattr(subprocess, "Popen", _Spy)
    return calls


@pytest.fixture
def no_ayh(monkeypatch: pytest.MonkeyPatch) -> None:
    """``shutil.which("ayh")`` ничего не находит → фолбэк на python -m."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)


def _cmd_of(call: tuple[tuple[Any, ...], dict[str, Any]]) -> list[str]:
    return list(call[0][0])


# --------------------------------------------------------------------------
# tray_cmd (CLI-обёртка)
# --------------------------------------------------------------------------


def test_tray_non_darwin_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray_cmd.sys, "platform", "linux")
    result = CliRunner().invoke(cli, ["tray"])
    assert result.exit_code == 2
    assert "рассчитан на macOS" in result.output


def test_tray_missing_rumps_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tray_cmd.sys, "platform", "darwin")
    # Значение None в sys.modules заставляет ``import rumps`` бросить ImportError.
    monkeypatch.setitem(sys.modules, "rumps", None)
    result = CliRunner().invoke(cli, ["tray"])
    assert result.exit_code == 2
    assert "pip install rumps" in result.output


def test_tray_command_builds_and_runs_app(
    monkeypatch: pytest.MonkeyPatch, fake_rumps: FakeRumps
) -> None:
    monkeypatch.setattr(tray_cmd.sys, "platform", "darwin")
    monkeypatch.setitem(sys.modules, "rumps", fake_rumps)

    built: dict[str, Any] = {}
    real_build = tray_cmd._build_app

    def _spy(rumps: object, root_path: str | None) -> object:
        app = real_build(rumps, root_path)
        built["app"] = app
        return app

    monkeypatch.setattr(tray_cmd, "_build_app", _spy)

    result = CliRunner().invoke(cli, ["tray", "--path", "/repo/ShortsMaker"])
    assert result.exit_code == 0
    assert built["app"].ran is True
    assert built["app"].name == "ayh"
    assert built["app"].root_path == "/repo/ShortsMaker"


# --------------------------------------------------------------------------
# _build_app: структура меню
# --------------------------------------------------------------------------


def test_build_app_menu_structure(fake_rumps: FakeRumps) -> None:
    app = tray_cmd._build_app(fake_rumps, "/repo")

    assert app.name == "ayh"
    assert app.kwargs == {"title": "ayh", "quit_button": None}
    assert app.root_path == "/repo"

    menu = app.menu
    assert len(menu) == 6
    assert menu[2] is fake_rumps.separator
    assert menu[4] is fake_rumps.separator

    items = [m for m in menu if isinstance(m, FakeMenuItem)]
    assert [m.title for m in items] == [
        "Process: analyze (dry-run)",
        "Doctor",
        "Открыть Terminal с ayh",
        "Quit ayh tray",
    ]
    for item in items:
        assert callable(item.callback)


def test_build_app_without_root_path(fake_rumps: FakeRumps) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    assert app.root_path is None


# --------------------------------------------------------------------------
# _run_ayh
# --------------------------------------------------------------------------


def test_run_ayh_falls_back_to_python_module(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
    no_ayh: None,
) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    app._run_ayh(["doctor"])

    args, kwargs = popen_calls[0]
    assert args[0] == [sys.executable, "-m", "aiyoutubehands.main", "doctor"]
    assert kwargs == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }
    assert fake_rumps.notifications[-1] == ("ayh", "Запущено", "doctor")


def test_run_ayh_prefers_installed_entrypoint(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/ayh")
    app = tray_cmd._build_app(fake_rumps, None)
    app._run_ayh(["process", "analyze"])

    assert _cmd_of(popen_calls[0]) == ["ayh", "process", "analyze"]
    assert fake_rumps.notifications[-1] == ("ayh", "Запущено", "process analyze")


def test_run_ayh_reports_oserror(
    fake_rumps: FakeRumps,
    monkeypatch: pytest.MonkeyPatch,
    no_ayh: None,
) -> None:
    def _boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("cannot spawn")

    monkeypatch.setattr(subprocess, "Popen", _boom)
    app = tray_cmd._build_app(fake_rumps, None)
    app._run_ayh(["doctor"])

    assert fake_rumps.notifications[-1] == ("ayh", "Ошибка запуска", "cannot spawn")


# --------------------------------------------------------------------------
# Колбэки меню
# --------------------------------------------------------------------------


def test_on_analyze_without_path_notifies(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    app.on_analyze(object())

    assert popen_calls == []
    assert fake_rumps.notifications[-1] == (
        "ayh",
        "Нужен --path",
        "Перезапустите: ayh tray --path /path/to/ShortsMaker",
    )


def test_on_analyze_with_path_runs_ayh(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
    no_ayh: None,
) -> None:
    app = tray_cmd._build_app(fake_rumps, "/repo")
    app.on_analyze(object())

    assert _cmd_of(popen_calls[0]) == [
        sys.executable,
        "-m",
        "aiyoutubehands.main",
        "process",
        "analyze",
        "--dry-run",
        "--path",
        "/repo",
    ]


def test_on_doctor_runs_doctor(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
    no_ayh: None,
) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    app.on_doctor(object())

    assert _cmd_of(popen_calls[0]) == [
        sys.executable,
        "-m",
        "aiyoutubehands.main",
        "doctor",
    ]


def test_on_terminal_opens_osascript(
    fake_rumps: FakeRumps,
    popen_calls: list[tuple[tuple[Any, ...], dict[str, Any]]],
) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    app.on_terminal(object())

    cmd = _cmd_of(popen_calls[0])
    assert cmd[0] == "osascript"
    assert cmd[1] == "-e"
    assert "Terminal" in cmd[2]


def test_on_quit_quits_app(fake_rumps: FakeRumps) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    app.on_quit(object())

    assert fake_rumps.quit_called is True


# Убедимся, что аннотированный callable действительно связывается с колбэком.
def test_menu_callbacks_are_bound_methods(fake_rumps: FakeRumps) -> None:
    app = tray_cmd._build_app(fake_rumps, None)
    by_title: dict[str, Callable[[object], None]] = {
        m.title: m.callback for m in app.menu if isinstance(m, FakeMenuItem)
    }
    assert by_title["Doctor"].__self__ is app
    assert by_title["Quit ayh tray"].__self__ is app
