"""Local secret-input helpers for CLI commands."""

from __future__ import annotations

import os

import click


def require_passphrase(passphrase: str | None) -> str:
    """Read a passphrase without exposing it in arguments or shell history.

    Порядок: явный аргумент → переменная окружения ``AYH_PASSPHRASE`` (для
    неинтерактивных сценариев, в том числе агентов) → интерактивный ввод.
    Приглашение пишется в stderr, чтобы stdout оставался машиночитаемым.
    """
    if passphrase:
        return passphrase
    env = os.environ.get("AYH_PASSPHRASE")
    if env:
        return env
    return str(click.prompt("Пароль локального хранилища", hide_input=True, err=True))
