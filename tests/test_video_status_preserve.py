"""videos.update сбрасывает поля статуса, которых нет в запросе.

YouTube заменяет весь блок ``status`` целиком: если не передать поле, оно
вернётся к значению по умолчанию. Программа передавала только
``privacyStatus`` и ``publishAt``, из-за чего у роликов слетели
``embeddable`` и ``publicStatsViewable`` (оба стали False).

Симптом на канале: у шести оформленных роликов плеер в Студии показывал
серую заглушку — встроенное воспроизведение было выключено.

Правило: собирая новый статус, переносим в него текущие значения полей,
которые не собираемся менять.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiyoutubehands.models.youtube import VideoResource, VideoStatus

if TYPE_CHECKING:
    from pathlib import Path


def test_to_api_sends_embeddable_and_stats() -> None:
    """Оба поля обязаны уходить в запрос, иначе YouTube их сбросит."""
    payload = VideoStatus(
        privacy_status="private",
        publish_at="2026-09-30T09:00:00Z",
        embeddable=True,
        public_stats_viewable=True,
    ).to_api()

    assert payload["embeddable"] is True
    assert payload["publicStatsViewable"] is True
    assert payload["privacyStatus"] == "private"
    assert payload["publishAt"] == "2026-09-30T09:00:00Z"


def test_from_api_reads_current_values() -> None:
    """Текущие значения читаются, чтобы их можно было перенести дальше."""
    st = VideoStatus.from_api(
        {"privacyStatus": "private", "embeddable": True, "publicStatsViewable": False}
    )

    assert st.embeddable is True
    assert st.public_stats_viewable is False


def test_from_api_defaults_follow_youtube() -> None:
    """Если поля нет в ответе — берём значение по умолчанию YouTube (True)."""
    st = VideoStatus.from_api({"privacyStatus": "public"})

    assert st.embeddable is True
    assert st.public_stats_viewable is True


def _video() -> VideoResource:
    return VideoResource.from_api(
        {
            "id": "vid00000001",
            "snippet": {"title": "Тема", "channelId": "UC_x"},
            "status": {
                "privacyStatus": "private",
                "embeddable": True,
                "publicStatsViewable": True,
            },
        }
    )


def test_status_for_update_preserves_untouched_fields() -> None:
    """Новый статус с publishAt не должен терять embeddable и показ статистики."""
    from aiyoutubehands.shorts_maker.processor import build_status_for_update

    st = build_status_for_update(_video(), "2026-09-30T09:00:00Z")

    assert st is not None
    assert st.publish_at == "2026-09-30T09:00:00Z"
    assert st.embeddable is True, "embeddable слетал и ломал превью в Студии"
    assert st.public_stats_viewable is True
    payload = st.to_api()
    assert payload["embeddable"] is True
    assert payload["publicStatsViewable"] is True


def test_status_for_update_none_when_not_private() -> None:
    """Опубликованные ролики расписанием не трогаем."""
    from aiyoutubehands.shorts_maker.processor import build_status_for_update

    v = _video()
    v.status.privacy_status = "public"

    assert build_status_for_update(v, "2026-09-30T09:00:00Z") is None


def test_status_for_update_none_without_publish_at() -> None:
    """Без расписания статус не меняем вовсе — меньше риска что-то сбросить."""
    from aiyoutubehands.shorts_maker.processor import build_status_for_update

    assert build_status_for_update(_video(), None) is None


def test_fix_helper_restores_fields(tmp_path: Path) -> None:
    """Хелпер восстановления возвращает True для сломанного ролика."""
    from aiyoutubehands.shorts_maker.processor import needs_status_repair

    assert needs_status_repair(_video()) is False

    broken = _video()
    broken.status.embeddable = False
    assert needs_status_repair(broken) is True
