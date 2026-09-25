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
