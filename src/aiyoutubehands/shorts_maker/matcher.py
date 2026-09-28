"""Match Shorts Maker folders to YouTube VideoResource objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from aiyoutubehands.logging import get_logger
from aiyoutubehands.models.youtube import VideoResource
from aiyoutubehands.shorts_maker.folder_scanner import FolderCandidate

log = get_logger(__name__)

MARKER_PROCESSED = "#ayh_processed"


@dataclass
class MatchResult:
    candidate: FolderCandidate
    video: VideoResource | None
    method: str  # title | video_id | duration_date | none
    reason: str = ""
    # Extra human-readable notes (duplicates, ambiguity)
    notes: str = ""
    related_folders: list[str] = field(default_factory=list)
    related_video_ids: list[str] = field(default_factory=list)


def is_already_styled(
    video: VideoResource,
    *,
    in_playlist_ids: set[str] | None = None,
) -> bool:
    """Video is considered already styled if ≥3 of 5 signals, or marker present."""
    if MARKER_PROCESSED in (video.snippet.description or ""):
        return True

    signals = 0
    title = video.snippet.title or ""
    filename_like = (" " not in title.strip() and len(title) <= 40) or title.endswith(
        (".mp4", ".mov", ".mkv")
    )
    if len(title) > 15 and not filename_like:
        signals += 1
    if len(video.snippet.description or "") > 50:
        signals += 1
    if len(video.snippet.tags or []) >= 3:
        signals += 1
    if video.has_custom_thumbnail():
        signals += 1
    if in_playlist_ids is not None and video.id in in_playlist_ids:
        signals += 1
    return signals >= 3


def _normalize_title(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _view_count(video: VideoResource) -> int:
    stats = (video.raw or {}).get("statistics") or {}
    try:
        return int(stats.get("viewCount") or 0)
    except (TypeError, ValueError):
        return 0


def is_safe_new_upload(video: VideoResource, *, max_age_days: int = 14) -> tuple[bool, str]:
    """Only private, recent, no views → eligible for process mutations."""
    priv = video.status.privacy_status
    if priv in ("public", "unlisted"):
        return False, f"privacy={priv} (только private новые)"
    if priv != "private":
        return False, f"privacy={priv}"
    views = _view_count(video)
    if views > 0:
        return False, f"есть просмотры ({views}) — не трогаем"
    if not _is_recent(video, max_age_days):
        return False, f"старше {max_age_days} дн."
    return True, "ok"


def find_folder_duplicate_groups(
    candidates: list[FolderCandidate],
) -> dict[str, list[FolderCandidate]]:
    """Group non-skipped folders by normalized clean_title (size≥2 = duplicates)."""
    groups: dict[str, list[FolderCandidate]] = {}
    for c in candidates:
        if c.should_skip:
            continue
        key = _normalize_title(c.clean_title) or _normalize_title(c.folder_name)
        if not key:
            continue
        groups.setdefault(key, []).append(c)
    return {k: v for k, v in groups.items() if len(v) >= 2}


def match_candidates(
    candidates: list[FolderCandidate],
    videos: list[VideoResource],
    *,
    max_age_days: int = 14,
    processed_ids: set[str] | None = None,
    in_playlist_ids: set[str] | None = None,
    only_new_private: bool = True,
) -> list[MatchResult]:
    """Match folders to videos by priority rules from TZ.

    Safety:
    - Ambiguous matches (several videos / several folders) → skip with explicit notes
    - only_new_private: never propose public/unlisted or videos with views
    """
    processed_ids = processed_ids or set()
    by_id = {v.id: v for v in videos if v.id}
    by_title: dict[str, list[VideoResource]] = {}
    for v in videos:
        key = _normalize_title(v.snippet.title)
        if key:
            by_title.setdefault(key, []).append(v)

    dup_groups = find_folder_duplicate_groups(candidates)
    # map folder path → sibling folder names
    folder_dup_peers: dict[str, list[str]] = {}
    for _key, group in dup_groups.items():
        names = [g.folder_name for g in group]
        for g in group:
            folder_dup_peers[str(g.path)] = [n for n in names if n != g.folder_name]

    used_ids: set[str] = set()
    results: list[MatchResult] = []

    for cand in candidates:
        peers = folder_dup_peers.get(str(cand.path), [])
        dup_note = ""
        if peers:
            dup_note = f"дубликат папки (ещё: {', '.join(peers[:5])})"

        if cand.should_skip:
            results.append(
                MatchResult(
                    candidate=cand,
                    video=None,
                    method="none",
                    reason=cand.skip_reason or "skip",
                    notes=dup_note,
                    related_folders=peers,
                )
            )
            continue

        title_key = _normalize_title(cand.clean_title)
        matched: VideoResource | None = None
        method = "none"
        reason = ""
        related_vids: list[str] = []

        # a) Exact cleaned title match — require unique free candidate
        if title_key and title_key in by_title:
            free = [v for v in by_title[title_key] if v.id not in used_ids]
            if len(free) == 1:
                matched = free[0]
                method = "title"
            elif len(free) > 1:
                related_vids = [v.id for v in free]
                results.append(
                    MatchResult(
                        candidate=cand,
                        video=None,
                        method="none",
                        reason="неоднозначный title: несколько видео",
                        notes=dup_note
                        or f"video_ids={','.join(related_vids[:8])}",
                        related_folders=peers,
                        related_video_ids=related_vids,
                    )
                )
                continue

        # b) Video ID hint
        if matched is None and cand.video_id_hint:
            v = by_id.get(cand.video_id_hint)
            if v and v.id not in used_ids:
                matched = v
                method = "video_id"
            elif v and v.id in used_ids:
                results.append(
                    MatchResult(
                        candidate=cand,
                        video=v,
                        method="video_id",
                        reason="video_id уже сопоставлен другой папке",
                        notes=dup_note,
                        related_folders=peers,
                        related_video_ids=[v.id],
                    )
                )
                continue

        # c) Duration ±1s + recent — only if unique
        if matched is None and cand.video_file:
            from aiyoutubehands.shorts_maker.media import probe_duration_seconds

            local_dur = probe_duration_seconds(cand.video_file)
            recent = [
                v
                for v in videos
                if v.id not in used_ids and _is_recent(v, max_age_days)
            ]
            if local_dur is not None:
                dur_matches = [
                    v
                    for v in recent
                    if (vd := v.content_details.duration_seconds()) is not None
                    and abs(vd - local_dur) <= 1
                ]
                if len(dur_matches) == 1:
                    matched = dur_matches[0]
                    method = "duration_date"
                    reason = f"duration±1s ({local_dur}s)"
                elif len(dur_matches) > 1:
                    related_vids = [v.id for v in dur_matches]
                    results.append(
                        MatchResult(
                            candidate=cand,
                            video=None,
                            method="none",
                            reason="неоднозначная duration: несколько видео ±1с",
                            notes=f"ids={','.join(related_vids[:8])}",
                            related_folders=peers,
                            related_video_ids=related_vids,
                        )
                    )
                    continue
        if matched is None:
            results.append(
                MatchResult(
                    candidate=cand,
                    video=None,
                    method="none",
                    reason="не сопоставлено",
                    notes=dup_note,
                    related_folders=peers,
                )
            )
            continue

        # Folder duplicates: do NOT auto-apply — operator must resolve
        if peers:
            results.append(
                MatchResult(
                    candidate=cand,
                    video=matched,
                    method=method,
                    reason="дубликат папки — пропуск до разбора",
                    notes=dup_note,
                    related_folders=peers,
                    related_video_ids=[matched.id],
                )
            )
            # do not mark used_ids — another folder might be the real one
            continue

        if matched.id in processed_ids or MARKER_PROCESSED in (
            matched.snippet.description or ""
        ):
            results.append(
                MatchResult(
                    candidate=cand,
                    video=matched,
                    method=method,
                    reason="уже обработано (#ayh_processed / ledger)",
                    related_video_ids=[matched.id],
                )
            )
            used_ids.add(matched.id)
            continue

        if matched.processing_details.processing_status and (
            matched.processing_details.processing_status != "succeeded"
        ):
            results.append(
                MatchResult(
                    candidate=cand,
                    video=matched,
                    method=method,
                    reason=(
                        f"processingStatus="
                        f"{matched.processing_details.processing_status}"
                    ),
                    related_video_ids=[matched.id],
                )
            )
            used_ids.add(matched.id)
            continue

        if is_already_styled(matched, in_playlist_ids=in_playlist_ids):
            results.append(
                MatchResult(
                    candidate=cand,
                    video=matched,
                    method=method,
                    reason="уже оформлено",
                    related_video_ids=[matched.id],
                )
            )
            used_ids.add(matched.id)
            continue

        if only_new_private:
            ok_new, why = is_safe_new_upload(matched, max_age_days=max_age_days)
            if not ok_new:
                results.append(
                    MatchResult(
                        candidate=cand,
                        video=matched,
                        method=method,
                        reason=f"не новое private: {why}",
                        related_video_ids=[matched.id],
                    )
                )
                used_ids.add(matched.id)
                continue

        used_ids.add(matched.id)
        results.append(
            MatchResult(
                candidate=cand,
                video=matched,
                method=method,
                reason=reason or "ok",
                notes=dup_note,
                related_video_ids=[matched.id],
            )
        )

    return results


def _is_recent(video: VideoResource, max_age_days: int) -> bool:
    pub = video.snippet.published_at
    if not pub:
        return video.status.privacy_status == "private"
    try:
        dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
    except ValueError:
        return False
    return dt >= datetime.now(timezone.utc) - timedelta(days=max_age_days)
