"""Shorts Maker post-processing: scan folders, match, plan, apply."""

from __future__ import annotations

from aiyoutubehands.shorts_maker.folder_scanner import FolderCandidate, scan_root
from aiyoutubehands.shorts_maker.metadata_extractor import ExtractedMeta, extract_metadata
from aiyoutubehands.shorts_maker.matcher import MatchResult, match_candidates
from aiyoutubehands.shorts_maker.plan import PlanItem, ProcessPlan, build_plan
from aiyoutubehands.shorts_maker.scheduler import propose_slots
from aiyoutubehands.shorts_maker.ledger import ProcessedLedger
from aiyoutubehands.shorts_maker.processor import apply_plan

__all__ = [
    "FolderCandidate",
    "scan_root",
    "ExtractedMeta",
    "extract_metadata",
    "MatchResult",
    "match_candidates",
    "PlanItem",
    "ProcessPlan",
    "build_plan",
    "propose_slots",
    "ProcessedLedger",
    "apply_plan",
]
