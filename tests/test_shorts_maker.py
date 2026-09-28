"""Tests for shorts_maker post-processing package."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.shorts_maker.folder_scanner import (
    clean_folder_title,
    scan_folder,
    scan_root,
)
from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
from aiyoutubehands.shorts_maker.matcher import is_already_styled, match_candidates
from aiyoutubehands.shorts_maker.metadata_extractor import extract_metadata
from aiyoutubehands.shorts_maker.plan import build_plan, render_plan_table
from aiyoutubehands.shorts_maker.scheduler import propose_slots, format_slot_local
from aiyoutubehands.quota import QuotaEngine


MSK = ZoneInfo("Europe/Moscow")


def _make_folder(
    root: Path,
    name: str,
    *,
    mp4: bool = True,
    cover: bool = True,
    titles: str | None = None,
    hashtags: str | None = None,
    editing_plan: dict | None = None,
    marker: str | None = None,
) -> Path:
    d = root / name
    d.mkdir(parents=True)
    prefix = name.split()[0] if name else "ш1"
    if mp4:
        (d / f"{prefix}_clip.mp4").write_bytes(b"fake")
    if cover:
        (d / f"{prefix}_final_cover.jpg").write_bytes(b"\xff\xd8\xff")
    if titles is not None:
        (d / f"{prefix}_titles.txt").write_text(titles, encoding="utf-8")
    if hashtags is not None:
        (d / f"{prefix}_hashtags.txt").write_text(hashtags, encoding="utf-8")
    if editing_plan is not None:
        (d / f"{prefix}_editing_plan.json").write_text(
            json.dumps(editing_plan, ensure_ascii=False), encoding="utf-8"
        )
    if marker == "PEREDELAT":
        (d / f"{prefix}_final_ПЕРЕДЕЛАТЬ.txt").write_text("x", encoding="utf-8")
    if marker == "RAZOBRATSYA":
        (d / "НУЖНО РАЗОБРАТЬСЯ.txt").write_text(
            "conflict Video ID: dQw4w9WgXcQ please check", encoding="utf-8"
        )
    return d


def test_clean_folder_title() -> None:
    assert clean_folder_title("ш1 Почему люди завидуют?") == "Почему люди завидуют?"
    assert clean_folder_title("ш12 Title") == "Title"
    assert clean_folder_title("без префикса") == "без префикса"


def test_scan_skips_markers(tmp_path: Path) -> None:
    _make_folder(tmp_path, "ш1 Good", marker=None)
    _make_folder(tmp_path, "ш2 Bad", marker="PEREDELAT")
    _make_folder(tmp_path, "ш3 Conflict", marker="RAZOBRATSYA")
    cands = scan_root(tmp_path)
    assert len(cands) == 3
    by_name = {c.folder_name: c for c in cands}
    assert by_name["ш1 Good"].should_skip is False
    assert "ПЕРЕДЕЛАТЬ" in (by_name["ш2 Bad"].skip_reason or "")
    assert "РАЗОБРАТЬСЯ" in (by_name["ш3 Conflict"].skip_reason or "")
    assert by_name["ш3 Conflict"].video_id_hint == "dQw4w9WgXcQ"


def test_prefix_mismatch(tmp_path: Path) -> None:
    d = tmp_path / "ш5 Title"
    d.mkdir()
    (d / "ш35_clip.mp4").write_bytes(b"x")
    cand = scan_folder(d)
    assert cand.prefix_mismatch is True
    assert cand.should_skip is True


def test_extract_metadata_priority(tmp_path: Path) -> None:
    plan = {
        "clips": [
            {
                "description": "Завидуют не вещам, а смелости!",
                "hashtags": ["зависть", "психология"],
            }
        ]
    }
    d = _make_folder(
        tmp_path,
        "ш1 Почему люди завидуют?",
        titles="Почему люди завидуют?\n\nСтарое описание из txt",
        hashtags="#shorts #мотивация",
        editing_plan=plan,
    )
    cand = scan_folder(d)
    meta = extract_metadata(cand)
    assert meta.title == "Почему люди завидуют?"
    assert "смелости" in meta.description
    assert "shorts" in [t.lower() for t in meta.tags]
    assert meta.thumbnail is not None


def test_extract_from_titles_when_no_plan(tmp_path: Path) -> None:
    d = _make_folder(
        tmp_path,
        "ш2 Only titles",
        titles="Заголовок\n\nДлинное описание из файла titles больше сорока символов точно.",
        hashtags=None,
        editing_plan=None,
    )
    cand = scan_folder(d)
    meta = extract_metadata(cand)
    assert "Длинное описание" in meta.description


def test_is_already_styled() -> None:
    v = VideoResource.from_api({
        "id": "x",
        "snippet": {
            "title": "A proper long enough title here",
            "description": "x" * 60,
            "tags": ["a", "b", "c"],
            "thumbnails": {"maxres": {"url": "http://x", "width": 1280, "height": 720}},
        },
        "status": {"privacyStatus": "public"},
    })
    assert is_already_styled(v) is True

    v2 = VideoResource.from_api({
        "id": "y",
        "snippet": {
            "title": "short",
            "description": "x",
            "tags": [],
            "thumbnails": {},
        },
        "status": {"privacyStatus": "private"},
    })
    assert is_already_styled(v2) is False

    v3 = VideoResource.from_api({
        "id": "z",
        "snippet": {
            "title": "t",
            "description": "hello #ayh_processed",
        },
        "status": {"privacyStatus": "private"},
    })
    assert is_already_styled(v3) is True


def test_match_by_title(tmp_path: Path) -> None:
    d = _make_folder(tmp_path, "ш1 Почему люди завидуют?")
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "vid1",
        "snippet": {
            "title": "Почему люди завидуют?",
            "description": "",
            "publishedAt": "",
        },
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT45S"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    results = match_candidates([cand], [video])
    assert len(results) == 1
    assert results[0].method == "title"
    assert results[0].reason == "ok"
    assert results[0].video is not None
    assert results[0].video.id == "vid1"


def test_match_skip_processed_ledger(tmp_path: Path) -> None:
    d = _make_folder(tmp_path, "ш1 Почему люди завидуют?")
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "vid1",
        "snippet": {"title": "Почему люди завидуют?", "description": ""},
        "status": {"privacyStatus": "private"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    results = match_candidates([cand], [video], processed_ids={"vid1"})
    assert results[0].reason.startswith("уже обработано")


def test_scheduler_skips_tue_fri() -> None:
    # Fixed Monday 2026-09-28 10:00 MSK
    now = datetime(2026, 9, 28, 10, 0, tzinfo=MSK)
    videos = [
        VideoResource.from_api({
            "id": f"v{i}",
            "snippet": {"title": "t", "publishedAt": ""},
            "status": {"privacyStatus": "private"},
        })
        for i in range(6)
    ]
    slots = propose_slots(videos, now=now)
    assert all(s is not None for s in slots)
    for s in slots:
        assert s is not None
        dt = datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(MSK)
        assert dt.weekday() not in (1, 4)
        assert dt.hour in (12, 18)


def test_scheduler_unavailable_for_public() -> None:
    v = VideoResource.from_api({
        "id": "pub",
        "snippet": {"title": "t", "publishedAt": "2026-01-01T00:00:00Z"},
        "status": {"privacyStatus": "public"},
    })
    slots = propose_slots([v])
    assert slots == [None]
    assert format_slot_local(None) == "расписание недоступно"


def test_ledger_record_and_marker(tmp_path: Path) -> None:
    led = ProcessedLedger(db_path=tmp_path / "p.db")
    assert led.is_processed("v1") is False
    led.record("v1", folder_name="ш1", title="T")
    assert led.is_processed("v1") is True
    assert "v1" in led.all_ids()
    desc = ProcessedLedger.append_marker("Hello")
    assert "#ayh_processed" in desc
    desc2 = ProcessedLedger.append_marker(desc)
    assert desc2.count("#ayh_processed") == 1


def test_build_plan_and_table(tmp_path: Path) -> None:
    d = _make_folder(
        tmp_path,
        "ш1 Почему люди завидуют?",
        titles="T\n\nОписание достаточно длинное для теста описания видео.",
        hashtags="#a #b #c",
    )
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "vid1",
        "snippet": {
            "title": "Почему люди завидуют?",
            "description": "",
            "publishedAt": "",
        },
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT40S"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    matches = match_candidates([cand], [video])
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    plan = build_plan(matches, root_path=tmp_path, quota=quota)
    assert len(plan.actionable_items()) == 1
    assert plan.confirm_phrase.startswith("подтверждаю план от ")
    table = render_plan_table(plan)
    assert "Новый title" in table
    assert "к обработке" in table
    assert plan.actionable_items()[0].estimated_quota >= 50


def test_ai_fallback_fills_gaps(tmp_path: Path) -> None:
    d = _make_folder(tmp_path, "ш9 Only title", titles=None, hashtags=None, editing_plan=None)
    cand = scan_folder(d)
    meta = extract_metadata(cand, allow_ai=True)
    assert meta.description  # filled by AI stub
    assert len(meta.tags) >= 2
    assert any("ai" in n for n in meta.source_notes)


def test_probe_duration_missing_file(tmp_path: Path) -> None:
    from aiyoutubehands.shorts_maker.media import probe_duration_seconds

    assert probe_duration_seconds(tmp_path / "nope.mp4") is None


def test_match_by_duration(tmp_path: Path) -> None:
    """When local duration matches exactly one channel video (±1s)."""
    from aiyoutubehands.shorts_maker.media import probe_duration_seconds

    d = _make_folder(tmp_path, "ш7 Unique duration")
    cand = scan_folder(d)
    # Fake mp4 won't probe; inject by patching
    import aiyoutubehands.shorts_maker.matcher as matcher_mod

    real_probe = matcher_mod.probe_duration_seconds if hasattr(matcher_mod, "probe_duration_seconds") else None

    videos = [
        VideoResource.from_api({
            "id": "va",
            "snippet": {"title": "raw_a", "publishedAt": "", "description": ""},
            "status": {"privacyStatus": "private"},
            "contentDetails": {"duration": "PT45S"},
            "processingDetails": {"processingStatus": "succeeded"},
        }),
        VideoResource.from_api({
            "id": "vb",
            "snippet": {"title": "raw_b", "publishedAt": "", "description": ""},
            "status": {"privacyStatus": "private"},
            "contentDetails": {"duration": "PT30S"},
            "processingDetails": {"processingStatus": "succeeded"},
        }),
    ]

    import aiyoutubehands.shorts_maker.media as media_mod

    orig = media_mod.probe_duration_seconds
    media_mod.probe_duration_seconds = lambda _p: 45  # type: ignore[assignment]
    try:
        results = match_candidates([cand], videos)
    finally:
        media_mod.probe_duration_seconds = orig  # type: ignore[assignment]

    assert results[0].method == "duration_date"
    assert results[0].video is not None
    assert results[0].video.id == "va"


def test_sole_recent_video_is_not_matched_without_title_evidence(
    tmp_path: Path,
) -> None:
    """Папка без совпадения по заголовку не должна «захватывать» видео.

    Регресс: при единственном «недавнем» видео в выборке папка сопоставлялась
    с ним без доказательств, и план помечал это готовым к записи. Правила
    репозитория (AGENT_PROMPT_PROCESS.md §0.1.3, §6) требуют при сомнении
    пропускать, а не угадывать.
    """
    d = _make_folder(tmp_path, "ш7 Совершенно другой ролик")
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "sole1",
        "snippet": {"title": "raw_filename_1234", "description": "", "publishedAt": ""},
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT30S"},
        "processingDetails": {"processingStatus": "succeeded"},
        "statistics": {"viewCount": "0"},
    })

    import aiyoutubehands.shorts_maker.media as media_mod

    orig = media_mod.probe_duration_seconds
    media_mod.probe_duration_seconds = lambda _p: None  # ffprobe недоступен
    try:
        results = match_candidates([cand], [video])
    finally:
        media_mod.probe_duration_seconds = orig  # type: ignore[assignment]

    assert results[0].video is None
    assert results[0].reason == "не сопоставлено"


def test_apply_plan_dry_run(tmp_path: Path) -> None:
    """Processor dry-run does not require network; spends estimated quota only."""
    from aiyoutubehands.client import HttpClient
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.shorts_maker.processor import apply_plan
    from aiyoutubehands.youtube import YoutubeService

    d = _make_folder(
        tmp_path,
        "ш1 Почему люди завидуют?",
        titles="T\n\nОписание достаточно длинное для теста описания ролика.",
        hashtags="#a #b #c",
    )
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "vid_dry",
        "snippet": {
            "title": "Почему люди завидуют?",
            "description": "",
            "publishedAt": "",
            "channelId": "UC_test",
        },
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT40S"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    matches = match_candidates([cand], [video])
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    plan = build_plan(matches, root_path=tmp_path, quota=quota)
    assert plan.actionable_items()

    client = HttpClient(access_token="fake")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    ledger = ProcessedLedger(db_path=tmp_path / "p.db")
    report = apply_plan(
        plan,
        yt,
        access_token="fake",
        dry_run=True,
        yes=True,
        ledger=ledger,
    )
    assert len(report.ok) == 1
    assert report.ok[0] == "vid_dry"
    assert ledger.is_processed("vid_dry") is False  # dry-run must not write ledger
    assert report.log_path is not None


def test_is_already_styled_with_playlist() -> None:
    v = VideoResource.from_api({
        "id": "inpl",
        "snippet": {
            "title": "A proper long enough title here",
            "description": "short",
            "tags": ["a"],
            "thumbnails": {},
        },
        "status": {"privacyStatus": "private"},
    })
    # Without playlist: only 1 signal (title) → not styled
    assert is_already_styled(v) is False
    # With playlist membership + title + ... need ≥3
    # title (1) + playlist (1) = 2 → still False
    assert is_already_styled(v, in_playlist_ids={"inpl"}) is False
    # Add description length
    v2 = VideoResource.from_api({
        "id": "inpl2",
        "snippet": {
            "title": "A proper long enough title here",
            "description": "x" * 60,
            "tags": ["a"],
            "thumbnails": {},
        },
        "status": {"privacyStatus": "private"},
    })
    # title + desc + playlist = 3
    assert is_already_styled(v2, in_playlist_ids={"inpl2"}) is True


def test_is_likely_short_missing(tmp_path: Path) -> None:
    from aiyoutubehands.shorts_maker.media import is_likely_short, probe_is_vertical

    assert probe_is_vertical(tmp_path / "no.mp4") is None
    assert is_likely_short(tmp_path / "no.mp4") is None


def test_full_pipeline_dry_run(tmp_path: Path) -> None:
    """scan → match → plan → apply (dry-run) end-to-end without network."""
    from aiyoutubehands.client import HttpClient
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.shorts_maker.processor import apply_plan
    from aiyoutubehands.youtube import YoutubeService

    root = tmp_path / "shorts"
    root.mkdir()
    _make_folder(
        root,
        "ш1 Почему люди завидуют?",
        titles="Почему люди завидуют?\n\nЗавидуют не вещам, а смелости и решительности!",
        hashtags="#психология #shorts #мотивация",
        editing_plan={
            "clips": [{"description": "Завидуют не вещам, а смелости!", "hashtags": ["зависть"]}]
        },
    )
    _make_folder(root, "ш2 Skip me", marker="PEREDELAT")

    candidates = scan_root(root)
    assert len(candidates) == 2
    assert any(c.should_skip for c in candidates)

    video = VideoResource.from_api({
        "id": "pipe1",
        "snippet": {
            "title": "Почему люди завидуют?",
            "description": "",
            "publishedAt": "",
            "channelId": "UC_test",
            "tags": [],
            "thumbnails": {},
        },
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT42S"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    matches = match_candidates(candidates, [video])
    actionable = [m for m in matches if m.reason == "ok"]
    assert len(actionable) == 1

    quota = QuotaEngine(db_path=tmp_path / "q.db")
    plan = build_plan(matches, root_path=root, quota=quota)
    assert len(plan.actionable_items()) == 1
    item = plan.actionable_items()[0]
    assert "смелости" in item.new_description
    assert item.thumbnail_path is not None
    assert plan.confirm_phrase.startswith("подтверждаю план от ")

    yt = YoutubeService(HttpClient(access_token="fake"), quota, expected_channel_id="UC_test")
    report = apply_plan(
        plan, yt, access_token="fake", dry_run=True, yes=True,
        ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
    )
    assert report.ok == ["pipe1"]
    assert report.failed == []


def test_publish_at_retry_only_on_publishat_error(tmp_path: Path) -> None:
    """Non-publishAt ClientError must not be swallowed by retry path."""
    from aiyoutubehands.client import ClientError, HttpClient
    from aiyoutubehands.quota import QuotaEngine
    from aiyoutubehands.shorts_maker.processor import apply_plan
    from aiyoutubehands.youtube import YoutubeService

    d = _make_folder(
        tmp_path,
        "ш1 Retry test title long",
        titles="T\n\nОписание достаточно длинное для теста описания ролика.",
        hashtags="#a #b #c",
    )
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "vid_err",
        "snippet": {
            "title": "Retry test title long",
            "description": "",
            "publishedAt": "",
            "channelId": "UC_test",
        },
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT40S"},
        "processingDetails": {"processingStatus": "succeeded"},
    })
    matches = match_candidates([cand], [video])
    plan = build_plan(matches, root_path=tmp_path, quota=QuotaEngine(db_path=tmp_path / "q.db"))
    assert plan.actionable_items()

    class BoomYT(YoutubeService):
        def update_video(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise ClientError("permission denied", code="FORBIDDEN", status_code=403)

    yt = BoomYT(HttpClient(access_token="fake"), QuotaEngine(db_path=tmp_path / "q2.db"), "UC_test")
    try:
        apply_plan(
            plan, yt, access_token="fake", dry_run=False, yes=True,
            ledger=ProcessedLedger(db_path=tmp_path / "p.db"),
        )
        raise AssertionError("expected ClientError")
    except ClientError as e:
        assert e.code == "FORBIDDEN"


def test_folder_duplicates_skip_both(tmp_path: Path) -> None:
    root = tmp_path / "sm"
    root.mkdir()
    _make_folder(root, "ш1 Один title")
    _make_folder(root, "ш2 Один title")  # same clean title after prefix strip? 
    # clean titles: "Один title" and "Один title" 
    cands = scan_root(root)
    # Force same clean_title
    for c in cands:
        c.clean_title = "Один title"
    video = VideoResource.from_api({
        "id": "only1",
        "snippet": {"title": "Один title", "description": "", "publishedAt": ""},
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT30S"},
        "processingDetails": {"processingStatus": "succeeded"},
        "statistics": {"viewCount": "0"},
    })
    results = match_candidates(cands, [video])
    # Both should be skipped as folder duplicates
    assert all("дубликат" in r.reason for r in results)
    assert all(r.related_folders for r in results)


def test_ambiguous_title_lists_ids(tmp_path: Path) -> None:
    d = _make_folder(tmp_path, "ш1 Shared")
    cand = scan_folder(d)
    cand.clean_title = "Shared"
    v1 = VideoResource.from_api({
        "id": "idAAA11111",
        "snippet": {"title": "Shared", "description": "", "publishedAt": ""},
        "status": {"privacyStatus": "private"},
        "processingDetails": {"processingStatus": "succeeded"},
        "statistics": {"viewCount": "0"},
    })
    v2 = VideoResource.from_api({
        "id": "idBBB22222",
        "snippet": {"title": "Shared", "description": "", "publishedAt": ""},
        "status": {"privacyStatus": "private"},
        "processingDetails": {"processingStatus": "succeeded"},
        "statistics": {"viewCount": "0"},
    })
    results = match_candidates([cand], [v1, v2])
    assert results[0].video is None
    assert "неоднознач" in results[0].reason
    assert "idAAA11111" in results[0].related_video_ids
    assert "idBBB22222" in results[0].related_video_ids


def test_public_with_views_skipped(tmp_path: Path) -> None:
    d = _make_folder(tmp_path, "ш1 Почему люди завидуют?")
    cand = scan_folder(d)
    video = VideoResource.from_api({
        "id": "pub1",
        "snippet": {
            "title": "Почему люди завидуют?",
            "description": "",
            "publishedAt": "2026-01-01T00:00:00Z",
        },
        "status": {"privacyStatus": "public"},
        "processingDetails": {"processingStatus": "succeeded"},
        "statistics": {"viewCount": "12"},
    })
    results = match_candidates([cand], [video])
    assert results[0].reason != "ok"
    assert "просмотры" in results[0].reason or "public" in results[0].reason or "privacy" in results[0].reason
