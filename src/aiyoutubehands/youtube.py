"""YouTube API methods with quota tracking and safety guards."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from aiyoutubehands.client import ClientError, HttpClient, require_access_token
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
    "playlists.insert": 50,
    "playlists.update": 50,
    "playlists.delete": 50,
    "playlistItems.list": 1,
    "playlistItems.insert": 50,
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
        self._channel_verified = False

    def _guard_channel(self, channel_id: str) -> None:
        if not self.expected_channel_id:
            raise ClientError(
                "Не задан channel.expected_channel_id — операция запрещена",
                code="CHANNEL_NOT_CONFIGURED",
                action="Укажите channel.expected_channel_id в config.yaml",
                retryable=False,
            )
        if channel_id != self.expected_channel_id:
            raise ClientError(
                f"channel_id mismatch: got {channel_id}, expected {self.expected_channel_id}",
                code="CHANNEL_MISMATCH",
                action="Проверьте expected_channel_id в конфиге",
                retryable=False,
            )

    def _verify_expected_channel(self) -> None:
        """Разово проверить, что токен принадлежит ожидаемому каналу.

        Вызывается перед первой реальной мутацией. Раньше _guard_channel жил
        только внутри get_my_channel(), поэтому ни один write-метод канал не
        проверял, и exit-код CHANNEL_MISMATCH (71) был недостижим для записей.
        """
        if self._channel_verified:
            return
        self.get_my_channel(dry_run=False)  # внутри вызывает _guard_channel
        self._channel_verified = True

    def _require_yes(self, yes: bool, dry_run: bool, action: str) -> None:
        if not yes and not dry_run:
            raise ClientError(
                f"Нужен --yes для: {action}",
                code="CONFIRM_REQUIRED",
                action="Передайте --yes",
            )

    def _require_write(self, yes: bool, dry_run: bool, action: str) -> None:
        """Гард для любого write-метода: подтверждение + проверка канала."""
        self._require_yes(yes, dry_run, action)
        if not dry_run:
            self._verify_expected_channel()

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
        part: str = "snippet,status,contentDetails,processingDetails,statistics",
        dry_run: bool = False,
    ) -> list[VideoResource] | dict[str, Any]:
        self.quota.check(COST["videos.list"])
        if not ids:
            raise ClientError("Нужны ids", code="BAD_REQUEST")
        data = self.client.get(
            "videos",
            params={"part": part, "id": ",".join(ids)},
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("videos.list", COST["videos.list"])
        return [VideoResource.from_api(i) for i in (data.get("items") or [])]

    def list_channel_videos(
        self,
        *,
        max_age_days: int = 14,
        max_results: int = 200,
        dry_run: bool = False,
    ) -> list[VideoResource] | dict[str, Any]:
        """List recent videos from the channel uploads playlist.

        Uses playlistItems.list (1 unit/page) + batched videos.list (1 unit per 50 ids).
        Filters by publishedAt within max_age_days when possible.
        """
        from datetime import datetime, timedelta, timezone

        if dry_run:
            return {
                "dry_run": True,
                "method": "list_channel_videos",
                "max_age_days": max_age_days,
                "max_results": max_results,
            }

        channel = self.get_my_channel(dry_run=False)
        if not isinstance(channel, ChannelResource):
            raise ClientError("Не удалось получить канал", code="CHANNEL_NOT_FOUND")
        uploads_id = (
            (channel.raw.get("contentDetails") or {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not uploads_id:
            raise ClientError(
                "uploads playlist не найден",
                code="NOT_FOUND",
                action="Проверьте права канала",
            )

        # Collect video IDs from uploads playlist
        video_ids: list[str] = []
        page_token: str | None = None
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

        while len(video_ids) < max_results:
            self.quota.check(COST["playlistItems.list"])
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": uploads_id,
                "maxResults": min(50, max_results - len(video_ids)),
            }
            if page_token:
                params["pageToken"] = page_token
            data = self.client.get("playlistItems", params=params, dry_run=False)
            self.quota.consume("playlistItems.list", COST["playlistItems.list"])
            items = data.get("items") or []
            if not items:
                break
            stop_early = False
            for item in items:
                sn = item.get("snippet") or {}
                published = sn.get("publishedAt") or ""
                if published:
                    try:
                        pub_dt = datetime.fromisoformat(
                            published.replace("Z", "+00:00")
                        )
                        if pub_dt < cutoff:
                            stop_early = True
                            break
                    except ValueError:
                        pass
                rid = (sn.get("resourceId") or {}).get("videoId")
                if rid:
                    video_ids.append(str(rid))
            if stop_early:
                break
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        if not video_ids:
            return []

        # Batch videos.list (50 ids = 1 unit)
        result: list[VideoResource] = []
        batch_size = 50
        for i in range(0, len(video_ids), batch_size):
            batch = video_ids[i : i + batch_size]
            batch_videos = self.list_videos(ids=batch, dry_run=False)
            if isinstance(batch_videos, list):
                result.extend(batch_videos)
        return result

    def list_video_ids_in_playlists(
        self,
        *,
        max_playlists: int = 25,
        dry_run: bool = False,
    ) -> set[str] | dict[str, Any]:
        """Return set of video IDs that appear in at least one of the user's playlists.

        Used for the «already styled» playlist membership signal.
        Quota: playlists.list (1) + playlistItems.list (1 per page per playlist).
        """
        if dry_run:
            return {"dry_run": True, "method": "list_video_ids_in_playlists"}

        playlists = self.list_playlists(dry_run=False)
        if not isinstance(playlists, list):
            return set()

        in_any: set[str] = set()
        for pl in playlists[:max_playlists]:
            page_token: str | None = None
            pages = 0
            while pages < 5:  # safety: max 250 items per playlist
                pages += 1
                self.quota.check(COST["playlistItems.list"])
                params: dict[str, Any] = {
                    "part": "contentDetails",
                    "playlistId": pl.id,
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token
                data = self.client.get("playlistItems", params=params, dry_run=False)
                self.quota.consume("playlistItems.list", COST["playlistItems.list"])
                for item in data.get("items") or []:
                    vid = (item.get("contentDetails") or {}).get("videoId")
                    if vid:
                        in_any.add(str(vid))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return in_any

    def update_video(
        self,
        video_id: str,
        snippet: VideoSnippet | None = None,
        status: VideoStatus | None = None,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> VideoResource | dict[str, Any]:
        self._require_write(yes, dry_run, "изменения видео")
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

    def schedule_video(
        self,
        video_id: str,
        publish_at: str,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> VideoResource | dict[str, Any]:
        """Set privacy to private + publishAt (YouTube schedule)."""
        status = VideoStatus(privacy_status="private", publish_at=publish_at)
        return self.update_video(video_id, status=status, dry_run=dry_run, yes=yes)

    def publish_video(
        self, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> VideoResource | dict[str, Any]:
        status = VideoStatus(privacy_status="public", publish_at=None)
        return self.update_video(video_id, status=status, dry_run=dry_run, yes=yes)

    def delete_video(
        self, video_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self._require_write(yes, dry_run, "удаления видео")
        self.quota.check(COST["videos.delete"])
        data = self.client.delete("videos", params={"id": video_id}, dry_run=dry_run)
        if dry_run:
            return data if isinstance(data, dict) else {"dry_run": True}
        self.quota.consume("videos.delete", COST["videos.delete"])
        return {"ok": True, "video_id": video_id}

    def list_playlists(self, *, dry_run: bool = False) -> list[PlaylistResource] | dict[str, Any]:
        self.quota.check(COST["playlists.list"])
        if dry_run:
            return self.client.get(
                "playlists",
                params={
                    "part": "snippet,contentDetails",
                    "mine": "true",
                    "maxResults": 50,
                },
                dry_run=True,
            )
        out: list[PlaylistResource] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "mine": "true",
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            data = self.client.get("playlists", params=params, dry_run=False)
            self.quota.consume("playlists.list", COST["playlists.list"])
            out.extend(PlaylistResource.from_api(i) for i in (data.get("items") or []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    def create_playlist(
        self,
        title: str,
        description: str = "",
        privacy: str = "private",
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> PlaylistResource | dict[str, Any]:
        self._require_write(yes, dry_run, "создания плейлиста")
        self.quota.check(COST["playlists.insert"])
        body = {
            "snippet": {"title": title, "description": description},
            "status": {"privacyStatus": privacy},
        }
        data = self.client.post(
            "playlists",
            params={"part": "snippet,status"},
            json_body=body,
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("playlists.insert", COST["playlists.insert"])
        return PlaylistResource.from_api(data)

    def delete_playlist(
        self, playlist_id: str, *, dry_run: bool = False, yes: bool = False
    ) -> dict[str, Any]:
        self._require_write(yes, dry_run, "удаления плейлиста")
        self.quota.check(COST["playlists.delete"])
        data = self.client.delete("playlists", params={"id": playlist_id}, dry_run=dry_run)
        if dry_run:
            return data if isinstance(data, dict) else {"dry_run": True}
        self.quota.consume("playlists.delete", COST["playlists.delete"])
        return {"ok": True, "playlist_id": playlist_id}

    def add_to_playlist(
        self,
        playlist_id: str,
        video_id: str,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        self._require_write(yes, dry_run, "добавления в плейлист")
        self.quota.check(COST["playlistItems.insert"])
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        data = self.client.post(
            "playlistItems",
            params={"part": "snippet"},
            json_body=body,
            dry_run=dry_run,
        )
        if dry_run:
            return data
        self.quota.consume("playlistItems.insert", COST["playlistItems.insert"])
        return data

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
        self._require_write(yes, dry_run, "ответа на комментарий")
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

    def moderate_comment(
        self,
        comment_id: str,
        moderation_status: str,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        """moderation_status: heldForReview | published | rejected."""
        self._require_write(yes, dry_run, "модерации комментария")
        self.quota.check(COST["comments.setModerationStatus"])
        data = self.client.post(
            "comments/setModerationStatus",
            params={"id": comment_id, "moderationStatus": moderation_status},
            dry_run=dry_run,
        )
        if dry_run:
            return data if isinstance(data, dict) else {"dry_run": True}
        self.quota.consume(
            "comments.setModerationStatus", COST["comments.setModerationStatus"]
        )
        return {"ok": True, "comment_id": comment_id, "status": moderation_status}

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

    def upload_caption(
        self,
        video_id: str,
        file_path: Path | str,
        language: str = "ru",
        name: str = "",
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        """Upload caption track (SBV/SRT/VTT etc.) via resumable-like binary POST."""
        self._require_write(yes, dry_run, "загрузки субтитров")
        path = Path(file_path)
        if not path.is_file():
            raise ClientError(f"Файл не найден: {path}", code="NOT_FOUND")
        if dry_run:
            return {"dry_run": True, "video_id": video_id, "file": str(path)}
        self.quota.check(COST["captions.insert"])
        metadata = {
            "snippet": {
                "videoId": video_id,
                "language": language,
                "name": name or language,
            }
        }
        # multipart upload to captions endpoint
        url = "https://www.googleapis.com/upload/youtube/v3/captions"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=120.0) as http:
            files = {
                "metadata": (
                    "metadata.json",
                    __import__("json").dumps(metadata),
                    "application/json",
                ),
                "media": (path.name, path.read_bytes(), "application/octet-stream"),
            }
            resp = http.post(
                url,
                params={"part": "snippet", "uploadType": "multipart"},
                headers=headers,
                files=files,
            )
            if resp.status_code >= 400:
                raise ClientError(
                    f"captions.insert failed: {resp.status_code} {resp.text[:300]}",
                    code="CAPTION_UPLOAD_FAILED",
                    retryable=True,
                )
            self.quota.consume("captions.insert", COST["captions.insert"])
            return resp.json()

    def set_thumbnail(
        self,
        video_id: str,
        image_path: Path | str,
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> dict[str, Any]:
        self._require_yes(yes, dry_run, "установки обложки")
        path = Path(image_path)
        if not path.is_file():
            raise ClientError(f"Файл не найден: {path}", code="NOT_FOUND")
        if dry_run:
            return {"dry_run": True, "video_id": video_id, "file": str(path)}
        # Токен проверяется ДО обращения к API за проверкой канала:
        # иначе пустой токен даёт невнятный AUTH_REQUIRED вместо NOT_AUTHENTICATED.
        require_access_token(access_token)
        self._verify_expected_channel()
        self.quota.check(COST["thumbnails.set"])
        url = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=60.0) as http:
            resp = http.post(
                url,
                params={"videoId": video_id},
                headers=headers,
                content=path.read_bytes(),
            )
            if resp.status_code >= 400:
                raise ClientError(
                    f"thumbnails.set failed: {resp.status_code} {resp.text[:300]}",
                    code="THUMBNAIL_FAILED",
                    retryable=True,
                )
            self.quota.consume("thumbnails.set", COST["thumbnails.set"])
            return resp.json() if resp.content else {"ok": True}

    def search(
        self, query: str, *, max_results: int = 10, dry_run: bool = False
    ) -> dict[str, Any]:
        self.quota.check(COST["search.list"])
        data = self.client.get(
            "search",
            params={
                "part": "snippet",
                "q": query,
                "type": "video",
                "maxResults": max_results,
            },
            dry_run=dry_run,
        )
        if not dry_run:
            self.quota.consume("search.list", COST["search.list"])
        return data

    def claims_unsupported(self) -> dict[str, str]:
        return {
            "status": "UNSUPPORTED",
            "message": "Claims / Content ID через публичный Data API не поддерживаются",
        }
