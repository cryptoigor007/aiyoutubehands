"""Map domain errors to CLI exit codes and user-facing messages."""

from __future__ import annotations

import sys
from typing import Any

import click

from aiyoutubehands.exceptions import (
    EXIT_GENERIC,
    EXIT_USAGE,
    AppError,
    exit_code_for_error_code,
)


def _error_fields(exc: BaseException) -> tuple[str, str, str, bool]:
    """Return (code, message, action, retryable) from known exception types."""
    code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)
    action = getattr(exc, "action", "") or ""
    retryable = bool(getattr(exc, "retryable", False))
    if isinstance(code, str) and code:
        return code, message, action, retryable
    if isinstance(exc, AppError):
        return exc.code, exc.message, exc.action, exc.retryable
    if isinstance(exc, ValueError):
        return "USAGE", message, "Проверьте аргументы", False
    if isinstance(exc, FileNotFoundError):
        return "NOT_FOUND", message, "Проверьте путь к файлу", False
    if isinstance(exc, PermissionError):
        return "FORBIDDEN", message, "Проверьте права доступа", False
    return "APP_ERROR", message, "", False


def exit_code_for_exception(exc: BaseException) -> int:
    if isinstance(exc, AppError):
        return exc.exit_code
    if isinstance(exc, click.ClickException):
        return EXIT_USAGE
    if isinstance(exc, click.exceptions.Exit):
        return int(getattr(exc, "exit_code", EXIT_GENERIC))
    code, _, _, _ = _error_fields(exc)
    if code == "USAGE":
        return EXIT_USAGE
    return exit_code_for_error_code(code)


def format_error_lines(exc: BaseException) -> list[str]:
    code, message, action, retryable = _error_fields(exc)
    lines = [f"ошибка [{code}]: {message}"]
    if action:
        lines.append(f"действие: {action}")
    if retryable:
        lines.append("можно повторить: да")
    return lines


def handle_cli_error(exc: BaseException, *, err: Any = None) -> int:
    """Print error to stderr and return process exit code."""
    if err is None:
        err = sys.stderr
    if isinstance(exc, click.exceptions.Exit):
        return int(getattr(exc, "exit_code", 0))
    if isinstance(exc, click.Abort):
        click.echo("отменено", err=True)
        return EXIT_GENERIC
    if isinstance(exc, click.ClickException):
        exc.show()
        return EXIT_USAGE
    for line in format_error_lines(exc):
        click.echo(line, err=True)
    return exit_code_for_exception(exc)
