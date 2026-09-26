"""CLI error mapping tests."""

from __future__ import annotations

from aiyoutubehands.cli_errors import exit_code_for_exception, format_error_lines, handle_cli_error
from aiyoutubehands.client import ClientError
from aiyoutubehands.exceptions import EXIT_CHANNEL_MISMATCH, EXIT_QUOTA, EXIT_USAGE
from aiyoutubehands.quota import QuotaError
from aiyoutubehands.token import TokenError


def test_channel_mismatch_exit() -> None:
    exc = ClientError("mismatch", code="CHANNEL_MISMATCH")
    assert exit_code_for_exception(exc) == EXIT_CHANNEL_MISMATCH


def test_quota_exit() -> None:
    exc = QuotaError("limit", code="QUOTA_EXCEEDED")
    assert exit_code_for_exception(exc) == EXIT_QUOTA


def test_token_exit() -> None:
    exc = TokenError("no file", code="TOKEN_NOT_FOUND")
    assert exit_code_for_exception(exc) == 10


def test_value_error_usage() -> None:
    assert exit_code_for_exception(ValueError("bad")) == EXIT_USAGE


def test_format_lines_include_code() -> None:
    lines = format_error_lines(ClientError("x", code="NOT_FOUND", action="check id"))
    assert any("NOT_FOUND" in ln for ln in lines)
    assert any("check id" in ln or "действие" in ln for ln in lines)


def test_handle_returns_code(capsys) -> None:
    code = handle_cli_error(ClientError("m", code="CHANNEL_MISMATCH"))
    assert code == EXIT_CHANNEL_MISMATCH
    err = capsys.readouterr().err
    assert "CHANNEL_MISMATCH" in err
