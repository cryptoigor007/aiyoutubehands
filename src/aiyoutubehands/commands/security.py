"""Local secret-input helpers for CLI commands."""

from __future__ import annotations

import click


def require_passphrase(passphrase: str | None) -> str:
    """Read a passphrase from the terminal without exposing it in arguments."""
    if passphrase:
        return passphrase
    return str(click.prompt("Пароль локального хранилища", hide_input=True))
