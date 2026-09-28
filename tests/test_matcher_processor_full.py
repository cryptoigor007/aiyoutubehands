"""Целевые тесты, закрывающие оставшиеся ветки matcher/processor/folder_scanner.

Дополняют ``tests/test_shorts_maker.py`` и ``tests/test_shorts_maker_extra.py``,
не дублируя уже покрытое. Сеть не используется; ``conftest.py`` изолирует HOME,
поэтому лог процессора и default-ledger пишутся в песочницу.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

import aiyoutubehands.shorts_maker.media as media_mod
import aiyoutubehands.shorts_maker.processor as processor_mod
from aiyoutubehands.client import ClientError
from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.shorts_maker.folder_scanner import (
    FolderCandidate,
    scan_folder,
    scan_root,
)
from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
from aiyoutubehands.shorts_maker.matcher import (
    find_folder_duplicate_groups,
    is_safe_new_upload,
    match_candidates,
)
from aiyoutubehands.shorts_maker.plan import PlanItem, ProcessPlan
from aiyoutubehands.shorts_maker.processor import ProcessReport, apply_plan

if TYPE_CHECKING:
    from pathlib import Path

MSK = ZoneInfo("Europe/Moscow")


# --------------------------------------------------------------------------- #
# Помощники
# --------------------------------------------------------------------------- #


def _video(
    vid: str,
    title: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    published_at: str = "",
    duration: str = "PT40S",
    processing: str = "succeeded",
    statistics: dict[str, str] | None = None,
    channel_id: str = "UC_test",
) -> VideoResource:
    return VideoResource.from_api(
        {
            "id": vid,
            "snippet": {
                "title": title,
                "description": description,
                "publishedAt": published_at,
                "channelId": channel_id,
                "tags": tags or [],
                "thumbnails": {},
            },
            "status": {"privacyStatus": privacy},
            "contentDetails": {"duration": duration},
            "processingDetails": {"processingStatus": processing},
            "statistics": statistics or {"viewCount": "0"},
        }
    )


def _cand(tmp_path: Path, clean_title: str, name: str = "ш1 Folder") -> FolderCandidate:
    return FolderCandidate(path=tmp_path / "folder", folder_name=name, clean_title=clean_title)


def _item(
    tmp_path: Path,
    video: VideoResource | None,
    *,
    new_title: str = "Новый заголовок",
    new_description: str = "Описание",
    new_tags: list[str] | None = None,
    thumbnail_path: Path | None = None,
    publish_at: str | None = None,
    playlist_id: str | None = None,
    estimated_quota: int = 50,
) -> PlanItem:
    return PlanItem(
        index=1,
        folder=_cand(tmp_path, "Folder"),
        video=video,
        match_method="title",
        new_title=new_title,
        new_description=new_description,
        new_tags=new_tags or ["a"],
        thumbnail_path=thumbnail_path,
        publish_at=publish_at,
        status="к обработке",
        estimated_quota=estimated_quota,
        playlist_id=playlist_id,
    )


def _plan(tmp_path: Path, items: list[PlanItem]) -> ProcessPlan:
    return ProcessPlan(
        created_at=datetime.now(MSK),
        root_path=tmp_path,
        items=items,
        quota_projection={},
        confirm_phrase="подтверждаю план от 01.01.2026",
    )


class _FakeYT:
    """Минимальный дублёр YoutubeService — только нужные методы, без сети."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        fail_update: BaseException | None = None,
        fail_thumb: BaseException | None = None,
        publish_at_reject: bool = False,
    ) -> None:
        self.quota = QuotaEngine(db_path=tmp_path / "q.db")
        self.fail_update = fail_update
        self.fail_thumb = fail_thumb
        self.publish_at_reject = publish_at_reject
        self.thumb_calls: list[str] = []
        self.playlist_calls: list[tuple[str, str]] = []

    def update_video(
        self,
        video_id: str,
        snippet: object = None,
        status: object = None,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        pub = getattr(status, "publish_at", None)
        if self.publish_at_reject and status is not None and pub:
            raise ClientError("invalidPublishAt", code="BAD_REQUEST")
        if self.fail_update is not None:
            raise self.fail_update
        return None

    def set_thumbnail(
        self,
        video_id: str,
        image_path: object,
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        if self.fail_thumb is not None:
            raise self.fail_thumb
        self.thumb_calls.append(video_id)
        return None

    def add_to_playlist(
        self,
        playlist_id: str,
        video_id: str,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        self.playlist_calls.append((playlist_id, video_id))
        return None


# --------------------------------------------------------------------------- #
# matcher: _view_count / is_safe_new_upload / _is_recent
# --------------------------------------------------------------------------- #


def test_view_count_non_numeric_is_treated_as_zero() -> None:
    v = _video("v1", "Заголовок", statistics={"viewCount": "abc"})
    ok, why = is_safe_new_upload(v)
    assert ok is True
    assert why == "ok"


def test_is_safe_new_upload_unknown_privacy() -> None:
    v = _video("v2", "Заголовок", privacy="weird")
    ok, why = is_safe_new_upload(v)
    assert ok is False
    assert why == "privacy=weird"


def test_is_safe_new_upload_private_with_views() -> None:
    v = _video("v3", "Заголовок", statistics={"viewCount": "5"})
    ok, why = is_safe_new_upload(v)
    assert ok is False
    assert "просмотры" in why


def test_is_safe_new_upload_private_too_old() -> None:
    v = _video("v4", "Заголовок", published_at="2020-01-01T00:00:00Z")
    ok, why = is_safe_new_upload(v)
    assert ok is False
    assert "старше" in why


def test_is_safe_new_upload_invalid_date_is_old() -> None:
    v = _video("v5", "Заголовок", published_at="not-a-date")
    ok, why = is_safe_new_upload(v)
    assert ok is False
    assert "старше" in why


# --------------------------------------------------------------------------- #
# matcher: find_folder_duplicate_groups
# --------------------------------------------------------------------------- #


def test_duplicate_groups_ignores_empty_key(tmp_path: Path) -> None:
    c = FolderCandidate(path=tmp_path / "empty", folder_name="", clean_title="")
    assert find_folder_duplicate_groups([c]) == {}


def test_duplicate_groups_groups_real_duplicates(tmp_path: Path) -> None:
    a = FolderCandidate(path=tmp_path / "a", folder_name="ш1 One", clean_title="One Title")
    b = FolderCandidate(path=tmp_path / "b", folder_name="ш2 One", clean_title="One   Title")
    groups = find_folder_duplicate_groups([a, b])
    assert list(groups.values()) == [[a, b]]


# --------------------------------------------------------------------------- #
# matcher: match_candidates дополнительные ветки
# --------------------------------------------------------------------------- #


def test_match_skips_video_without_title_in_index(tmp_path: Path) -> None:
    """Видео с пустым title не попадает в by_title (ветка `if key`)."""
    cand = _cand(tmp_path, "Нечто")
    empty = _video("empty", "")
    results = match_candidates([cand], [empty])
    assert results[0].video is None
    assert results[0].reason == "не сопоставлено"


def test_match_title_all_used_falls_through(tmp_path: Path) -> None:
    """Title совпал, но все такие видео уже заняты → ветка len(free)==0."""
    first = FolderCandidate(
        path=tmp_path / "a", folder_name="ш1 Alpha", clean_title="Alpha", video_id_hint="vid1"
    )
    second = _cand(tmp_path, "Shared Title", name="ш2 Beta")
    video = _video("vid1", "Shared Title")
    results = match_candidates([first, second], [video])
    assert results[0].reason == "ok"
    assert results[1].video is None
    assert results[1].reason == "не сопоставлено"


def test_match_video_id_already_taken(tmp_path: Path) -> None:
    first = _cand(tmp_path, "Alpha", name="ш1 Alpha")
    second = FolderCandidate(
        path=tmp_path / "b", folder_name="ш2 Beta", clean_title="Beta", video_id_hint="vid1"
    )
    video = _video("vid1", "Alpha")
    results = match_candidates([first, second], [video])
    assert results[0].video is not None
    assert results[1].reason == "video_id уже сопоставлен другой папке"
    assert results[1].related_video_ids == ["vid1"]


def test_match_video_id_hint_not_found_falls_through(tmp_path: Path) -> None:
    cand = FolderCandidate(
        path=tmp_path / "a", folder_name="ш1 Alpha", clean_title="Alpha", video_id_hint="missing_id"
    )
    video = _video("vid1", "Совсем другой заголовок")
    results = match_candidates([cand], [video])
    assert results[0].video is None
    assert results[0].reason == "не сопоставлено"


def test_match_duration_without_any_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "ш8 Clip"
    d.mkdir()
    (d / "ш8_clip.mp4").write_bytes(b"fake")
    cand = scan_folder(d)
    videos = [_video("va", "raw_a", duration="PT10S"), _video("vb", "raw_b", duration="PT20S")]
    monkeypatch.setattr(media_mod, "probe_duration_seconds", lambda _p: 45)
    results = match_candidates([cand], videos)
    assert results[0].video is None
    assert results[0].reason == "не сопоставлено"


def test_match_ambiguous_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = tmp_path / "ш7 Clip"
    d.mkdir()
    (d / "ш7_clip.mp4").write_bytes(b"fake")
    cand = scan_folder(d)
    videos = [_video("va", "raw_a", duration="PT45S"), _video("vb", "raw_b", duration="PT44S")]
    monkeypatch.setattr(media_mod, "probe_duration_seconds", lambda _p: 45)
    results = match_candidates([cand], videos)
    assert results[0].video is None
    assert "неоднозначная duration" in results[0].reason
    assert set(results[0].related_video_ids) == {"va", "vb"}


def test_match_processing_status_not_succeeded(tmp_path: Path) -> None:
    cand = _cand(tmp_path, "Beta")
    video = _video("vid1", "Beta", processing="processing")
    results = match_candidates([cand], [video])
    assert results[0].reason == "processingStatus=processing"


def test_match_already_styled(tmp_path: Path) -> None:
    big_title = "Очень длинный заголовок для оформленного видео"
    cand = _cand(tmp_path, big_title)
    video = _video(
        "vid1",
        big_title,
        description="о" * 60,
        tags=["a", "b", "c"],
    )
    results = match_candidates([cand], [video])
    assert results[0].reason == "уже оформлено"


def test_match_only_new_private_disabled_allows_public(tmp_path: Path) -> None:
    cand = _cand(tmp_path, "Beta")
    video = _video("pub1", "Beta", privacy="public", statistics={"viewCount": "9"})
    results = match_candidates([cand], [video], only_new_private=False)
    assert results[0].video is not None
    assert results[0].reason == "ok"


# --------------------------------------------------------------------------- #
# processor: ProcessReport.summary
# --------------------------------------------------------------------------- #


def test_process_report_summary_without_log_and_with_failures() -> None:
    r = ProcessReport()
    assert "Лог:" not in r.summary()
    r.failed.append(("v1", "boom"))
    r.notes.append(("v1", "внимание"))
    s = r.summary()
    assert "FAIL v1: boom" in s
    assert "ВНИМАНИЕ v1: внимание" in s


# --------------------------------------------------------------------------- #
# processor: apply_plan / _apply_one
# --------------------------------------------------------------------------- #


def test_apply_plan_creates_default_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(processor_mod, "_run_log_path", lambda: tmp_path / "run.log")
    report = apply_plan(
        _plan(tmp_path, []),
        _FakeYT(tmp_path),
        access_token="fake",
        dry_run=True,
        yes=True,
    )
    assert report.ok == []
    assert report.log_path == tmp_path / "run.log"


class _StubPlan:
    """План с одним actionable-элементом без видео (оборонная ветка)."""

    def __init__(self, root: Path, items: list[PlanItem]) -> None:
        self.root_path = root
        self._items = items

    def actionable_items(self) -> list[PlanItem]:
        return self._items


def test_apply_plan_item_without_video_raises(tmp_path: Path) -> None:
    stub = _StubPlan(tmp_path, [_item(tmp_path, None)])
    with pytest.raises(ClientError):
        apply_plan(stub, _FakeYT(tmp_path), access_token="fake", dry_run=True, yes=True)


def test_apply_plan_stops_on_first_non_quota_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "run.log"
    monkeypatch.setattr(processor_mod, "_run_log_path", lambda: log_file)
    yt = _FakeYT(tmp_path, fail_update=ClientError("bad request", code="BAD_REQUEST"))
    item = _item(tmp_path, _video("vid_bad", "Заголовок"))
    with pytest.raises(ClientError):
        apply_plan(
            _plan(tmp_path, [item]),
            yt,
            access_token="fake",
            dry_run=False,
            yes=True,
            ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        )
    text = log_file.read_text(encoding="utf-8")
    assert "STOP: first error" in text
    assert "FAIL vid_bad BAD_REQUEST: bad request" in text


def test_apply_plan_stops_on_unexpected_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "run.log"
    monkeypatch.setattr(processor_mod, "_run_log_path", lambda: log_file)
    yt = _FakeYT(tmp_path, fail_update=RuntimeError("kaboom"))
    item = _item(tmp_path, _video("vid_kaboom", "Заголовок"))
    with pytest.raises(RuntimeError):
        apply_plan(
            _plan(tmp_path, [item]),
            yt,
            access_token="fake",
            dry_run=False,
            yes=True,
            ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        )
    text = log_file.read_text(encoding="utf-8")
    assert "STOP: unexpected" in text
    assert "FAIL vid_kaboom kaboom" in text


def test_apply_plan_stops_immediately_on_quota_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "run.log"
    monkeypatch.setattr(processor_mod, "_run_log_path", lambda: log_file)
    yt = _FakeYT(
        tmp_path,
        fail_update=ClientError("quota", code="QUOTA_EXCEEDED", status_code=403),
    )
    item = _item(tmp_path, _video("vid_q", "Заголовок"))
    with pytest.raises(ClientError):
        apply_plan(
            _plan(tmp_path, [item]),
            yt,
            access_token="fake",
            dry_run=False,
            yes=True,
            ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        )
    assert "STOP: 403/429" in log_file.read_text(encoding="utf-8")


def test_apply_one_without_video_raises(tmp_path: Path) -> None:
    item = _item(tmp_path, None)
    ledger = ProcessedLedger(db_path=tmp_path / "p.db")
    with pytest.raises(ClientError):
        processor_mod._apply_one(
            item,
            _FakeYT(tmp_path),
            access_token="fake",
            dry_run=True,
            yes=True,
            ledger=ledger,
            run_id="r",
        )


def test_apply_one_publish_at_rejected_in_dry_run(tmp_path: Path) -> None:
    item = _item(
        tmp_path,
        _video("vid_pa", "Заголовок"),
        publish_at="2026-10-01T09:00:00Z",
    )
    yt = _FakeYT(tmp_path, publish_at_reject=True)
    spent, notes = processor_mod._apply_one(
        item,
        yt,
        access_token="fake",
        dry_run=True,
        yes=True,
        ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        run_id="r",
    )
    assert any("расписан" in n for n in notes)
    # dry-run возвращает оценку, а не реально потраченное
    assert spent == item.estimated_quota


def test_apply_one_thumbnail_counts_quota_and_records_ledger(tmp_path: Path) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff")
    item = _item(tmp_path, _video("vid_thumb", "Заголовок"), thumbnail_path=cover)
    yt = _FakeYT(tmp_path)
    ledger = ProcessedLedger(db_path=tmp_path / "p.db")
    spent, notes = processor_mod._apply_one(
        item,
        yt,
        access_token="fake",
        dry_run=False,
        yes=True,
        ledger=ledger,
        run_id="run-1",
    )
    assert notes == []
    assert yt.thumb_calls == ["vid_thumb"]
    assert spent == 100  # videos.update(50) + thumbnails.set(50)
    assert ledger.is_processed("vid_thumb") is True


def test_apply_one_playlist_counts_quota(tmp_path: Path) -> None:
    item = _item(tmp_path, _video("vid_pl", "Заголовок"), playlist_id="PL123")
    yt = _FakeYT(tmp_path)
    spent, _ = processor_mod._apply_one(
        item,
        yt,
        access_token="fake",
        dry_run=False,
        yes=True,
        ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        run_id="run-2",
    )
    assert yt.playlist_calls == [("PL123", "vid_pl")]
    assert spent == 100  # videos.update(50) + playlistItems.insert(50)


def test_apply_one_playlist_dry_run_returns_estimate(tmp_path: Path) -> None:
    item = _item(tmp_path, _video("vid_pl2", "Заголовок"), playlist_id="PL999")
    yt = _FakeYT(tmp_path)
    spent, _ = processor_mod._apply_one(
        item,
        yt,
        access_token="fake",
        dry_run=True,
        yes=True,
        ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        run_id="run-4",
    )
    assert yt.playlist_calls == [("PL999", "vid_pl2")]
    assert spent == item.estimated_quota


def test_apply_one_thumbnail_missing_file_is_skipped(tmp_path: Path) -> None:
    item = _item(
        tmp_path,
        _video("vid_nocover", "Заголовок"),
        thumbnail_path=tmp_path / "nope.jpg",
    )
    yt = _FakeYT(tmp_path)
    spent, _ = processor_mod._apply_one(
        item,
        yt,
        access_token="fake",
        dry_run=False,
        yes=True,
        ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        run_id="run-3",
    )
    assert yt.thumb_calls == []
    assert spent == 50


# --------------------------------------------------------------------------- #
# folder_scanner
# --------------------------------------------------------------------------- #


def test_read_video_id_hint_oserror_returns_none(tmp_path: Path) -> None:
    from aiyoutubehands.shorts_maker.folder_scanner import _read_video_id_hint

    d = tmp_path / "dir"
    d.mkdir()
    assert _read_video_id_hint(d) is None


def test_scan_folder_non_directory(tmp_path: Path) -> None:
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x", encoding="utf-8")
    cand = scan_folder(f)
    assert cand.skip_reason == "не директория"


def test_scan_folder_skips_nested_directory_entry(tmp_path: Path) -> None:
    d = tmp_path / "ш1 With Subdir"
    d.mkdir()
    (d / "nested").mkdir()
    (d / "ш1_clip.mp4").write_bytes(b"x")
    cand = scan_folder(d)
    assert cand.video_file is not None
    assert cand.skip_reason is None


def test_scan_folder_marker_without_video_id(tmp_path: Path) -> None:
    d = tmp_path / "ш1 Conflict"
    d.mkdir()
    (d / "НУЖНО РАЗОБРАТЬСЯ.txt").write_text("нет идентификатора", encoding="utf-8")
    cand = scan_folder(d)
    assert cand.video_id_hint is None
    assert cand.skip_reason is not None


def test_scan_folder_without_useful_files(tmp_path: Path) -> None:
    d = tmp_path / "ш1 Empty"
    d.mkdir()
    (d / "readme.md").write_text("nothing useful", encoding="utf-8")
    cand = scan_folder(d)
    assert cand.skip_reason == "нет полезных файлов (mp4 / plan / titles)"


def test_scan_folder_uses_mp4_stem_when_folder_generic(tmp_path: Path) -> None:
    d = tmp_path / "clip"
    d.mkdir()
    (d / "ш1 Мой ролик.mp4").write_bytes(b"x")
    cand = scan_folder(d)
    assert cand.clean_title == "Мой ролик"


def test_scan_root_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        scan_root(tmp_path / "does-not-exist")


def test_scan_root_skips_hidden_and_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    hidden = root / ".hidden"
    hidden.mkdir()
    (hidden / "a.mp4").write_bytes(b"x")
    (root / "plain.txt").write_text("x", encoding="utf-8")
    good = root / "ш1 Good"
    good.mkdir()
    (good / "ш1_clip.mp4").write_bytes(b"x")

    candidates = scan_root(root)
    assert [c.folder_name for c in candidates] == ["ш1 Good"]
