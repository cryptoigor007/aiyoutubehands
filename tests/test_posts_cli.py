"""CLI tests for ayh post create (dry-run only, no Safari)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from aiyoutubehands.main import cli


@pytest.fixture
def text_file(tmp_path: Path) -> Path:
    f = tmp_path / "post.txt"
    f.write_text("Тестовая запись для dry-run", encoding="utf-8")
    return f


def test_post_create_help() -> None:
    runner = CliRunner()
    r = runner.invoke(cli, ["post", "create", "--help"])
    assert r.exit_code == 0
    assert "text-file" in r.output
    assert "dry-run" in r.output


def test_post_create_dry_run_no_config(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    """Without config the command should fail with a clear message."""
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(cli, ["post", "create", "--text-file", str(text_file)])
    # load_config raises when channel_id missing
    assert r.exit_code != 0
    out = (r.output or str(r.exception) or "").lower()
    assert (
        "channel" in out
        or "expected_channel" in out
        or "конфиг" in out
        or "config" in out
    ), f"unexpected output: {r.output!r} exc={r.exception!r}"


def test_post_create_dry_run_with_config(
    text_file: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "channel:\n  expected_channel_id: UCtestdryrun123\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["post", "create", "--text-file", str(text_file), "--dry-run"],
    )
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output or "dry_run" in r.output
    assert "UCtestdryrun123" in r.output
    assert "Тестовая" in r.output or "text" in r.output.lower()
    assert "подтверждаю план" in r.output


def test_post_create_dry_run_json(
    text_file: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text(
        "channel:\n  expected_channel_id: UCjson123\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["post", "create", "--text-file", str(text_file), "--json"],
    )
    assert r.exit_code == 0, r.output
    assert '"dry_run": true' in r.output or '"dry_run":true' in r.output
    assert "plan_hash" in r.output
    assert "confirm_phrase" in r.output


def test_post_create_missing_text_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    r = runner.invoke(
        cli,
        ["post", "create", "--text-file", str(tmp_path / "missing.txt")],
    )
    assert r.exit_code != 0
