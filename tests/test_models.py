"""Tests for YouTube models."""

from __future__ import annotations

from aiyoutubehands.models.youtube import (
    ChannelResource,
    VideoResource,
    VideoSnippet,
    VideoStatus,
)


def test_video_snippet() -> None:
    s = VideoSnippet(title="Test", description="Desc", tags=["a", "b"])
    assert s.title == "Test"
    assert s.tags == ["a", "b"]
    d = s.to_api()
    assert d["title"] == "Test"
    assert d["tags"] == ["a", "b"]


def test_snippet_omits_unset_description() -> None:
    """Смена заголовка не должна затирать описание живого видео.

    Регресс: to_api() всегда отправляла description (по умолчанию ""), поэтому
    videos.update с part=snippet очищал описание, которого никто не касался.
    """
    d = VideoSnippet(title="Новый заголовок").to_api()
    assert "description" not in d


def test_snippet_sends_explicitly_empty_description() -> None:
    """Явно пустое описание отправляется — сентинел отличает «не задано» от «очистить»."""
    assert VideoSnippet(title="T", description="").to_api()["description"] == ""


def test_status_omits_made_for_kids_when_unset() -> None:
    """Публикация/расписание не должны молча сбрасывать флаг COPPA.

    Регресс: to_api() всегда отправляла selfDeclaredMadeForKids=False,
    поэтому любой videos.update со status снимал self-declared «для детей».
    """
    d = VideoStatus(privacy_status="private").to_api()
    assert "selfDeclaredMadeForKids" not in d


def test_status_sends_explicitly_set_made_for_kids() -> None:
    """Явно заданный флаг по-прежнему уходит в API."""
    d = VideoStatus(privacy_status="private", self_declared_made_for_kids=True).to_api()
    assert d["selfDeclaredMadeForKids"] is True


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
    raw = {
        "id": "UC_x",
        "snippet": {"title": "My Channel"},
        "statistics": {"subscriberCount": "10"},
    }
    c = ChannelResource.from_api(raw)
    assert c.id == "UC_x"
    assert c.title == "My Channel"


def test_comment_and_caption() -> None:
    from aiyoutubehands.models.youtube import CaptionResource, CommentResource

    c = CommentResource.from_api(
        {
            "id": "c1",
            "snippet": {
                "topLevelComment": {
                    "snippet": {"authorDisplayName": "A", "textOriginal": "Hi", "videoId": "v"}
                }
            },
        }
    )
    assert c.author == "A"
    cap = CaptionResource.from_api(
        {"id": "x", "snippet": {"videoId": "v", "language": "ru", "name": "RU"}}
    )
    assert cap.language == "ru"


def test_duration_seconds() -> None:
    from aiyoutubehands.models.youtube import VideoContentDetails

    assert VideoContentDetails(duration="PT45S").duration_seconds() == 45
    assert VideoContentDetails(duration="PT1M30S").duration_seconds() == 90
    assert VideoContentDetails(duration="PT1H2M3S").duration_seconds() == 3723
    assert VideoContentDetails(duration="").duration_seconds() is None
    assert VideoContentDetails(duration="P1D").duration_seconds() is None


def test_video_is_short_and_never_published() -> None:
    raw = {
        "id": "s1",
        "snippet": {"title": "Short", "publishedAt": ""},
        "status": {"privacyStatus": "private"},
        "contentDetails": {"duration": "PT58S"},
        "processingDetails": {"processingStatus": "succeeded"},
    }
    v = VideoResource.from_api(raw)
    assert v.is_short() is True
    assert v.never_published() is True
    assert v.processing_details.processing_status == "succeeded"

    raw2 = {
        "id": "s2",
        "snippet": {"title": "Long", "publishedAt": "2026-01-01T00:00:00Z"},
        "status": {"privacyStatus": "public"},
        "contentDetails": {"duration": "PT5M"},
    }
    v2 = VideoResource.from_api(raw2)
    assert v2.is_short() is False
    assert v2.never_published() is False


def test_has_custom_thumbnail() -> None:
    v = VideoResource.from_api(
        {
            "id": "t1",
            "snippet": {
                "title": "T",
                "thumbnails": {
                    "maxres": {"url": "https://example.com/max.jpg", "width": 1280, "height": 720}
                },
            },
        }
    )
    assert v.has_custom_thumbnail() is True

    v2 = VideoResource.from_api(
        {
            "id": "t2",
            "snippet": {
                "title": "T",
                "thumbnails": {
                    "default": {"url": "https://example.com/d.jpg", "width": 120, "height": 90}
                },
            },
        }
    )
    assert v2.has_custom_thumbnail() is False
