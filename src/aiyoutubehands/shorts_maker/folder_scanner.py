"""Scan Shorts Maker root folder for per-clip subfolders."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from aiyoutubehands.logging import get_logger

log = get_logger(__name__)

# Prefix like «ш1 », «ш12 », «ш 3 »
_PREFIX_RE = re.compile(r"^ш\s*\d+\s*", re.IGNORECASE)
# Video ID pattern (YouTube video ids are 11 chars [A-Za-z0-9_-])
_VIDEO_ID_RE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")

MARKER_PEREDELAT = "ПЕРЕДЕЛАТЬ"
MARKER_RAZOBRATSYA = "НУЖНО РАЗОБРАТЬСЯ"


@dataclass
class FolderCandidate:
    """One Shorts Maker subfolder with discovered files and markers."""

    path: Path
    folder_name: str
    clean_title: str
    video_file: Path | None = None
    cover: Path | None = None  # *_final_cover.jpg
    titles_txt: Path | None = None
    hashtags_txt: Path | None = None
    hooks_txt: Path | None = None
    editing_plan: Path | None = None  # *_editing_plan.json
    final_aisie_plan: Path | None = None
    transcript_json: Path | None = None
    markers: set[str] = field(default_factory=set)
    video_id_hint: str | None = None  # from НУЖНО РАЗОБРАТЬСЯ.txt
    prefix_mismatch: bool = False
    skip_reason: str | None = None

    @property
    def should_skip(self) -> bool:
        return self.skip_reason is not None


def clean_folder_title(name: str) -> str:
    """Remove leading «шN » prefix from folder or file stem."""
    return _PREFIX_RE.sub("", name).strip()


def _extract_prefix_number(name: str) -> str | None:
    m = re.match(r"^ш\s*(\d+)", name, re.IGNORECASE)
    return m.group(1) if m else None


def _find_first(folder: Path, patterns: list[str]) -> Path | None:
    for pat in patterns:
        matches = sorted(folder.glob(pat))
        if matches:
            return matches[0]
    return None


def _read_video_id_hint(path: Path) -> str | None:
    """Extract first YouTube-like video id from marker file content."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = _VIDEO_ID_RE.search(text)
    return m.group(1) if m else None


def scan_folder(folder: Path) -> FolderCandidate:
    """Inspect a single Shorts Maker subfolder."""
    folder = folder.resolve()
    name = folder.name
    clean = clean_folder_title(name)
    cand = FolderCandidate(path=folder, folder_name=name, clean_title=clean)

    if not folder.is_dir():
        cand.skip_reason = "не директория"
        return cand

    # Markers
    for f in folder.iterdir():
        if not f.is_file():
            continue
        fname = f.name
        if MARKER_PEREDELAT in fname and fname.endswith(".txt"):
            cand.markers.add(MARKER_PEREDELAT)
        if MARKER_RAZOBRATSYA in fname or fname == "НУЖНО РАЗОБРАТЬСЯ.txt":
            cand.markers.add(MARKER_RAZOBRATSYA)
            hint = _read_video_id_hint(f)
            if hint:
                cand.video_id_hint = hint

    if MARKER_PEREDELAT in cand.markers:
        cand.skip_reason = "маркер ПЕРЕДЕЛАТЬ"
        return cand
    if MARKER_RAZOBRATSYA in cand.markers:
        cand.skip_reason = "маркер НУЖНО РАЗОБРАТЬСЯ"
        return cand

    # Files
    cand.video_file = _find_first(folder, ["*.mp4", "*.MP4"])
    cand.cover = _find_first(
        folder, ["*_final_cover.jpg", "*_final_cover.jpeg", "*_final_cover.png"]
    )
    cand.titles_txt = _find_first(folder, ["*_titles.txt", "*titles*.txt"])
    cand.hashtags_txt = _find_first(folder, ["*_hashtags.txt", "*hashtags*.txt"])
    cand.hooks_txt = _find_first(folder, ["*_hooks.txt"])
    cand.editing_plan = _find_first(folder, ["*_editing_plan.json", "*editing_plan*.json"])
    cand.final_aisie_plan = _find_first(folder, ["*_final_aisie_plan.json"])
    cand.transcript_json = _find_first(
        folder,
        [
            "*_corrected_words.json",
            "*_transcript.json",
            "*transcript*.json",
        ],
    )

    # Prefix consistency: folder «ш5 …» vs files «ш35_…»
    folder_num = _extract_prefix_number(name)
    if folder_num and cand.video_file:
        file_num = _extract_prefix_number(cand.video_file.stem)
        if file_num and file_num != folder_num:
            cand.prefix_mismatch = True
            cand.skip_reason = f"несовпадение префикса ш{folder_num} vs ш{file_num}"
            return cand

    if not cand.video_file and not cand.editing_plan and not cand.titles_txt:
        cand.skip_reason = "нет полезных файлов (mp4 / plan / titles)"
        return cand

    # Prefer clean title from mp4 stem if folder name is generic
    if cand.video_file:
        stem_clean = clean_folder_title(cand.video_file.stem)
        if stem_clean and (not clean or clean == name):
            cand.clean_title = stem_clean

    return cand


def scan_root(root: Path | str) -> list[FolderCandidate]:
    """Scan all immediate subfolders of Shorts Maker root."""
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise FileNotFoundError(f"Папка не найдена: {root_path}")

    candidates: list[FolderCandidate] = []
    for child in sorted(root_path.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        cand = scan_folder(child)
        candidates.append(cand)
        log.info(
            "folder_scanned",
            folder=cand.folder_name,
            skip=cand.skip_reason,
            clean_title=cand.clean_title,
        )
    return candidates
