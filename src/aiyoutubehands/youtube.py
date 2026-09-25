"""YouTube API methods with quota tracking and safety guards."""

from __future__ import annotations

from typing import Any

from aiyoutubehands.client import ClientError, HttpClient
from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import (
    CaptionResource,
    ChannelResource,
    CommentResource,
    PlaylistResource,
    VideoResource,
    VideoSnippet,
    VideoStatus,
)
from aiyoutubehands.quota import QuotaEngine

log = get_logger(__name__)

COST = {
    "channels.list": 1,
    "videos.list": 1,
    "videos.insert": 1600,
    "videos.update": 50,
    "videos.delete": 50,
    "search.list": 100,
    "playlists.list": 1,
    "playlistItems.list": 1,
    "commentThreads.list": 1,
    "comments.insert": 50,
    "comments.setModerationStatus": 50,
    "captions.list": 50,
    "captions.insert": 400,
    "thumbnails.set": 50,
}


class YoutubeService:
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
        if channel_id and self.expected_channel_id and channel_id != self.expected_channel_id:
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
        self, *, ids: list[str] | None = None, dry_run: bool = False
    ) -> list[VideoResource] | dict[str, Any]:
        self.quota.check(COST["videos.list"])
        if not ids:
            raise ClientError("Нужны ids", code="BAD_REQUEST")
        data = self.client.get(
            "videos",
            params={"part": "snippet,status", "id": ",".join(ids)},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("videos.list", COST["videos.list"])
        return [VideoResource.from_api(i) for i in (data.get("items") or [])]

    def update_video(
        self,
        video_id: str,
        snippet: VideoSnippet | None = None,
        status: VideoStatus | None = None,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> VideoResource | dict[str, Any]:
        if not yes and not dry_run:
            raise ClientError(
                "Нужен --yes для изменения видео",
                code="CONFIRM_REQUIRED",
                action="Передайте --yes",
            )
        self.quota.check(COST["videos.update"])
        body: dict[str, Any] = {"id": video_id}
        parts: list[str] = []
        if snippet is not None:
            body["snippet"] = snippet.to_api()
            parts.append("snippet")
        if status is not None:
            body["status"] = status.to_api()
            parts.append("status")
        if not parts:
            raise ClientError("Нечего обновлять", code="BAD_REQUEST")
        data = self.client.put(
            "videos",
            params={"part": ",".join(parts)},
            json_body=body,
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("videos.update", COST["videos.update"])
        return VideoResource.from_api(data)

    def delete_video(
        self, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        if not yes and not dry_run:
            raise ClientError(
                "Нужен --yes для удаления видео",
                code="CONFIRM_REQUIRED",
                action="Передайте --yes",
            )
        self.quota.check(COST["videos.delete"])
        data = self.client.delete("videos", params={"id": video_id}, dry_run=dry_run)
        if dry_run:
            return data if isinstance(data, dict) else {"dry_run": True}
        self.quota.consume("videos.delete", COST["videos.delete"])
        return {"ok": True, "video_id": video_id}

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

    def list_comment_threads(
        self, video_id: str, *, max_results: int = 20, dry_run: bool = False
    ) -> list[CommentResource] | dict[str, Any]:
        self.quota.check(COST["commentThreads.list"])
        data = self.client.get(
            "commentThreads",
            params={
                "part": "snippet",
                "videoId": video_id,
                "maxResults": max_results,
                "textFormat": "plainText",
            },
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("commentThreads.list", COST["commentThreads.list"])
        return [CommentResource.from_api(i) for i in (data.get("items") or [])]

    def reply_to_comment(
        self, parent_id: str, text: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        if not yes and not dry_run:
            raise ClientError("Нужен --yes для ответа на комментарий", code="CONFIRM_REQUIRED")
        self.quota.check(COST["comments.insert"])
        body = {"snippet": {"parentId": parent_id, "textOriginal": text}}
        data = self.client.post(
            "comments",
            params={"part": "snippet"},
            json_body=body,
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("comments.insert", COST["comments.insert"])
        return data

    def list_captions(
        self, video_id: str, *, dry_run: bool = False
    ) -> list[CaptionResource] | dict[str, Any]:
        self.quota.check(COST["captions.list"])
        data = self.client.get(
            "captions",
            params={"part": "snippet", "videoId": video_id},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("captions.list", COST["captions.list"])
        return [CaptionResource.from_api(i) for i in (data.get("items") or [])]

    def claims_unsupported(self) -> dict[str, str]:
        """Content ID claims are not supported via public Data API fully."""
        return {
            "status": "UNSUPPORTED",
            "message": "Claims / Content ID через публичный Data API не поддерживаются",
        }
