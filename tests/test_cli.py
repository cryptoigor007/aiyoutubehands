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


def test_auth_login_stub() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["auth", "login", "--stub"])
    assert r.exit_code == 0
    assert "STUB" in r.output or "stub" in r.output.lower() or "код" in r.output.lower()


def test_upload_prepare(tmp_path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"data")
    runner = CliRunner()
    r = runner.invoke(cli, ["upload", "prepare", str(f), "--title", "T"])
    assert r.exit_code == 0
    assert "dry-run" in r.output.lower() or "План" in r.output
