"""CLI tests for ayh post create (dry-run + confirmation rules; no Safari)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from click.testing import CliRunner

from aiyoutubehands.main import cli
from aiyoutubehands.posts.models import PostPayload

if TYPE_CHECKING:
    from pathlib import Path


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


# ---------------------------------------------------------------------------
# Confirmation phrase rules (repo standard: «подтверждаю план от ДД.ММ.ГГГГ #hash»)
# ---------------------------------------------------------------------------


def _fake_plan(payload: PostPayload, *, via: str = "api") -> dict:
    return {
        "dry_run": True,
        "via": via,
        "url": "https://example.invalid/posts",
        "text_preview": payload.text[:50],
        "text_len": len(payload.text),
        "image": None,
        "image_size": None,
        "crop": payload.crop,
        "preview_coordinates": None,
        "platform": "Darwin",
        "safari_available": True,
        "steps": [],
        "image_requirements": None,
    }


def _config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = tmp_path / ".config" / "aiyoutubehands"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "channel:\n  expected_channel_id: UCtestdryrun123\n",
        encoding="utf-8",
    )


def _invoke_with_mocks(monkeypatch, args):
    import aiyoutubehands.commands.post_cmd as pc

    calls: list[str] = []
    monkeypatch.setattr(pc, "dry_run_plan", _fake_plan)
    monkeypatch.setattr(
        pc,
        "publish_post",
        lambda payload, via="api", progress=None: (
            calls.append(via) or {"ok": True, "via": via, "verified": True}
        ),
    )
    runner = CliRunner()
    return runner.invoke(cli, args), calls


def test_publish_requires_confirm_phrase(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch)
    r, calls = _invoke_with_mocks(
        monkeypatch,
        ["post", "create", "--text-file", str(text_file), "--no-dry-run", "--yes"],
    )
    assert r.exit_code != 0
    assert not calls


def test_publish_rejects_wrong_date(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch)
    r, calls = _invoke_with_mocks(
        monkeypatch,
        [
            "post", "create", "--text-file", str(text_file),
            "--no-dry-run", "--yes",
            "--confirm", "подтверждаю план от 01.01.2020 #deadbeefdead",
        ],
    )
    assert r.exit_code != 0
    assert not calls


def test_publish_rejects_wrong_hash(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch)
    today = date.today().strftime("%d.%m.%Y")
    r, calls = _invoke_with_mocks(
        monkeypatch,
        [
            "post", "create", "--text-file", str(text_file),
            "--no-dry-run", "--yes",
            "--confirm", f"подтверждаю план от {today} #000000000000",
        ],
    )
    assert r.exit_code != 0
    assert not calls


def test_publish_with_correct_phrase(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch)
    import aiyoutubehands.commands.post_cmd as pc

    payload = PostPayload.from_files(text_file, None, channel_id="UCtestdryrun123")
    h = pc._plan_hash(payload, via="api")
    today = date.today().strftime("%d.%m.%Y")
    r, calls = _invoke_with_mocks(
        monkeypatch,
        [
            "post", "create", "--text-file", str(text_file),
            "--no-dry-run", "--yes",
            "--confirm", f"подтверждаю план от {today} #{h}",
        ],
    )
    assert r.exit_code == 0, r.output
    assert calls == ["api"]


def test_dry_run_shows_api_steps_and_phrase(text_file: Path, tmp_path: Path, monkeypatch) -> None:
    _config(tmp_path, monkeypatch)
    runner = CliRunner()
    r = runner.invoke(cli, ["post", "create", "--text-file", str(text_file), "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "create_post" in r.output
    assert "подтверждаю план от" in r.output
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
