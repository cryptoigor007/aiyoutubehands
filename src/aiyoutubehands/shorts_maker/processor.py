"""Apply approved process plan: update snippet/status, thumbnail, ledger, marker."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiyoutubehands.client import ClientError
from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoSnippet, VideoStatus
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.shorts_maker.ledger import MARKER, ProcessedLedger
from aiyoutubehands.shorts_maker.plan import PlanItem, ProcessPlan
from aiyoutubehands.youtube import YoutubeService

log = get_logger(__name__)

MSK = ZoneInfo("Europe/Moscow")
PAUSE_SEC = 0.75  # ban-safe gap between writes
MAX_DESCRIPTION = 5000  # жёсткий лимит YouTube для snippet.description


def _run_log_path() -> Path:
    from aiyoutubehands.config import get_state_dir

    state = get_state_dir()
    state.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(MSK).strftime("%Y%m%d_%H%M%S")
    return state / f"ayh_run_{stamp}.log"


class ProcessReport:
    def __init__(self) -> None:
        self.ok: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[str] = []
        self.quota_spent: int = 0
        self.log_path: Path | None = None

    def summary(self) -> str:
        lines = [
            f"Успешно: {len(self.ok)}",
            f"Ошибки: {len(self.failed)}",
            f"Пропущено: {len(self.skipped)}",
            f"Квота потрачена: {self.quota_spent}",
        ]
        if self.log_path:
            lines.append(f"Лог: {self.log_path}")
        for vid, err in self.failed:
            lines.append(f"  FAIL {vid}: {err}")
        return "\n".join(lines)


def apply_plan(
    plan: ProcessPlan,
    yt: YoutubeService,
    *,
    access_token: str,
    dry_run: bool = True,
    yes: bool = False,
    ledger: ProcessedLedger | None = None,
) -> ProcessReport:
    """Apply actionable items. Stops on first 403/429."""
    report = ProcessReport()
    log_path = _run_log_path()
    report.log_path = log_path
    run_id = log_path.stem
    # Hard rule: never mutate Shorts Maker source folders
    root = plan.root_path.resolve()
    lines: list[str] = [
        f"run={run_id}",
        f"root={plan.root_path}",
        f"dry_run={dry_run}",
        f"items={len(plan.actionable_items())}",
        "",
    ]

    if ledger is None:
        ledger = ProcessedLedger()

    for item in plan.actionable_items():
        assert item.video is not None
        vid = item.video.id
        # Local Shorts Maker files are read-only for process
        if item.thumbnail_path is not None:
            try:
                item.thumbnail_path.resolve().relative_to(root)
                # cover is under root — OK to READ only (set_thumbnail reads bytes)
            except ValueError:
                pass
        try:
            spent = _apply_one(
                item,
                yt,
                access_token=access_token,
                dry_run=dry_run,
                yes=yes,
                ledger=ledger,
                run_id=run_id,
            )
            report.ok.append(vid)
            report.quota_spent += spent
            lines.append(f"OK {vid} quota+={spent} title={item.new_title!r}")
        except ClientError as exc:
            report.failed.append((vid, f"{exc.code}: {exc.message}"))
            lines.append(f"FAIL {vid} {exc.code}: {exc.message}")
            # Immediate stop on quota / rate limit
            if exc.status_code in (403, 429) or exc.code in (
                "QUOTA_EXCEEDED",
                "RATE_LIMIT",
            ):
                lines.append("STOP: 403/429")
                log_path.write_text("\n".join(lines), encoding="utf-8")
                raise
            # Other errors: stop as well for safety (partial better than full damage)
            lines.append("STOP: first error")
            log_path.write_text("\n".join(lines), encoding="utf-8")
            raise
        except Exception as exc:  # noqa: BLE001
            report.failed.append((vid, str(exc)))
            lines.append(f"FAIL {vid} {exc}")
            lines.append("STOP: unexpected")
            log_path.write_text("\n".join(lines), encoding="utf-8")
            raise

        if not dry_run:
            time.sleep(PAUSE_SEC)

    log_path.write_text("\n".join(lines), encoding="utf-8")
    return report


def _apply_one(
    item: PlanItem,
    yt: YoutubeService,
    *,
    access_token: str,
    dry_run: bool,
    yes: bool,
    ledger: ProcessedLedger,
    run_id: str,
) -> int:
    """Returns estimated/actual quota units spent for this video."""
    assert item.video is not None
    vid = item.video.id
    spent = 0

    # Маркер добавляется В КОНЕЦ, поэтому место под него резервируется ДО обрезки.
    # Иначе при длинном описании он срезался вместе с хвостом и исчезал с видео.
    body = (item.new_description or "")[: MAX_DESCRIPTION - len(MARKER) - 2]
    desc = ProcessedLedger.append_marker(body)

    snippet = VideoSnippet(
        title=item.new_title[:100],
        description=desc[:MAX_DESCRIPTION],
        tags=item.new_tags,
        category_id="22",
        channel_id=item.video.snippet.channel_id,
    )

    status: VideoStatus | None = None
    if item.publish_at and item.video.status.privacy_status == "private":
        status = VideoStatus(
            privacy_status="private",
            publish_at=item.publish_at,
        )

    yt.quota.check(50)  # videos.update
    try:
        yt.update_video(vid, snippet=snippet, status=status, dry_run=dry_run, yes=yes)
    except ClientError as exc:
        # publishAt rejected (already published once) → retry without status only
        msg = (exc.message or "").lower()
        publish_at_rejected = status is not None and (
            "publishat" in msg
            or "invalidpublishat" in msg
            or "invalid publish" in msg
        )
        if publish_at_rejected:
            log.warning("publish_at_rejected_retry", video_id=vid, error=exc.message)
            yt.update_video(vid, snippet=snippet, status=None, dry_run=dry_run, yes=yes)
        else:
            raise
    if not dry_run:
        spent += 50

    if item.thumbnail_path and item.thumbnail_path.is_file():
        yt.quota.check(50)
        yt.set_thumbnail(
            vid,
            item.thumbnail_path,
            access_token=access_token,
            dry_run=dry_run,
            yes=yes,
        )
        if not dry_run:
            spent += 50

    if item.playlist_id:
        yt.quota.check(50)
        yt.add_to_playlist(
            item.playlist_id,
            vid,
            dry_run=dry_run,
            yes=yes,
        )
        if not dry_run:
            spent += 50

    if not dry_run:
        ledger.record(
            vid,
            folder_name=item.folder.folder_name,
            title=item.new_title,
            run_id=run_id,
        )

    return spent if not dry_run else item.estimated_quota
