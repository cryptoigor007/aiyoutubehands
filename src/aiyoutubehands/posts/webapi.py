"""Pure-Python helpers for the in-page YouTube web API flow (community posts).

The flow below was captured from a real Safari session (08.10.2026):

  1. POST /channel_image_upload/posts          (resumable init -> X-Goog-Upload-URL)
  2. POST <X-Goog-Upload-URL>                  (upload, finalize -> encryptedBlobId)
  3. POST /youtubei/v1/backstage/create_post   (commentText + imagesAttachment)

This module contains only request *construction* and image metadata helpers —
no network access, no macOS dependencies (unit-testable on Linux).
"""

from __future__ import annotations

import base64
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

CROP_CHOICES = ("center", "left", "right", "top", "bottom")


class WebApiBuildError(ValueError):
    """Invalid input for building a web API request."""


def build_create_backstage_post_params(channel_id: str) -> str:
    """base64 protobuf for ``createBackstagePostParams``.

    Captured structure (verified byte-for-byte against a real request):

    ``field1 = <channel id>``, ``field2 = 1``, ``field6 = {field3 = 6}``,
    ``field9 = {field1 = 2}``.

    Raw bytes: ``0A <len> <id> 10 01 32 02 18 06 4A 02 08 02``.
    """
    if not channel_id:
        raise WebApiBuildError("channel_id пустой")
    cid = channel_id.encode("utf-8")
    if len(cid) > 0x7F:
        raise WebApiBuildError("channel_id слишком длинный для protobuf-поля")
    body = (
        bytes([0x0A, len(cid)])
        + cid
        + bytes([0x10, 0x01, 0x32, 0x02, 0x18, 0x06, 0x4A, 0x02, 0x08, 0x02])
    )
    return base64.b64encode(body).decode("ascii")


def compute_preview_coordinates(
    width: int | None,
    height: int | None,
    crop: str = "center",
) -> dict[str, float]:
    """Normalized square crop window ``[0..1]`` like the Studio editor produces.

    ``crop``: ``center`` | ``left`` | ``right`` (для горизонтальных картинок)
    или ``top`` | ``bottom`` (для вертикальных).  Для невалидных значений —
    ``WebApiBuildError``; при неизвестных размерах — полный кадр.
    """
    if crop not in CROP_CHOICES:
        raise WebApiBuildError(f"crop должен быть из {CROP_CHOICES}")
    if not width or not height or width <= 0 or height <= 0:
        return {"top": 0.0, "right": 1.0, "bottom": 1.0, "left": 0.0}
    if width == height:
        return {"top": 0.0, "right": 1.0, "bottom": 1.0, "left": 0.0}
    if width > height:
        side = height / width
        if crop == "left":
            left, right = 0.0, side
        elif crop == "right":
            left, right = 1.0 - side, 1.0
        else:  # center (top/bottom are vertical-only; fall back to center)
            left, right = (1.0 - side) / 2.0, (1.0 + side) / 2.0
        return {
            "top": 0.0,
            "right": round(right, 6),
            "bottom": 1.0,
            "left": round(left, 6),
        }
    side = width / height
    if crop == "top":
        top, bottom = 0.0, side
    elif crop == "bottom":
        top, bottom = 1.0 - side, 1.0
    else:
        top, bottom = (1.0 - side) / 2.0, (1.0 + side) / 2.0
    return {
        "top": round(top, 6),
        "right": 1.0,
        "bottom": round(bottom, 6),
        "left": 0.0,
    }


def read_image_size(path: Path) -> tuple[int, int] | None:
    """Best-effort ``(width, height)`` for jpg/png/gif/webp — без Pillow.

    Returns ``None`` if the format is not recognized or the header is broken;
    callers fall back to full-frame coordinates and warn.
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _webp_size(f)
            if head[:2] == b"\xff\xd8":
                return _jpeg_size(f)
    except (OSError, struct.error):
        return None
    return None


def _jpeg_size(f) -> tuple[int, int] | None:  # type: ignore[no-untyped-def]
    f.seek(2)
    while True:
        b = f.read(1)
        while b and b != b"\xff":
            b = f.read(1)
        if not b:
            return None
        marker = f.read(1)
        while marker == b"\xff":
            marker = f.read(1)
        if not marker:
            return None
        m = marker[0]
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            continue
        ln_b = f.read(2)
        if len(ln_b) != 2:
            return None
        (ln,) = struct.unpack(">H", ln_b)
        if ln < 2:
            return None
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            data = f.read(5)
            if len(data) != 5:
                return None
            h, w = struct.unpack(">HH", data[1:5])
            return int(w), int(h)
        f.seek(ln - 2, 1)


def _webp_size(f) -> tuple[int, int] | None:  # type: ignore[no-untyped-def]
    f.seek(12)
    chunk = f.read(4)
    if chunk == b"VP8X":
        f.read(4)
        data = f.read(10)
        if len(data) < 10:
            return None
        w = 1 + (data[4] | (data[5] << 8) | (data[6] << 16))
        h = 1 + (data[7] | (data[8] << 8) | (data[9] << 16))
        return int(w), int(h)
    if chunk == b"VP8 ":
        f.read(4)
        data = f.read(10)
        if len(data) < 10:
            return None
        w = struct.unpack("<H", data[6:8])[0] & 0x3FFF
        h = struct.unpack("<H", data[8:10])[0] & 0x3FFF
        return int(w), int(h)
    if chunk == b"VP8L":
        f.read(4)
        data = f.read(5)
        if len(data) < 5 or data[0] != 0x2F:
            return None
        bits = data[1] | (data[2] << 8) | (data[3] << 16) | (data[4] << 24)
        w = (bits & 0x3FFF) + 1
        h = ((bits >> 14) & 0x3FFF) + 1
        return int(w), int(h)
    return None
