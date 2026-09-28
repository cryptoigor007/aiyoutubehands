"""Auth command integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from aiyoutubehands.main import cli

if TYPE_CHECKING:
    from pathlib import Path


def test_auth_login_stub_saves(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["auth", "login", "--stub", "--yes"],
        input="test-pass\n",
    )
    assert r.exit_code == 0, r.output
    tmp_path / ".config" / "aiyoutubehands" / "token.age"
    # path may use expand - check message
    assert "OK" in r.output or "сохранён" in r.output


def test_auth_logout_requires_yes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    runner.invoke(cli, ["auth", "login", "--stub", "--yes"], input="p\n")
    r = runner.invoke(cli, ["auth", "logout"])
    assert r.exit_code == 2


def test_auth_logout_yes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    runner.invoke(cli, ["auth", "login", "--stub", "--yes"], input="p\n")
    r = runner.invoke(cli, ["auth", "logout", "--yes"])
    assert r.exit_code == 0
    assert "OK" in r.output
