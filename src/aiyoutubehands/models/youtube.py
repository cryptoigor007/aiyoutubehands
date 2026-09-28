"""YouTube API resource models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VideoSnippet:
    title: str = ""
    # None = «поле не задано» и НЕ отправляется; "" = «очистить описание».
    # Раньше значение по умолчанию было "", и это затирало описание живого видео.
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    category_id: str = "22"
    channel_id: str = ""
    published_at: str = ""
    thumbnails: dict[str, Any] = field(default_factory=dict)

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "categoryId": self.category_id,
        }
        if self.description is not None:
            d["description"] = self.description
        if self.tags:
            d["tags"] = self.tags
        return d

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoSnippet:
        return cls(
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            tags=list(data.get("tags") or []),
            category_id=str(data.get("categoryId") or "22"),
            channel_id=str(data.get("channelId") or ""),
            published_at=str(data.get("publishedAt") or ""),
            thumbnails=dict(data.get("thumbnails") or {}),
        )


@dataclass
class VideoStatus:
    privacy_status: str = "private"
    publish_at: str | None = None
    # None = «не задано» и НЕ отправляется; True/False — явная установка.
    # Раньше по умолчанию был False, и любой update со status снимал COPPA-флаг.
    self_declared_made_for_kids: bool | None = None

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "privacyStatus": self.privacy_status,
        }
        if self.self_declared_made_for_kids is not None:
            d["selfDeclaredMadeForKids"] = self.self_declared_made_for_kids
        if self.publish_at:
            d["publishAt"] = self.publish_at
        return d

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoStatus:
        return cls(
            privacy_status=str(data.get("privacyStatus") or "private"),
            publish_at=data.get("publishAt"),
            self_declared_made_for_kids=bool(data.get("selfDeclaredMadeForKids", False)),
        )


@dataclass
class VideoContentDetails:
    duration: str = ""  # ISO 8601, e.g. PT45S
    definition: str = ""
    dimension: str = ""  # 2d / 3d
    projection: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoContentDetails:
        return cls(
            duration=str(data.get("duration") or ""),
            definition=str(data.get("definition") or ""),
            dimension=str(data.get("dimension") or ""),
            projection=str(data.get("projection") or ""),
        )

    def duration_seconds(self) -> int | None:
        """Parse ISO 8601 duration (PT#H#M#S) to total seconds."""
        if not self.duration or not self.duration.startswith("PT"):
            return None
        import re

        m = re.fullmatch(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
            self.duration,
        )
        if not m:
            return None
        h, mi, s = (int(x) if x else 0 for x in m.groups())
        return h * 3600 + mi * 60 + s


@dataclass
class VideoProcessingDetails:
    processing_status: str = ""  # succeeded / processing / failed / terminated

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoProcessingDetails:
        return cls(processing_status=str(data.get("processingStatus") or ""))


@dataclass
class VideoResource:
    id: str = ""
    snippet: VideoSnippet = field(default_factory=VideoSnippet)
    status: VideoStatus = field(default_factory=VideoStatus)
    content_details: VideoContentDetails = field(default_factory=VideoContentDetails)
    processing_details: VideoProcessingDetails = field(default_factory=VideoProcessingDetails)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoResource:
        return cls(
            id=str(data.get("id") or ""),
            snippet=VideoSnippet.from_api(data.get("snippet") or {}),
            status=VideoStatus.from_api(data.get("status") or {}),
            content_details=VideoContentDetails.from_api(data.get("contentDetails") or {}),
            processing_details=VideoProcessingDetails.from_api(data.get("processingDetails") or {}),
            raw=data,
        )

    def has_custom_thumbnail(self) -> bool:
        """True if non-default thumbnail is present (maxres or high with reasonable size)."""
        thumbs = self.snippet.thumbnails or {}
        for key in ("maxres", "standard", "high"):
            t = thumbs.get(key)
            if isinstance(t, dict) and t.get("url"):
                # Default auto-generated often lack maxres; presence of maxres is strong signal
                if key == "maxres":
                    return True
                w = int(t.get("width") or 0)
                h = int(t.get("height") or 0)
                if w >= 640 and h >= 360:
                    return True
        return False

    def is_short(self) -> bool:
        """Duration ≤ 60s (Shorts heuristic)."""
        sec = self.content_details.duration_seconds()
        return sec is not None and sec <= 60

    def never_published(self) -> bool:
        """Heuristic: schedule publishAt may still be allowed.

        YouTube only allows status.publishAt when privacy is private and the
        video has never been made public/unlisted. A non-empty snippet.publishedAt
        usually means the platform already treated it as published — API then
        returns invalidPublishAt. Fresh private inserts without publishedAt
        return True; typical already-uploaded private videos return False.
        """
        if self.status.privacy_status != "private":
            return False
        return not bool(self.snippet.published_at)


@dataclass
class ChannelResource:
    id: str = ""
    title: str = ""
    description: str = ""
    subscriber_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ChannelResource:
        stats = data.get("statistics") or {}
        snippet = data.get("snippet") or {}
        return cls(
            id=str(data.get("id") or ""),
            title=str(snippet.get("title") or ""),
            description=str(snippet.get("description") or ""),
            subscriber_count=int(stats.get("subscriberCount") or 0),
            raw=data,
        )


@dataclass
class PlaylistResource:
    id: str = ""
    title: str = ""
    description: str = ""
    item_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PlaylistResource:
        snippet = data.get("snippet") or {}
        content = data.get("contentDetails") or {}
        return cls(
            id=str(data.get("id") or ""),
            title=str(snippet.get("title") or ""),
            description=str(snippet.get("description") or ""),
            item_count=int(content.get("itemCount") or 0),
            raw=data,
        )


@dataclass
class CommentResource:
    id: str = ""
    video_id: str = ""
    author: str = ""
    text: str = ""
    like_count: int = 0
    published_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CommentResource:
        snippet = data.get("snippet") or {}
        top = snippet.get("topLevelComment", {}).get("snippet") or snippet
        return cls(
            id=str(data.get("id") or ""),
            video_id=str(snippet.get("videoId") or top.get("videoId") or ""),
            author=str(top.get("authorDisplayName") or ""),
            text=str(top.get("textDisplay") or top.get("textOriginal") or ""),
            like_count=int(top.get("likeCount") or 0),
            published_at=str(top.get("publishedAt") or ""),
            raw=data,
        )


@dataclass
class CaptionResource:
    id: str = ""
    video_id: str = ""
    language: str = ""
    name: str = ""
    track_kind: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> CaptionResource:
        snippet = data.get("snippet") or {}
        return cls(
            id=str(data.get("id") or ""),
            video_id=str(snippet.get("videoId") or ""),
            language=str(snippet.get("language") or ""),
            name=str(snippet.get("name") or ""),
            track_kind=str(snippet.get("trackKind") or ""),
            raw=data,
        )
