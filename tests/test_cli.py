"""CLI smoke tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from aiyoutubehands.main import cli

if TYPE_CHECKING:
    from pathlib import Path


def test_cli_help() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["--help"])
    assert r.exit_code == 0
    assert "AI YouTube Hands" in r.output or "ayh" in r.output.lower() or "YouTube" in r.output


def test_doctor() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["doctor"])
    assert r.exit_code == 0
    assert "версия" in r.output or "version" in r.output.lower() or "OK" in r.output


def test_doctor_json() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["doctor", "--json"])
    assert r.exit_code == 0
    assert "ok" in r.output


def test_version() -> None:
    from aiyoutubehands import __version__

    runner = CliRunner()
    r = runner.invoke(cli, ["version"])
    assert r.exit_code == 0
    # Сверяем с фактической версией, а не с зашитой строкой: иначе тест ломается
    # при каждом бампе версии и ничего не проверяет.
    assert __version__ in r.output


def test_calendar_list_empty(tmp_path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["calendar", "list", "--db", str(tmp_path / "c.db")])
    assert r.exit_code == 0


def test_quota_status(tmp_path) -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["quota", "status", "--db", str(tmp_path / "q.db")])
    assert r.exit_code == 0
    assert "Использовано" in r.output or "used" in r.output.lower()


def test_ai_title() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["ai", "title", "python"])
    assert r.exit_code == 0
    assert len(r.output.strip()) > 5


def test_auth_login_stub(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["auth", "login", "--stub", "--yes"],
        input="test\n",
    )
    assert r.exit_code == 0, r.output
    assert "OK" in r.output or "сохранён" in r.output or "код" in r.output.lower()


def test_passphrase_is_not_accepted_as_flag() -> None:
    """Мастер-ключ не должен передаваться аргументом.

    Аргументы видны в истории shell и в `ps auxww`, а этот CLI рассчитан в том
    числе на запуск агентом, который пойдёт по документированному флагу.
    Пароль читается только интерактивно.
    """
    import click

    def leaves(group, path):
        for name, cmd in group.commands.items():
            if isinstance(cmd, click.Group):
                yield from leaves(cmd, path + [name])
            else:
                yield path + [name]

    runner = CliRunner()
    offenders = []
    for path in leaves(cli, []):
        out = runner.invoke(cli, path + ["--help"]).output
        if "--passphrase" in out:
            offenders.append(" ".join(path))

    assert offenders == []


def test_upload_prepare(tmp_path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"data")
    runner = CliRunner()
    r = runner.invoke(cli, ["upload", "prepare", str(f), "--title", "T"])
    assert r.exit_code == 0
    assert "dry-run" in r.output.lower() or "План" in r.output


def test_main_ok() -> None:
    from aiyoutubehands.main import main

    assert main(["version"]) == 0


def test_main_unknown_command() -> None:
    from aiyoutubehands.main import main

    # click raises UsageError / SystemExit depending on path
    code = main(["no-such-command"])
    assert code != 0


def test_process_help() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["process", "--help"])
    assert r.exit_code == 0
    assert "analyze" in r.output
    assert "apply" in r.output
    assert "run" in r.output


def test_tray_help_or_platform() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["tray", "--help"])
    # help always works; actual tray needs macOS+rumps
    assert r.exit_code == 0
    assert "tray" in r.output.lower() or "menu" in r.output.lower() or "macOS" in r.output


def test_process_rules_command() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["process", "rules"])
    assert r.exit_code == 0, r.output
    assert "НЕ НАВРЕДИ" in r.output or "АБСОЛЮТНЫЕ ЗАПРЕТЫ" in r.output
    assert "подтверждаю план от" in r.output


def test_process_analyze_shows_banner(tmp_path: Path) -> None:
    # dry-run without auth may fail after banner; banner must appear
    runner = CliRunner()
    r = runner.invoke(cli, ["process", "analyze", "--path", str(tmp_path), "--dry-run"])
    assert "ПРАВИЛА БЕЗОПАСНОСТИ" in r.output or "AGENT_PROMPT" in r.output
