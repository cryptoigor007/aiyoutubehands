"""Resumable upload (dry-run / structure only — no real upload without explicit permission)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoSnippet, VideoStatus

log = get_logger(__name__)


class UploadError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str = "UPLOAD_ERROR",
        action: str = "Проверьте файл и квоту",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable


@dataclass
class UploadPlan:
    file_path: Path
    size: int
    sha256: str
    snippet: VideoSnippet
    status: VideoStatus
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.file_path),
            "size": self.size,
            "sha256": self.sha256,
            "title": self.snippet.title,
            "privacy": self.status.privacy_status,
            "dry_run": self.dry_run,
        }


def prepare_upload(
    file_path: Path | str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    publish_at: str | None = None,
    dry_run: bool = True,
) -> UploadPlan:
    path = Path(file_path)
    if not path.is_file():
        raise UploadError(f"Файл не найден: {path}", code="FILE_NOT_FOUND")
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    snippet = VideoSnippet(title=title, description=description, tags=tags or [])
    status = VideoStatus(privacy_status=privacy, publish_at=publish_at)
    plan = UploadPlan(
        file_path=path,
        size=size,
        sha256=h.hexdigest(),
        snippet=snippet,
        status=status,
        dry_run=dry_run,
    )
    log.info("upload_prepared", file=str(path), size=size, dry_run=dry_run)
    return plan


def execute_upload_dry_run(plan: UploadPlan) -> dict[str, Any]:
    """Always dry-run unless explicitly overridden later with user permission."""
    if not plan.dry_run:
        raise UploadError(
            "Реальная загрузка запрещена без явного разрешения пользователя",
            code="UPLOAD_FORBIDDEN",
            action="Передайте «разрешаю smoke» / «делай реальный upload»",
        )
    return {
        "ok": True,
        "dry_run": True,
        "message": "Загрузка не выполнена (dry-run)",
        "plan": plan.to_dict(),
        "video_id": None,
    }
