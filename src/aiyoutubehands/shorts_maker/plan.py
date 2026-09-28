"""Build process plan table and quota projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.quota import QuotaEngine
from aiyoutubehands.shorts_maker.folder_scanner import FolderCandidate
from aiyoutubehands.shorts_maker.matcher import MatchResult
from aiyoutubehands.shorts_maker.metadata_extractor import ExtractedMeta, extract_metadata
from aiyoutubehands.shorts_maker.scheduler import format_slot_local, propose_slots
from aiyoutubehands.youtube import COST

log = get_logger(__name__)

MSK = ZoneInfo("Europe/Moscow")


@dataclass
class PlanItem:
    index: int
    folder: FolderCandidate
    video: VideoResource | None
    match_method: str
    new_title: str
    new_description: str
    new_tags: list[str]
    thumbnail_path: Path | None
    publish_at: str | None  # ISO UTC or None
    status: str  # «к обработке» | «пропуск: …» | «не сопоставлено»
    estimated_quota: int
    meta_notes: list[str] = field(default_factory=list)
    playlist_id: str | None = None  # optional; only after user confirms

    @property
    def actionable(self) -> bool:
        return self.status == "к обработке" and self.video is not None

    def current_title(self) -> str:
        if self.video:
            return self.video.snippet.title or self.folder.folder_name
        return self.folder.folder_name


@dataclass
class ProcessPlan:
    created_at: datetime
    root_path: Path
    items: list[PlanItem]
    quota_projection: dict
    confirm_phrase: str  # expected confirmation string

    def actionable_items(self) -> list[PlanItem]:
        return [i for i in self.items if i.actionable]

    def total_quota(self) -> int:
        return sum(i.estimated_quota for i in self.actionable_items())


def build_plan(
    matches: list[MatchResult],
    *,
    root_path: Path,
    quota: QuotaEngine | None = None,
    occupied_slots: set[str] | None = None,
    playlist_id: str | None = None,
    allow_ai: bool = False,
) -> ProcessPlan:
    """Build full plan from match results."""
    now = datetime.now(MSK)
    # Pre-extract meta and decide status
    metas: list[ExtractedMeta | None] = []
    videos_for_slots: list[VideoResource | None] = []
    statuses: list[str] = []

    for m in matches:
        # actionable only when reason is exactly "ok" (or ok with duration note prefix)
        actionable = m.reason == "ok" or m.reason.startswith("duration±1s") or m.reason.startswith(
            "единственное"
        )
        if m.video is None or not actionable or m.reason.startswith("дубликат"):
            metas.append(None)
            videos_for_slots.append(None)
            status = f"пропуск: {m.reason}"
            if m.notes:
                status += f" | {m.notes}"
            if m.related_video_ids and "неоднознач" in m.reason:
                status += f" [{', '.join(m.related_video_ids[:4])}]"
            statuses.append(status)
            continue
        meta = extract_metadata(m.candidate, allow_ai=allow_ai)
        metas.append(meta)
        videos_for_slots.append(m.video)
        statuses.append("к обработке")

    # Avoid colliding with publishAt already set on channel videos
    occupied = set(occupied_slots or [])
    for m in matches:
        if m.video and m.video.status.publish_at:
            occupied.add(str(m.video.status.publish_at))
    slots = propose_slots(videos_for_slots, occupied=occupied)

    items: list[PlanItem] = []
    ops: list[tuple[str, int]] = []

    for idx, (m, meta, slot, status) in enumerate(
        zip(matches, metas, slots, statuses, strict=True), start=1
    ):
        if status != "к обработке" or meta is None or m.video is None:
            items.append(
                PlanItem(
                    index=idx,
                    folder=m.candidate,
                    video=m.video,
                    match_method=m.method,
                    new_title=meta.title if meta else m.candidate.clean_title,
                    new_description=meta.description if meta else "",
                    new_tags=meta.tags if meta else [],
                    thumbnail_path=meta.thumbnail if meta else None,
                    publish_at=None,
                    status=status,
                    estimated_quota=0,
                    meta_notes=meta.source_notes if meta else [],
                )
            )
            continue

        # Quota: videos.update always; thumbnails.set if cover; playlistItems.insert if set
        est = COST["videos.update"]
        ops.append(("videos.update", COST["videos.update"]))
        if meta.thumbnail:
            est += COST["thumbnails.set"]
            ops.append(("thumbnails.set", COST["thumbnails.set"]))
        if playlist_id:
            est += COST["playlistItems.insert"]
            ops.append(("playlistItems.insert", COST["playlistItems.insert"]))

        # Schedule only for private videos that look never-published
        publish_at = slot if m.video.never_published() else None

        items.append(
            PlanItem(
                index=idx,
                folder=m.candidate,
                video=m.video,
                match_method=m.method,
                new_title=meta.title,
                new_description=meta.description,
                new_tags=meta.tags,
                thumbnail_path=meta.thumbnail,
                publish_at=publish_at,
                status="к обработке",
                estimated_quota=est,
                meta_notes=meta.source_notes,
                playlist_id=playlist_id,
            )
        )

    projection: dict = {
        "used_today": 0,
        "extra": sum(u for _, u in ops),
        "projected_total": sum(u for _, u in ops),
        "daily_limit": 10000,
        "would_exceed": False,
        "remaining_after": 10000,
    }
    if quota is not None:
        projection = quota.project(ops)

    phrase_date = now.strftime("%d.%m.%Y")
    confirm = f"подтверждаю план от {phrase_date}"

    return ProcessPlan(
        created_at=now,
        root_path=root_path,
        items=items,
        quota_projection=projection,
        confirm_phrase=confirm,
    )


def render_plan_table(plan: ProcessPlan) -> str:
    """ASCII table for CLI output (required columns)."""
    headers = [
        "#",
        "Папка / Текущий title",
        "Новый title",
        "Описание",
        "Обложка",
        "Теги",
        "Дата и время публикации",
        "Статус",
        "Квота",
    ]
    rows: list[list[str]] = []
    for item in plan.items:
        desc_short = (item.new_description[:40] + "…") if len(item.new_description) > 40 else item.new_description
        tags_short = ", ".join(item.new_tags[:5])
        if len(item.new_tags) > 5:
            tags_short += "…"
        cover = item.thumbnail_path.name if item.thumbnail_path else "—"
        pub = format_slot_local(item.publish_at)
        folder_col = f"{item.folder.folder_name}"
        if item.video:
            folder_col += f"\n→ {item.video.snippet.title[:40]}"
        rows.append(
            [
                str(item.index),
                folder_col.replace("\n", " | "),
                item.new_title[:50],
                desc_short,
                cover,
                tags_short[:40],
                pub,
                item.status,
                str(item.estimated_quota) if item.estimated_quota else "0",
            ]
        )

    # Simple fixed-width-ish table
    col_widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
    col_widths = [min(w, 40) for w in col_widths]

    def fmt_row(cols: list[str]) -> str:
        parts = []
        for i, c in enumerate(cols):
            parts.append(c[: col_widths[i]].ljust(col_widths[i]))
        return "| " + " | ".join(parts) + " |"

    sep = "|-" + "-|-".join("-" * w for w in col_widths) + "-|"
    lines = [fmt_row(headers), sep]
    for r in rows:
        lines.append(fmt_row(r))
    lines.append("")
    lines.append(f"К обработке: {len(plan.actionable_items())} / {len(plan.items)}")
    lines.append(
        f"Квота: +{plan.quota_projection.get('extra', 0)} "
        f"(used={plan.quota_projection.get('used_today', 0)}, "
        f"limit={plan.quota_projection.get('daily_limit', 10000)}, "
        f"would_exceed={plan.quota_projection.get('would_exceed', False)})"
    )
    lines.append(f"Для применения напишите точно: «{plan.confirm_phrase}»")
    return "\n".join(lines)
