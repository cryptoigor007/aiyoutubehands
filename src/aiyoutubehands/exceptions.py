"""Shared exceptions and process exit codes (charter-aligned)."""

from __future__ import annotations

# Exit codes used by CLI
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_AUTH = 10
EXIT_CONFIG = 20
EXIT_QUOTA = 30
EXIT_NETWORK = 40
EXIT_NOT_FOUND = 50
EXIT_FORBIDDEN = 60
EXIT_CHANNEL_MISMATCH = 71  # charter
EXIT_UNSUPPORTED = 80
EXIT_CIRCUIT = 90


class AppError(Exception):
    """Base application error with structured fields."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "APP_ERROR",
        action: str = "",
        retryable: bool = False,
        exit_code: int = EXIT_GENERIC,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.retryable = retryable
        self.exit_code = exit_code


def exit_code_for_error_code(code: str) -> int:
    """Map string error codes to process exit codes."""
    mapping = {
        "CHANNEL_MISMATCH": EXIT_CHANNEL_MISMATCH,
        "AUTH_REQUIRED": EXIT_AUTH,
        "TOKEN_NOT_FOUND": EXIT_AUTH,
        "TOKEN_DECRYPT_FAILED": EXIT_AUTH,
        "CONFIG_ERROR": EXIT_CONFIG,
        "CONFIG_MISSING_CHANNEL_ID": EXIT_CONFIG,
        "CONFIG_READ_ERROR": EXIT_CONFIG,
        "CONFIG_VALIDATION_ERROR": EXIT_CONFIG,
        "QUOTA_EXCEEDED": EXIT_QUOTA,
        "NOT_FOUND": EXIT_NOT_FOUND,
        "CHANNEL_NOT_FOUND": EXIT_NOT_FOUND,
        "FORBIDDEN": EXIT_FORBIDDEN,
        "NETWORK_ERROR": EXIT_NETWORK,
        "RATE_LIMIT": EXIT_NETWORK,
        "CIRCUIT_OPEN": EXIT_CIRCUIT,
        "UNSUPPORTED": EXIT_UNSUPPORTED,
        "UPLOAD_FORBIDDEN": EXIT_FORBIDDEN,
        "CONFIRM_REQUIRED": EXIT_USAGE,
        "BAD_REQUEST": EXIT_USAGE,
    }
    return mapping.get(code, EXIT_GENERIC)
