"""publishAt ставится и на приватный ролик с непустым snippet.publishedAt.

Программа отказывалась планировать, потому что считала непустой
``snippet.publishedAt`` признаком опубликованного ролика. Это неверно:
YouTube выставляет publishedAt уже при загрузке, поэтому он заполнен у всех
роликов канала.

Прямое доказательство с канала (28.09.2026): у приватных роликов
``_R3Kw1gFW60`` и ``gNB7R-ldu40`` заполнены и publishedAt, и publishAt.
Значит отложенная публикация для приватных роликов с publishedAt работает.

Реальные признаки «планировать нельзя»:
- ролик не приватный;
- у ролика уже стоит publishAt.
"""

from __future__ import annotations

from aiyoutubehands.models.youtube import VideoResource


def _video(
    *,
    privacy: str = "private",
    published_at: str | None = "2026-09-28T13:48:20Z",
    publish_at: str | None = None,
    views: int | None = None,
) -> VideoResource:
    raw: dict = {}
    if views is not None:
        raw["statistics"] = {"viewCount": str(views)}
    return VideoResource.from_api(
        {
            "id": "vid00000001",
            "snippet": {"title": "Тема", "publishedAt": published_at},
            "status": {"privacyStatus": privacy, "publishAt": publish_at},
            "contentDetails": {"duration": "PT34S"},
            "statistics": raw.get("statistics", {}),
        }
    )


def test_private_video_with_upload_date_can_be_scheduled() -> None:
    """Главный случай: свежая приватная загрузка — планировать можно."""
    v = _video(privacy="private", published_at="2026-09-28T13:48:20Z", publish_at=None)

    assert v.never_published() is True


def test_already_scheduled_video_is_not_reschedulable() -> None:
    """Если publishAt уже стоит — повторно не планируем."""
    v = _video(privacy="private", publish_at="2026-09-28T15:00:00Z")

    assert v.never_published() is False


def test_public_video_is_not_schedulable() -> None:
    """Опубликованный ролик расписанием не трогаем."""
    v = _video(privacy="public", publish_at=None)

    assert v.never_published() is False


def test_unlisted_video_is_not_schedulable() -> None:
    """Доступ по ссылке — тоже не планируем."""
    v = _video(privacy="unlisted", publish_at=None)

    assert v.never_published() is False


def test_video_with_views_is_not_schedulable() -> None:
    """Приватный ролик с просмотрами почти наверняка уже публиковался."""
    v = _video(privacy="private", publish_at=None, views=120)

    assert v.never_published() is False
