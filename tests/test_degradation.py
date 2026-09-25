"""Degradation and resilience tests (required by charter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiyoutubehands.client import HttpClient, CircuitOpenError, map_http_error
from aiyoutubehands.quota import QuotaEngine, QuotaError
from aiyoutubehands.token import TokenStore, TokenError, encrypt_bytes, decrypt_bytes
from aiyoutubehands.ai import AIEngine


def test_scaffold_placeholder() -> None:
    assert True


def test_circuit_breaker_degrades() -> None:
    c = HttpClient(failure_threshold=2)
    c._record_failure()
    c._record_failure()
    with pytest.raises(CircuitOpenError):
        c._ensure_circuit()


def test_quota_blocks_without_force(tmp_path: Path) -> None:
    eng = QuotaEngine(tmp_path / "q.db", daily_limit=50)
    eng.consume("x", 50)
    with pytest.raises(QuotaError):
        eng.check(1)


def test_token_corrupt_raises() -> None:
    with pytest.raises(TokenError):
        decrypt_bytes(b"short", b"k" * 32)


def test_ai_local_always_works() -> None:
    eng = AIEngine()
    assert len(eng.generate_title("x")) > 0


def test_map_errors_stable() -> None:
    assert map_http_error(401).code == "AUTH_REQUIRED"
    assert map_http_error(429).retryable is True
