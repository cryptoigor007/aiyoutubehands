"""Resumable YouTube video upload."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoSnippet, VideoStatus

if TYPE_CHECKING:
    from aiyoutubehands.quota import QuotaEngine

log = get_logger(__name__)

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
COST_INSERT = 1600


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
    # youtube videos.insert notifySubscribers; по умолчанию YouTube = true
    notify_subscribers: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.file_path),
            "size": self.size,
            "sha256": self.sha256,
            "title": self.snippet.title,
            "privacy": self.status.privacy_status,
            "dry_run": self.dry_run,
            "notify_subscribers": self.notify_subscribers,
        }


def prepare_upload(
    file_path: Path | str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy: str = "private",
    publish_at: str | None = None,
    dry_run: bool = True,
    notify_subscribers: bool = True,
) -> UploadPlan:
    path = Path(file_path)
    if not path.is_file():
        raise UploadError(f"Файл не найден: {path}", code="FILE_NOT_FOUND")
    size = path.stat().st_size
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return UploadPlan(
        file_path=path,
        size=size,
        sha256=h.hexdigest(),
        snippet=VideoSnippet(title=title, description=description, tags=tags or []),
        status=VideoStatus(privacy_status=privacy, publish_at=publish_at),
        dry_run=dry_run,
        notify_subscribers=notify_subscribers,
    )


def execute_upload_dry_run(plan: UploadPlan) -> dict[str, Any]:
    return {
        "ok": True,
        "dry_run": True,
        "message": "Загрузка не выполнена (dry-run)",
        "plan": plan.to_dict(),
        "video_id": None,
    }


def execute_resumable_upload(
    plan: UploadPlan,
    access_token: str,
    quota: QuotaEngine | None = None,
    *,
    yes: bool = False,
    chunk_size: int = 256 * 1024 * 10,
) -> dict[str, Any]:
    """Real resumable upload to YouTube. Requires --yes and non-dry-run plan."""
    if plan.dry_run:
        return execute_upload_dry_run(plan)
    if not yes:
        raise UploadError(
            "Реальная загрузка требует --yes",
            code="CONFIRM_REQUIRED",
            action="Передайте --yes",
        )
    if not access_token:
        raise UploadError(
            "Нет access_token — авторизация не выполнена",
            code="NOT_AUTHENTICATED",
            action="Выполните: ayh auth login",
        )
    if quota is not None:
        quota.check(COST_INSERT)

    metadata = {
        "snippet": plan.snippet.to_api(),
        "status": plan.status.to_api(),
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(plan.size),
        "X-Upload-Content-Type": "application/octet-stream",
    }
    params = {
        "uploadType": "resumable",
        "part": "snippet,status",
        "notifySubscribers": "true" if plan.notify_subscribers else "false",
    }

    with httpx.Client(timeout=120.0, trust_env=False) as client:
        init = client.post(UPLOAD_URL, params=params, headers=headers, json=metadata)
        if init.status_code not in (200, 201):
            raise UploadError(
                f"Не удалось начать resumable upload: {init.status_code} {init.text[:300]}",
                code="UPLOAD_INIT_FAILED",
                retryable=True,
            )
        session_url = init.headers.get("Location")
        if not session_url:
            raise UploadError("Нет Location для resumable session", code="UPLOAD_NO_SESSION")

        sent = 0
        with plan.file_path.open("rb") as f:
            while sent < plan.size:
                # Читаем ровно с той позиции, которую подтвердил сервер:
                # после 308 с Range позиция может отличаться от прочитанной.
                f.seek(sent)
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                start = sent
                end = sent + len(chunk) - 1
                put_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Length": str(len(chunk)),
                    "Content-Type": "application/octet-stream",
                    "Content-Range": f"bytes {start}-{end}/{plan.size}",
                }
                put = client.put(session_url, headers=put_headers, content=chunk)
                if put.status_code in (200, 201):
                    # Сервер подтвердил приём. Если это меньше заявленного
                    # размера — данные потеряны, а не «загружено успешно».
                    if end + 1 != plan.size:
                        raise UploadError(
                            f"Сервер принял {end + 1} из {plan.size} байт",
                            code="UPLOAD_INCOMPLETE",
                            retryable=True,
                        )
                    try:
                        data = put.json()
                    except ValueError as exc:
                        raise UploadError(
                            "Ответ загрузки не является JSON",
                            code="UPLOAD_BAD_RESPONSE",
                            retryable=True,
                        ) from exc
                    video_id = str(data.get("id") or "")
                    if quota is not None:
                        quota.consume("videos.insert", COST_INSERT)
                    log.info("upload_complete", video_id=video_id)
                    return {
                        "ok": True,
                        "dry_run": False,
                        "video_id": video_id,
                        "plan": plan.to_dict(),
                        "raw": data,
                    }
                if put.status_code == 308:
                    # Сколько байт сервер реально принял, он сообщает в Range.
                    m = re.fullmatch(r"bytes=(\d+)-(\d+)", (put.headers.get("Range") or "").strip())
                    sent = int(m.group(2)) + 1 if m else end + 1
                    continue
                raise UploadError(
                    f"Ошибка загрузки chunk: {put.status_code} {put.text[:300]}",
                    code="UPLOAD_CHUNK_FAILED",
                    retryable=True,
                )

    raise UploadError("Загрузка не завершилась", code="UPLOAD_INCOMPLETE")
