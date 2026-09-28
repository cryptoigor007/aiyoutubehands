"""Ролики, загруженные пайплайном, не должны считаться «уже оформленными».

Пайплайн Shorts Maker кладёт на канал ролик с рабочим именем вида
«Ш43 Почему люди боятся успеха final» и четырьмя тегами по умолчанию.
YouTube при этом сам генерирует ``maxres`` в ``snippet.thumbnails``.

Из-за этого набиралось 3 из 5 сигналов «уже оформлено» и программа
отказывалась обрабатывать ровно те ролики, которые ждут оформления.

Второй дефект: сопоставление не использовало номер «ШNN», хотя он есть и в
имени папки, и в названии ролика — это самый точный идентификатор.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.shorts_maker.folder_scanner import scan_folder
from aiyoutubehands.shorts_maker.matcher import is_already_styled, match_candidates

if TYPE_CHECKING:
    from pathlib import Path

RAW_TITLE = "Ш43 Почему люди боятся успеха final"
DEFAULT_TAGS = [
    "психология отношений",
    "современное общество",
    "психология личности",
    "точка наблюдения",
]
# YouTube отдаёт maxres для обычного вертикального ролика сам
AUTO_THUMBS = {
    "default": {"url": "https://i.ytimg.com/vi/x/default.jpg", "width": 120, "height": 90},
    "medium": {"url": "https://i.ytimg.com/vi/x/mqdefault.jpg", "width": 320, "height": 180},
    "high": {"url": "https://i.ytimg.com/vi/x/hqdefault.jpg", "width": 480, "height": 360},
    "standard": {"url": "https://i.ytimg.com/vi/x/sddefault.jpg", "width": 640, "height": 480},
    "maxres": {"url": "https://i.ytimg.com/vi/x/maxresdefault.jpg", "width": 1280, "height": 720},
}


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _video(
    vid: str,
    title: str,
    *,
    description: str = "",
    tags: list[str] | None = None,
    duration: str = "PT34S",
    thumbs: dict | None = None,
    published_at: str | None = None,
) -> VideoResource:
    return VideoResource.from_api(
        {
            "id": vid,
            "snippet": {
                "title": title,
                "description": description,
                "tags": DEFAULT_TAGS if tags is None else tags,
                "thumbnails": AUTO_THUMBS if thumbs is None else thumbs,
                "publishedAt": published_at or _now_iso(),
            },
            "status": {"privacyStatus": "private"},
            "contentDetails": {"duration": duration},
        }
    )


def _folder(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / f"{name}_titles.txt").write_text("Заголовок: Т\nОписание: О.\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# 1. «Уже оформлено»: рабочее имя пайплайна — не признак оформления
# ---------------------------------------------------------------------------


def test_raw_pipeline_name_is_not_styled() -> None:
    """Сырое имя + авто-обложка + теги по умолчанию ≠ оформленный ролик."""
    v = _video("2dYDNL3hCqA", RAW_TITLE)

    assert is_already_styled(v) is False


def test_real_styled_video_is_still_detected() -> None:
    """Настоящее оформление по-прежнему распознаётся (защита не сломана)."""
    v = _video(
        "good0000001",
        "Почему люди боятся успеха?",
        description="Большое осмысленное описание ролика, больше пятидесяти символов точно.",
        tags=["психология", "успех", "страх", "саморазвитие"],
    )

    assert is_already_styled(v) is True


def test_processed_marker_still_wins() -> None:
    """Маркер #ayh_processed остаётся безусловным признаком."""
    v = _video("marked00001", RAW_TITLE, description="текст #ayh_processed")

    assert is_already_styled(v) is True


# ---------------------------------------------------------------------------
# 2. Сопоставление по номеру «ШNN»
# ---------------------------------------------------------------------------


def test_folder_matches_video_by_number(tmp_path: Path) -> None:
    """Папка «ш44 …» находит ролик «Ш44 … final» по номеру."""
    folder = _folder(tmp_path, "ш44 Почему мы держимся за то, что давно умерло")
    video = _video("qEilYDsp25M", "Ш44 Почему мы держимся за то, что давно умерло final")

    results = match_candidates([scan_folder(folder)], [video], max_age_days=14)

    assert len(results) == 1
    assert results[0].video is not None
    assert results[0].video.id == "qEilYDsp25M"
    assert results[0].method == "prefix"


def test_number_does_not_match_other_number(tmp_path: Path) -> None:
    """Чужой номер не подставляется."""
    folder = _folder(tmp_path, "ш44 Тема")
    video = _video("other000001", "Ш99 Тема final", duration="PT34S")

    results = match_candidates([scan_folder(folder)], [video], max_age_days=14)

    assert results[0].video is None


def test_ambiguous_number_is_skipped(tmp_path: Path) -> None:
    """Два ролика с одним номером — не угадываем."""
    folder = _folder(tmp_path, "ш44 Тема")
    videos = [
        _video("dup00000001", "Ш44 Тема final"),
        _video("dup00000002", "Ш44 Тема final copy"),
    ]

    results = match_candidates([scan_folder(folder)], videos, max_age_days=14)

    assert results[0].video is None
    assert "ш44" in results[0].reason or "неоднозначн" in results[0].reason


def test_number_match_beats_duration_ambiguity(tmp_path: Path) -> None:
    """Раньше здесь была «неоднозначная duration» — номер решает точнее."""
    folder = _folder(tmp_path, "ш43 Почему люди боятся успеха")
    videos = [
        _video("a4300000001", "Ш43 Почему люди боятся успеха final", duration="PT38S"),
        _video("b4400000001", "Ш44 Что-то другое final", duration="PT38S"),
        _video("c4500000001", "Ш45 Ещё одно final", duration="PT38S"),
    ]

    results = match_candidates([scan_folder(folder)], videos, max_age_days=14)

    assert results[0].video is not None
    assert results[0].video.id == "a4300000001"
