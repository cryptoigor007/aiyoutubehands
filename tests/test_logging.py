"""Tests for structured logging."""

from __future__ import annotations

import json
from io import StringIO

from aiyoutubehands.logging import get_logger, setup_logging, correlation_id_var


def test_setup_logging_json() -> None:
    stream = StringIO()
    setup_logging(level="INFO", json_output=True, stream=stream)
    log = get_logger("test")
    log.info("привет", key="value")
    output = stream.getvalue().strip()
    assert output
    # may be one or more lines
    line = output.splitlines()[-1]
    data = json.loads(line)
    assert data["event"] == "привет"
    assert data.get("key") == "value" or "key" in str(data)
    assert "correlation_id" in data


def test_correlation_id_context() -> None:
    token = correlation_id_var.set("test-cid-123")
    try:
        stream = StringIO()
        setup_logging(level="INFO", json_output=True, stream=stream)
        log = get_logger("test")
        log.info("msg")
        line = stream.getvalue().strip().splitlines()[-1]
        data = json.loads(line)
        assert data["correlation_id"] == "test-cid-123"
    finally:
        correlation_id_var.reset(token)


def test_get_logger_returns_logger() -> None:
    log = get_logger("my.module")
    assert log is not None
