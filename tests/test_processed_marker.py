"""Служебный маркер ``#ayh_processed`` в описании можно не писать.

Маркер виден зрителю: он попадает в описание ролика и выглядит как мусор.
Защита от повторной обработки дублируется локальным реестром ``processed.db``
и набором признаков «уже оформлено», поэтому запись маркера сделана
отключаемой.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from click.testing import CliRunner

import aiyoutubehands.shorts_maker.processor as processor_mod
from aiyoutubehands.main import cli
from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.shorts_maker.folder_scanner import FolderCandidate
from aiyoutubehands.shorts_maker.plan import PlanItem, ProcessPlan
from aiyoutubehands.shorts_maker.processor import apply_plan

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

MSK = ZoneInfo("Europe/Moscow")
BODY = "Нормальное описание ролика без мусора."


class _RecYT:
    """Запоминает описания, которые ушли в videos.update."""

    def __init__(self, tmp_path: Path) -> None:
        self.quota = QuotaEngine(db_path=tmp_path / "q.db")
        self.descriptions: list[str] = []

    def update_video(
        self,
        video_id: str,
        snippet: object = None,
        status: object = None,
        *,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        self.descriptions.append(str(getattr(snippet, "description", "")))

    def set_thumbnail(
        self,
        video_id: str,
        image_path: object,
        *,
        access_token: str,
        dry_run: bool = False,
        yes: bool = False,
    ) -> None:
        return None


def _item(tmp_path: Path) -> PlanItem:
    video = VideoResource.from_api(
        {
            "id": "vid00000001",
            "snippet": {
                "title": "Ш43 Тема final",
                "channelId": "UC_x",
                "publishedAt": "2026-09-28T13:00:00Z",
            },
            "status": {"privacyStatus": "private"},
        }
    )
    return PlanItem(
        index=1,
        folder=FolderCandidate(path=tmp_path, folder_name="Ш43 Тема", clean_title="Тема"),
        video=video,
        match_method="prefix",
        new_title="Тема",
        new_description=BODY,
        new_tags=["психология"],
        thumbnail_path=None,
        publish_at=None,
        status="к обработке",
        estimated_quota=50,
    )


def _plan(tmp_path: Path) -> ProcessPlan:
    return ProcessPlan(
        created_at=datetime.now(MSK),
        root_path=tmp_path,
        items=[_item(tmp_path)],
        quota_projection={},
        confirm_phrase="подтверждаю план от 01.01.2026 #abc",
    )


def _apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs) -> _RecYT:
    monkeypatch.setattr(processor_mod, "_run_log_path", lambda: tmp_path / "run.log")
    yt = _RecYT(tmp_path)
    apply_plan(
        _plan(tmp_path),
        yt,
        access_token="fake",
        dry_run=False,
        yes=True,
        **kwargs,
    )
    return yt


def test_marker_written_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Прежнее поведение сохраняется: по умолчанию маркер пишется."""
    yt = _apply(tmp_path, monkeypatch)

    assert "#ayh_processed" in yt.descriptions[0]


def test_no_marker_leaves_description_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """С mark_processed=False описание уходит ровно таким, как в плане."""
    yt = _apply(tmp_path, monkeypatch, mark_processed=False)

    assert yt.descriptions[0] == BODY
    assert "#ayh_processed" not in yt.descriptions[0]


def test_apply_has_no_marker_option() -> None:
    """У команды apply должен быть флаг --no-marker."""
    result = CliRunner().invoke(cli, ["process", "apply", "--help"])

    assert result.exit_code == 0, result.output
    assert "--no-marker" in result.output
