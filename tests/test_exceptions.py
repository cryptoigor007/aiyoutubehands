"""Exit code mapping tests."""

from __future__ import annotations

from aiyoutubehands.exceptions import (
    EXIT_CHANNEL_MISMATCH,
    exit_code_for_error_code,
)


def test_channel_mismatch_exit() -> None:
    assert exit_code_for_error_code("CHANNEL_MISMATCH") == EXIT_CHANNEL_MISMATCH


def test_unknown_defaults_generic() -> None:
    assert exit_code_for_error_code("SOMETHING_NEW") == 1
