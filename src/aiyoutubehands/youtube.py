"""YouTube API methods (read-focused; mutations require explicit --yes / confirmation)."""

from __future__ import annotations

from typing import Any

from aiyoutubehands.client import HttpClient, ClientError
from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import (
    ChannelResource,
    PlaylistResource,
    VideoResource,
)
from aiyoutubehands.quota import QuotaEngine

log = get_logger(__name__)

# Approximate quota costs (YouTube Data API v3)
COST = {
    "channels.list": 1,
    "videos.list": 1,
    "search.list": 100,
    "playlists.list": 1,
    "playlistItems.list": 1,
    "videos.insert": 1600,
    "videos.update": 50,
    "videos.delete": 50,
    "thumbnails.set": 50,
}


class YoutubeService:
    """High-level YouTube operations with quota tracking and channel guard."""

    def __init__(
        self,
        client: HttpClient,
        quota: QuotaEngine,
        expected_channel_id: str,
    ) -> None:
        self.client = client
        self.quota = quota
        self.expected_channel_id = expected_channel_id

    def _guard_channel(self, channel_id: str) -> None:
        if channel_id and channel_id != self.expected_channel_id:
            raise ClientError(
                f"channel_id mismatch: got {channel_id}, expected {self.expected_channel_id}",
                code="CHANNEL_MISMATCH",
                action="Проверьте expected_channel_id в конфиге",
                retryable=False,
            )

    def get_my_channel(self, *, dry_run: bool = False) -> ChannelResource | dict[str, Any]:
        self.quota.check(COST["channels.list"])
        data = self.client.get(
            "channels",
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        items = data.get("items") or []
        if not items:
            raise ClientError("Канал не найден", code="CHANNEL_NOT_FOUND")
        ch = ChannelResource.from_api(items[0])
        self._guard_channel(ch.id)
        self.quota.consume("channels.list", COST["channels.list"])
        return ch

    def get_video(self, video_id: str, *, dry_run: bool = False) -> VideoResource | dict[str, Any]:
        self.quota.check(COST["videos.list"])
        data = self.client.get(
            "videos",
            params={"part": "snippet,status,contentDetails", "id": video_id},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        items = data.get("items") or []
        if not items:
            raise ClientError(f"Видео {video_id} не найдено", code="NOT_FOUND")
        self.quota.consume("videos.list", COST["videos.list"])
        return VideoResource.from_api(items[0])

    def list_videos(
        self,
        *,
        ids: list[str] | None = None,
        dry_run: bool = False,
    ) -> list[VideoResource] | dict[str, Any]:
        self.quota.check(COST["videos.list"])
        params: dict[str, Any] = {"part": "snippet,status"}
        if ids:
            params["id"] = ",".join(ids)
        else:
            raise ClientError("Нужны ids", code="BAD_REQUEST")
        data = self.client.get("videos", params=params, dry_run=dry_run)
        if dry_run:
            return data
        self.quota.consume("videos.list", COST["videos.list"])
        return [VideoResource.from_api(i) for i in (data.get("items") or [])]

    def list_playlists(self, *, dry_run: bool = False) -> list[PlaylistResource] | dict[str, Any]:
        self.quota.check(COST["playlists.list"])
        data = self.client.get(
            "playlists",
            params={"part": "snippet,contentDetails", "mine": "true", "maxResults": 50},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("playlists.list", COST["playlists.list"])
        return [PlaylistResource.from_api(i) for i in (data.get("items") or [])]
