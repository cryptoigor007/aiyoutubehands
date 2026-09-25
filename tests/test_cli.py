"""CLI smoke tests."""

from __future__ import annotations

from click.testing import CliRunner

from aiyoutubehands.main import cli


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
    runner = CliRunner()
    r = runner.invoke(cli, ["version"])
    assert r.exit_code == 0
    assert "0.1.0" in r.output


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
        ["auth", "login", "--stub", "--passphrase", "test", "--yes"],
    )
    assert r.exit_code == 0, r.output
    assert "OK" in r.output or "сохранён" in r.output or "код" in r.output.lower()


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
