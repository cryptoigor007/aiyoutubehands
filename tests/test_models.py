"""Tests for YouTube models."""

from __future__ import annotations

from aiyoutubehands.models.youtube import (
    VideoSnippet,
    VideoStatus,
    VideoResource,
    ChannelResource,
    PlaylistResource,
)


def test_video_snippet() -> None:
    s = VideoSnippet(title="Test", description="Desc", tags=["a", "b"])
    assert s.title == "Test"
    assert s.tags == ["a", "b"]
    d = s.to_api()
    assert d["title"] == "Test"
    assert d["tags"] == ["a", "b"]


def test_video_resource_from_api() -> None:
    raw = {
        "id": "vid123",
        "snippet": {"title": "T", "description": "D", "channelId": "UC1"},
        "status": {"privacyStatus": "private", "publishAt": None},
    }
    v = VideoResource.from_api(raw)
    assert v.id == "vid123"
    assert v.snippet.title == "T"
    assert v.status.privacy_status == "private"


def test_channel_resource() -> None:
    raw = {"id": "UC_x", "snippet": {"title": "My Channel"}, "statistics": {"subscriberCount": "10"}}
    c = ChannelResource.from_api(raw)
    assert c.id == "UC_x"
    assert c.title == "My Channel"
