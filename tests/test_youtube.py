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
