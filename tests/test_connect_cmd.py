"""Tests for one-command secure connection."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from aiyoutubehands.commands.connect_cmd import _find_downloaded_oauth_file
from aiyoutubehands.main import cli


def test_connect_configures_and_removes_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    source = tmp_path / "client_secret.json"
    source.write_text(
        '{"installed": {"client_id": "client-id", "client_secret": "client-secret"}}',
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["connect", "--oauth-file", str(source), "--channel-id", "UC_channel", "--stub"],
        input="test-pass\ntest-pass\n",
    )
    assert result.exit_code == 0, result.output
    assert not source.exists()
    config_dir = tmp_path / "config" / "aiyoutubehands"
    assert (config_dir / "client_secrets.age").is_file()
    assert (config_dir / "token.age").is_file()


def test_find_downloaded_oauth_file_uses_newest_matching_json(tmp_path: Path) -> None:
    import os
    import time

    older = tmp_path / "client_secret_old.json"
    newer = tmp_path / "client_secret_new.json"
    older.write_text("{}", encoding="utf-8")
    # Ensure mtime ordering even on coarse FS timestamps
    os.utime(older, (time.time() - 10, time.time() - 10))
    newer.write_text("{}", encoding="utf-8")
    os.utime(newer, (time.time(), time.time()))
    assert _find_downloaded_oauth_file(tmp_path) == newer
