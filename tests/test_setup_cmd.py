"""Tests for setup guidance."""

from __future__ import annotations

from click.testing import CliRunner

from aiyoutubehands.main import cli


def test_setup_shows_current_youtube_guidance(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    runner = CliRunner()
    result = runner.invoke(cli, ["setup"])
    assert result.exit_code == 0, result.output
    assert "YouTube Data API v3" in result.output
    assert "Desktop app" in result.output
    assert "ayh connect" in result.output


def test_setup_json_contains_local_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    runner = CliRunner()
    result = runner.invoke(cli, ["setup", "--json"])
    assert result.exit_code == 0, result.output
    assert "oauth_vault_exists" in result.output
