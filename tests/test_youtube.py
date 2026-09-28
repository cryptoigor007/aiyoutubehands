"""Tests for YoutubeService (dry-run only)."""

from __future__ import annotations

from pathlib import Path

from aiyoutubehands.client import HttpClient
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.youtube import YoutubeService, COST


def test_get_my_channel_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.get_my_channel(dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True


def test_get_video_dry_run(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.get_video("abc", dry_run=True)
    assert result["dry_run"] is True


def test_cost_table() -> None:
    assert COST["videos.insert"] == 1600
    assert COST["search.list"] == 100


def test_claims_unsupported(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    r = yt.claims_unsupported()
    assert r["status"] == "UNSUPPORTED"


def test_update_requires_yes(tmp_path: Path) -> None:
    from aiyoutubehands.client import ClientError
    from aiyoutubehands.models.youtube import VideoSnippet
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    try:
        yt.update_video("v", snippet=VideoSnippet(title="t"), dry_run=False, yes=False)
        raise AssertionError("expected ClientError")
    except ClientError as e:
        assert e.code == "CONFIRM_REQUIRED"


def test_schedule_and_playlist_dry_run(tmp_path: Path) -> None:
    client = HttpClient()
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    r = yt.schedule_video("vid", "2026-10-01T12:00:00Z", dry_run=True, yes=True)
    assert r["dry_run"] is True
    r2 = yt.create_playlist("T", dry_run=True, yes=True)
    assert r2["dry_run"] is True
    r3 = yt.moderate_comment("c1", "published", dry_run=True, yes=True)
    assert r3.get("dry_run") is True or "dry_run" in r3


def test_list_channel_videos_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.list_channel_videos(max_age_days=14, dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True
    assert result["method"] == "list_channel_videos"


def test_list_video_ids_in_playlists_dry_run(tmp_path: Path) -> None:
    client = HttpClient(access_token="fake")
    quota = QuotaEngine(db_path=tmp_path / "q.db")
    yt = YoutubeService(client, quota, expected_channel_id="UC_test")
    result = yt.list_video_ids_in_playlists(dry_run=True)
    assert isinstance(result, dict)
    assert result["dry_run"] is True
