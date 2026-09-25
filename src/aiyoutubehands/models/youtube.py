"""YouTube API resource models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class VideoSnippet:
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "22"
    channel_id: str = ""
    published_at: str = ""
    thumbnails: dict[str, Any] = field(default_factory=dict)

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "categoryId": self.category_id,
        }
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
    self_declared_made_for_kids: bool = False

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "privacyStatus": self.privacy_status,
            "selfDeclaredMadeForKids": self.self_declared_made_for_kids,
        }
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
class VideoResource:
    id: str = ""
    snippet: VideoSnippet = field(default_factory=VideoSnippet)
    status: VideoStatus = field(default_factory=VideoStatus)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> VideoResource:
        return cls(
            id=str(data.get("id") or ""),
            snippet=VideoSnippet.from_api(data.get("snippet") or {}),
            status=VideoStatus.from_api(data.get("status") or {}),
            raw=data,
        )


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
