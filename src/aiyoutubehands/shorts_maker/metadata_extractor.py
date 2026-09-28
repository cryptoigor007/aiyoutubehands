"""Extract title, description, tags, thumbnail from Shorts Maker folder files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from aiyoutubehands.logging import get_logger
from aiyoutubehands.shorts_maker.folder_scanner import FolderCandidate, clean_folder_title

if TYPE_CHECKING:
    from pathlib import Path

log = get_logger(__name__)


@dataclass
class ExtractedMeta:
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    thumbnail: Path | None = None
    source_notes: list[str] = field(default_factory=list)


def _load_json(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("json_load_failed", path=str(path), error=str(exc))
        return None
    if isinstance(data, (dict, list)):
        return data
    return None


def _description_from_editing_plan(path: Path) -> str | None:
    data = _load_json(path)
    if not isinstance(data, dict):
        return None
    clips = data.get("clips")
    if isinstance(clips, list) and clips:
        first = clips[0]
        if isinstance(first, dict):
            desc = first.get("description") or first.get("desc")
            if isinstance(desc, str) and desc.strip():
                return desc.strip()
    # Fallback top-level
    for key in ("description", "desc"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _hashtags_from_editing_plan(path: Path) -> list[str]:
    data = _load_json(path)
    if not isinstance(data, dict):
        return []
    tags: list[str] = []
    clips = data.get("clips")
    if isinstance(clips, list):
        for clip in clips:
            if not isinstance(clip, dict):
                continue
            for key in ("hashtags", "tags"):
                val = clip.get(key)
                if isinstance(val, list):
                    tags.extend(str(t).strip().lstrip("#") for t in val if str(t).strip())
                elif isinstance(val, str) and val.strip():
                    tags.extend(
                        p.strip().lstrip("#") for p in re.split(r"[\s,]+", val) if p.strip()
                    )
    # Top-level
    for key in ("hashtags", "tags"):
        val = data.get(key)
        if isinstance(val, list):
            tags.extend(str(t).strip().lstrip("#") for t in val if str(t).strip())
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        low = t.lower()
        if low and low not in seen:
            seen.add(low)
            out.append(t)
    return out


def _description_from_titles_txt(path: Path) -> str | None:
    """First non-empty block after a title-like line, or first multi-line paragraph."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lines = text.splitlines()
    # Heuristic: after first non-empty line (title), collect following non-empty until blank
    started = False
    buf: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not started:
            if stripped:
                started = True  # skip title line itself
            continue
        if not stripped:
            if buf:
                break
            continue
        buf.append(stripped)
    if buf:
        return " ".join(buf)
    # Fallback: longest line that looks like description
    candidates = [ln.strip() for ln in lines if len(ln.strip()) > 40]
    return candidates[0] if candidates else None


def _tags_from_hashtags_txt(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    tags: list[str] = []
    for part in re.split(r"[\s,]+", text):
        t = part.strip().lstrip("#")
        if t and not t.startswith("http"):
            tags.append(t)
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            out.append(t)
    return out


def extract_metadata(cand: FolderCandidate, *, allow_ai: bool = False) -> ExtractedMeta:
    """Extract title/description/tags/thumbnail per TZ priority rules.

    AI is used only when allow_ai=True and description or tags are critically missing.
    """
    meta = ExtractedMeta()

    # Title: folder name or mp4 stem, strip «шN »
    title = cand.clean_title
    if not title and cand.video_file:
        title = clean_folder_title(cand.video_file.stem)
    raw_title = (title or cand.folder_name or "Untitled").strip()
    meta.title = raw_title[:100] if raw_title else "Untitled"
    meta.source_notes.append("title:folder/mp4")

    # Description priority: editing_plan → final_aisie_plan → titles.txt
    desc: str | None = None
    if cand.editing_plan:
        desc = _description_from_editing_plan(cand.editing_plan)
        if desc:
            meta.source_notes.append("description:editing_plan")
    if not desc and cand.final_aisie_plan:
        desc = _description_from_editing_plan(cand.final_aisie_plan)
        if desc:
            meta.source_notes.append("description:final_aisie_plan")
    if not desc and cand.titles_txt:
        desc = _description_from_titles_txt(cand.titles_txt)
        if desc:
            meta.source_notes.append("description:titles_txt")
    meta.description = (desc or "")[:5000]

    # Tags: hashtags.txt → editing_plan → final_aisie_plan
    tags: list[str] = []
    if cand.hashtags_txt:
        tags = _tags_from_hashtags_txt(cand.hashtags_txt)
        if tags:
            meta.source_notes.append("tags:hashtags_txt")
    if not tags and cand.editing_plan:
        tags = _hashtags_from_editing_plan(cand.editing_plan)
        if tags:
            meta.source_notes.append("tags:editing_plan")
    if not tags and cand.final_aisie_plan:
        tags = _hashtags_from_editing_plan(cand.final_aisie_plan)
        if tags:
            meta.source_notes.append("tags:final_aisie_plan")
    if cand.hooks_txt and cand.hooks_txt.is_file():
        meta.source_notes.append("hooks:present")
    meta.tags = _trim_tags(tags, max_chars=500)

    # Thumbnail
    if cand.cover and cand.cover.is_file():
        meta.thumbnail = cand.cover
        meta.source_notes.append("thumbnail:final_cover")

    # Local Shorts heuristic (duration + vertical) — informational for plan notes
    if cand.video_file and cand.video_file.is_file():
        try:
            from aiyoutubehands.shorts_maker.media import is_likely_short

            short = is_likely_short(cand.video_file)
            if short is True:
                meta.source_notes.append("media:likely_short")
            elif short is False:
                meta.source_notes.append("media:not_short")
        except Exception as exc:  # noqa: BLE001
            log.warning("short_probe_failed", error=str(exc))

    # AI fallback only for critical gaps
    if allow_ai and (not meta.description or len(meta.tags) < 2):
        try:
            from aiyoutubehands.ai import AIEngine

            engine = AIEngine()
            topic = meta.title or cand.folder_name
            if not meta.description:
                meta.description = engine.generate_description(topic)[:5000]
                meta.source_notes.append("description:ai")
            if len(meta.tags) < 2:
                ai_tags = engine.generate_tags(topic)
                merged = list(meta.tags)
                seen = {x.lower() for x in merged}
                for t in ai_tags:
                    if t.lower() not in seen:
                        merged.append(t)
                        seen.add(t.lower())
                meta.tags = _trim_tags(merged, max_chars=500)
                meta.source_notes.append("tags:ai")
        except Exception as exc:  # noqa: BLE001
            log.warning("ai_fallback_failed", error=str(exc))

    return meta


def _trim_tags(tags: list[str], max_chars: int = 500) -> list[str]:
    out: list[str] = []
    total = 0
    for t in tags:
        # +1 for comma separator approximation
        add = len(t) + (1 if out else 0)
        if total + add > max_chars:
            break
        out.append(t)
        total += add
    return out
