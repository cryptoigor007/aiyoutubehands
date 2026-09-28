"""Tests for quota engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aiyoutubehands.quota import (
    QuotaEngine,
    QuotaError,
    QuotaLedger,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_ledger_record_and_total(tmp_path: Path) -> None:
    db = tmp_path / "quota.db"
    ledger = QuotaLedger(db)
    ledger.record("videos.insert", 1600)
    ledger.record("search.list", 100)
    assert ledger.total_today() == 1700


def test_engine_check_allows(tmp_path: Path) -> None:
    eng = QuotaEngine(db_path=tmp_path / "q.db", daily_limit=10000)
    eng.check(100)
    eng.consume("test", 100)
    assert eng.used_today() == 100
    assert eng.remaining() == 9900


def test_engine_exceeds_raises(tmp_path: Path) -> None:
    eng = QuotaEngine(db_path=tmp_path / "q.db", daily_limit=100)
    eng.consume("a", 90)
    with pytest.raises(QuotaError) as ei:
        eng.check(20)
    assert ei.value.code == "QUOTA_EXCEEDED"
    assert ei.value.retryable is False


def test_engine_force_quota(tmp_path: Path) -> None:
    eng = QuotaEngine(db_path=tmp_path / "q.db", daily_limit=10, force_quota=True)
    eng.check(100)  # should not raise
    eng.consume("force", 100)
    assert eng.used_today() == 100


def test_projection(tmp_path: Path) -> None:
    eng = QuotaEngine(db_path=tmp_path / "q.db", daily_limit=10000)
    eng.consume("x", 500)
    proj = eng.project([("videos.insert", 1600), ("search.list", 100)])
    assert proj["projected_total"] == 2200
    assert proj["would_exceed"] is False
