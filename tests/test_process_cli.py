"""CLI tests for ``ayh process`` (analyze / apply / run / rules).

Strategy
--------
* No real network: ``aiyoutubehands.service_factory.build_youtube_service`` is
  replaced via ``monkeypatch`` with a factory returning a fake ``(yt, client)``.
  ``process_cmd`` imports it *inside* the command, so patching the module
  attribute is enough.
* ``QuotaEngine`` always points at ``tmp_path``.
* Every local state dir (ledger, run log) is already redirected into a sandbox
  by ``tests/conftest.py``.

The fake ``yt`` only holds local data; none of its methods perform I/O.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest
from click.testing import CliRunner

from aiyoutubehands.commands.process_cmd import (
    _parse_confirm,
    _plan_to_dict,
    _require_fingerprint_match,
    _resolve_playlist,
)
from aiyoutubehands.main import cli
from aiyoutubehands.models.youtube import PlaylistResource, VideoResource
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.shorts_maker.folder_scanner import scan_root
from aiyoutubehands.shorts_maker.matcher import match_candidates
from aiyoutubehands.shorts_maker.plan import build_plan, plan_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

MSK = ZoneInfo("Europe/Moscow")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _today_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m.%Y")


def _make_folder(root: Path, name: str) -> Path:
    """Create a minimal Shorts Maker subfolder (mp4 only)."""
    d = root / name
    d.mkdir(parents=True)
    prefix = name.split()[0] if name else "clip"
    (d / f"{prefix}_clip.mp4").write_bytes(b"fake")
    return d


def _mk_video(vid: str, title: str) -> VideoResource:
    """A private, recent, zero-view video that is safe to match.

    ``publishedAt`` is set (recent), so ``never_published()`` is False and the
    proposed ``publish_at`` is ``None`` — this keeps the plan fingerprint stable
    between the plan computed by the test and the plan computed by the command.
    """
    return VideoResource.from_api(
        {
            "id": vid,
            "snippet": {
                "title": title,
                "description": "",
                "publishedAt": datetime.now(UTC).isoformat(),
                "channelId": "UC_test",
                "tags": [],
                "thumbnails": {},
            },
            "status": {"privacyStatus": "private"},
            "contentDetails": {"duration": "PT40S"},
            "processingDetails": {"processingStatus": "succeeded"},
            "statistics": {"viewCount": "0"},
        }
    )


class FakeYT:
    """Offline stand-in for ``YoutubeService`` used by process commands."""

    def __init__(
        self,
        *,
        videos: list[VideoResource] | None = None,
        pl_ids: set[str] | None = None,
        quota: QuotaEngine,
        membership_error: Exception | None = None,
        membership_raw: object | None = None,
    ) -> None:
        self.quota = quota
        self._videos = list(videos or [])
        self._pl_ids = set(pl_ids or set())
        self._membership_error = membership_error
        self._membership_raw = membership_raw
        self.calls: list[tuple[str, str]] = []

    def list_channel_videos(
        self, *, max_age_days: int = 14, dry_run: bool = False
    ) -> list[VideoResource]:
        return list(self._videos)

    def list_video_ids_in_playlists(self, *, dry_run: bool = False) -> Any:
        if self._membership_error is not None:
            raise self._membership_error
        if self._membership_raw is not None:
            return self._membership_raw
        return set(self._pl_ids)

    def list_playlists(self, *, dry_run: bool = False) -> list[PlaylistResource]:
        return []

    def update_video(
        self,
        vid: str,
        *,
        snippet: object = None,
        status: object = None,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        self.calls.append(("update_video", vid))

    def set_thumbnail(
        self,
        vid: str,
        path: object,
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        self.calls.append(("set_thumbnail", vid))

    def add_to_playlist(
        self, playlist_id: str, vid: str, *, dry_run: bool = False, yes: bool = False
    ) -> None:
        self.calls.append(("add_to_playlist", vid))


class FakeClient:
    def __init__(self) -> None:
        self.access_token = "fake-access-token"
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _install_fake(monkeypatch: pytest.MonkeyPatch, yt: FakeYT, client: FakeClient) -> None:
    """Patch the local import target of the process commands."""

    def _build(*, passphrase: str, force_quota: bool = False) -> tuple[FakeYT, FakeClient]:
        return yt, client

    monkeypatch.setattr(
        "aiyoutubehands.service_factory.build_youtube_service",
        _build,
    )


def _expected_plan(root: Path, tmp_path: Path, videos: list[VideoResource]) -> Any:
    matches = match_candidates(scan_root(root), videos)
    return build_plan(
        matches,
        root_path=root,
        quota=QuotaEngine(db_path=tmp_path / "expected_quota.db"),
    )


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #


def test_parse_confirm_requires_hash() -> None:
    import click

    with pytest.raises(click.ClickException):
        _parse_confirm("подтверждаю план от 01.01.2026")


def test_parse_confirm_returns_date_and_hash() -> None:
    date, fp = _parse_confirm("подтверждаю план от 01.01.2026 #abc123abc123")
    assert date == "01.01.2026"
    assert fp == "abc123abc123"


def test_require_fingerprint_match_rejects_non_plan() -> None:
    with pytest.raises(TypeError):
        _require_fingerprint_match(object(), "abc123abc123")


def test_plan_to_dict_rejects_non_plan() -> None:
    with pytest.raises(TypeError):
        _plan_to_dict(object())


def test_resolve_playlist_variants(tmp_path: Path) -> None:
    assert _resolve_playlist(None) is None
    assert _resolve_playlist("нет") is None
    assert _resolve_playlist("  ") is None
    assert _resolve_playlist("PL0123456789") == "PL0123456789"
    assert _resolve_playlist("just-name", yt=None) == "just-name"
    # Any non-YoutubeService object can't resolve titles → warn, return None.
    assert _resolve_playlist("just-name", yt=object()) is None

    from aiyoutubehands.client import HttpClient
    from aiyoutubehands.youtube import YoutubeService

    yt = YoutubeService(
        HttpClient(access_token="fake"),
        QuotaEngine(db_path=tmp_path / "pq.db"),
        "UC_p",
    )
    pl = PlaylistResource.from_api({"id": "PLabcdefghij", "snippet": {"title": "My Shorts"}})
    yt.list_playlists = lambda dry_run=False: [pl]  # type: ignore[method-assign]

    assert _resolve_playlist("my shorts", yt=yt) == "PLabcdefghij"
    assert _resolve_playlist("short", yt=yt) == "PLabcdefghij"
    assert _resolve_playlist("absent", yt=yt) is None

    # Non-list playlists response → keep the raw value as an id.
    yt.list_playlists = lambda dry_run=False: "not-a-list"  # type: ignore[method-assign]
    assert _resolve_playlist("raw-name", yt=yt) == "raw-name"


# --------------------------------------------------------------------------- #
# process rules
# --------------------------------------------------------------------------- #


def test_process_group_without_subcommand_prints_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["process"])
    # Click groups require an explicit subcommand → help + usage error (2).
    assert result.exit_code == 2, result.output
    assert "Commands:" in result.output
    assert "analyze" in result.output
    assert "apply" in result.output


def test_rules_prints_banner_and_full_text() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["process", "rules"])
    assert result.exit_code == 0, result.output
    assert "ПРАВИЛА БЕЗОПАСНОСТИ" in result.output
    assert "подтверждаю план от" in result.output


def test_rules_missing_file_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    import aiyoutubehands.agent_rules as agent_rules

    monkeypatch.setattr(agent_rules, "rules_file_path", lambda: None)
    monkeypatch.setattr(agent_rules, "load_rules_text", lambda: None)

    runner = CliRunner()
    result = runner.invoke(cli, ["process", "rules"])
    assert result.exit_code != 0
    assert "не найден" in result.output


# --------------------------------------------------------------------------- #
# analyze
# --------------------------------------------------------------------------- #


def test_analyze_dry_run_shows_banner_and_empty_matching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--path", str(root), "--dry-run"],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "ПРАВИЛА БЕЗОПАСНОСТИ" in result.output
    assert "сопоставление будет пустым" in result.output
    assert "Найдено подпапок: 1" in result.output
    assert client.closed is True


def test_analyze_save_plan_writes_fingerprint_and_phrase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("analyzeplan1", "Alpha")

    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    plan_path = tmp_path / "plan.json"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--path", str(root), "--save-plan", str(plan_path)],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert plan_path.is_file()
    assert "План сохранён" in result.output

    saved = json.loads(plan_path.read_text(encoding="utf-8"))
    assert len(saved["fingerprint"]) == 12
    assert saved["confirm_phrase"].endswith(f"#{saved['fingerprint']}")
    assert saved["items"], "план должен содержать хотя бы один элемент"
    assert saved["items"][0]["video_id"] == "analyzeplan1"


def test_analyze_json_output_contains_plan_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("analyzejson1", "Alpha")

    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--path", str(root), "--json"],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert '"fingerprint"' in result.output
    assert '"confirm_phrase"' in result.output
    assert '"items"' in result.output


def test_analyze_prompts_for_path_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--dry-run"],
        input=f"{root}\nsecret\n",
    )
    assert result.exit_code == 0, result.output
    assert "Найдено подпапок: 1" in result.output


def test_analyze_prompted_missing_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--dry-run"],
        input=f"{tmp_path / 'does-not-exist'}\n",
    )
    assert result.exit_code != 0
    assert "Папка не найдена" in result.output


def test_analyze_membership_error_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("analyzemen1", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_error=RuntimeError("boom"),
    )
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "analyze", "--path", str(root)],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "Не удалось загрузить membership плейлистов: boom" in result.output


def test_analyze_with_playlist_id_and_non_set_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("analyzepl001", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_raw=["not", "a", "set"],
    )
    _install_fake(monkeypatch, yt, FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "analyze",
            "--path",
            str(root),
            "--playlist",
            "PL0123456789",
        ],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    # A playlist was supplied, so the "not set" note must not be printed.
    assert "Плейлист: не задан" not in result.output


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #


def test_apply_confirm_without_hash_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            "подтверждаю план от 01.01.2026",
            "--no-dry-run",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "Фраза должна быть" in result.output


def test_apply_confirm_wrong_date_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            "подтверждаю план от 01.01.2020 #abc123abc123",
            "--no-dry-run",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "не сегодняшняя" in result.output


def test_apply_wrong_fingerprint_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    wrong = "deadbeef0000"
    assert wrong != plan_fingerprint([])
    phrase = f"подтверждаю план от {_today_msk()} #{wrong}"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "apply", "--path", str(root), "--confirm", phrase, "--no-dry-run", "--yes"],
        input="secret\n",
    )
    assert result.exit_code != 0
    assert "хэш не совпал" in result.output


def test_apply_no_dry_run_without_yes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    phrase = f"подтверждаю план от {_today_msk()} #abc123abc123"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "apply", "--path", str(root), "--confirm", phrase, "--no-dry-run"],
    )
    assert result.exit_code != 0
    assert "Нужен --yes" in result.output


def test_apply_dry_run_does_not_apply_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    # apply --dry-run не читает канал, поэтому вместо плана объясняет, как его
    # посмотреть. Главное — ничего не применяет и не требует фразы.
    runner = CliRunner()
    result = runner.invoke(cli, ["process", "apply", "--path", str(root)])

    assert result.exit_code != 0
    assert "analyze" in result.output
    assert not yt.calls, "dry-run не должен ничего применять"


def test_apply_plan_file_mismatch_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    plan_file = tmp_path / "foreign-plan.json"
    plan_file.write_text(json.dumps({"fingerprint": "deadbeef0000"}), encoding="utf-8")

    phrase = f"подтверждаю план от {_today_msk()} #{plan_fingerprint([])}"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            phrase,
            "--plan",
            str(plan_file),
            "--no-dry-run",
            "--yes",
        ],
        input="secret\n",
    )
    assert result.exit_code != 0
    assert "не совпадает с текущим" in result.output


def test_apply_plan_file_matching_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    _install_fake(monkeypatch, yt, FakeClient())

    fp = plan_fingerprint([])
    plan_file = tmp_path / "matching-plan.json"
    plan_file.write_text(json.dumps({"fingerprint": fp}), encoding="utf-8")

    phrase = f"подтверждаю план от {_today_msk()} #{fp}"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            phrase,
            "--plan",
            str(plan_file),
            "--no-dry-run",
            "--yes",
        ],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "Нет видео для обработки." in result.output


def test_apply_no_dry_run_prints_plan_and_hash_and_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("applynodry1", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_raw=["not", "a", "set"],
    )
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    expected = _expected_plan(root, tmp_path, [video])
    assert expected.actionable_items(), "нужен actionable-элемент для применения"
    phrase = f"подтверждаю план от {_today_msk()} #{expected.fingerprint}"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            phrase,
            "--no-dry-run",
            "--yes",
        ],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "Новый title" in result.output
    assert f"Хэш плана: {expected.fingerprint}" in result.output
    assert "Успешно: 1" in result.output
    assert ("update_video", "applynodry1") in yt.calls
    assert client.closed is True


def test_apply_quota_would_exceed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("applyquota1", "Alpha")

    # A zero daily limit makes the projection report would_exceed immediately.
    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q0.db", daily_limit=0))
    _install_fake(monkeypatch, yt, FakeClient())

    phrase = f"подтверждаю план от {_today_msk()} #abc123abc123"
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            phrase,
            "--no-dry-run",
            "--yes",
        ],
        input="secret\n",
    )
    assert result.exit_code != 0
    assert "Квота будет превышена" in result.output
    assert not yt.calls, "при превышении квоты ничего не применяется"


def test_apply_membership_error_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("applymen001", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_error=RuntimeError("boom"),
    )
    _install_fake(monkeypatch, yt, FakeClient())

    expected = _expected_plan(root, tmp_path, [video])
    phrase = f"подтверждаю план от {_today_msk()} #{expected.fingerprint}"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "process",
            "apply",
            "--path",
            str(root),
            "--confirm",
            phrase,
            "--no-dry-run",
            "--yes",
        ],
        input="secret\n",
    )
    assert result.exit_code == 0, result.output
    assert "membership плейлистов пропущен: boom" in result.output


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


def test_run_dry_run_says_nothing_to_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")

    yt = FakeYT(quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--path", str(root)],
        input="нет\nsecret\n",
    )
    assert result.exit_code == 0, result.output
    assert "Нечего применять." in result.output
    assert not yt.calls


def test_run_without_correct_phrase_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("runwrong001", "Alpha")

    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--path", str(root), "--no-dry-run"],
        input="нет\nsecret\nне та фраза\n",
    )
    assert result.exit_code != 0
    assert "не совпала" in result.output
    assert not yt.calls, "без верной фразы применять нельзя"
    assert client.closed is True


def test_run_with_correct_phrase_applies(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("runapply001", "Alpha")

    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    expected = _expected_plan(root, tmp_path, [video])
    assert expected.actionable_items()
    phrase = expected.confirm_phrase

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--path", str(root), "--no-dry-run", "--yes"],
        input=f"нет\nsecret\n{phrase}\n",
    )
    assert result.exit_code == 0, result.output
    assert "Успешно: 1" in result.output
    assert ("update_video", "runapply001") in yt.calls
    assert client.closed is True


def test_run_path_prompt_reports_membership_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("runpatherr1", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_error=RuntimeError("boom"),
    )
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--no-dry-run"],
        input=f"{root}\nнет\nsecret\nне та фраза\n",
    )
    assert result.exit_code != 0
    assert "membership плейлистов пропущен: boom" in result.output
    assert not yt.calls


def test_run_confirmation_declined_does_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("runconfirm1", "Alpha")

    yt = FakeYT(videos=[video], quota=QuotaEngine(db_path=tmp_path / "q.db"))
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    expected = _expected_plan(root, tmp_path, [video])
    phrase = expected.confirm_phrase

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--path", str(root), "--no-dry-run"],
        input=f"нет\nsecret\n{phrase}\nn\n",
    )
    assert result.exit_code == 0, result.output
    assert "Отмена." in result.output
    assert not yt.calls
    assert client.closed is True


def test_run_prompted_missing_path_is_refused(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run"],
        input=f"{tmp_path / 'does-not-exist'}\n",
    )
    assert result.exit_code != 0
    assert "Папка не найдена" in result.output


def test_run_non_set_membership_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Alpha")
    video = _mk_video("runrawmem01", "Alpha")

    yt = FakeYT(
        videos=[video],
        quota=QuotaEngine(db_path=tmp_path / "q.db"),
        membership_raw=["not", "a", "set"],
    )
    client = FakeClient()
    _install_fake(monkeypatch, yt, client)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["process", "run", "--path", str(root), "--no-dry-run"],
        input="нет\nsecret\nне та фраза\n",
    )
    assert result.exit_code != 0
    assert "membership плейлистов пропущен" not in result.output
    assert not yt.calls
