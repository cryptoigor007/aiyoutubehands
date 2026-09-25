"""Tests for structured logging."""

from __future__ import annotations

import json
import logging
from io import StringIO

import pytest

from aiyoutubehands.logging import get_logger, setup_logging, correlation_id_var


def test_setup_logging_json() -> None:
    stream = StringIO()
    setup_logging(level="INFO", json_output=True, stream=stream)
    log = get_logger("test")
    log.info("привет", key="value")
    output = stream.getvalue().strip()
    assert output
    data = json.loads(output)
    assert data["event"] == "привет"
    assert data["key"] == "value"
    assert "correlation_id" in data
    assert data["level"] == "info"


def test_correlation_id_context() -> None:
    token = correlation_id_var.set("test-cid-123")
    try:
        stream = StringIO()
        setup_logging(level="INFO", json_output=True, stream=stream)
        log = get_logger("test")
        log.info("msg")
        data = json.loads(stream.getvalue().strip())
        assert data["correlation_id"] == "test-cid-123"
    finally:
        correlation_id_var.reset(token)


def test_get_logger_returns_bound_logger() -> None:
    log = get_logger("my.module")
    assert log is not None
