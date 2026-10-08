"""Community posts (YouTube «Записи») via Safari web automation (macOS).

Official YouTube Data API v3 has no endpoint for creating community posts.
This package automates the Studio / channel posts dialog in Safari using
Apple Events (osascript + JavaScript) and optional System Events for
native file picker (image attachment).

All macOS-specific code lives in ``safari.py``. Core helpers (JS escaping,
payload validation) are cross-platform and covered by unit tests.
"""

from __future__ import annotations

from aiyoutubehands.posts.models import (
    IMAGE_REQUIREMENTS_RU,
    PostPayload,
    validate_image_path,
    validate_text_file,
)

__all__ = [
    "IMAGE_REQUIREMENTS_RU",
    "PostPayload",
    "validate_image_path",
    "validate_text_file",
]
