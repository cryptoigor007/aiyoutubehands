"""Unit tests for pure-Python web API helpers (posts)."""

from __future__ import annotations

import base64
import struct
from typing import TYPE_CHECKING

import pytest

from aiyoutubehands.posts.webapi import (
    WebApiBuildError,
    build_create_backstage_post_params,
    compute_preview_coordinates,
    read_image_size,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_params_structure_and_roundtrip() -> None:
    cid = "UC" + "x" * 22  # 24 chars like real channel ids
    enc = build_create_backstage_post_params(cid)
    raw = base64.b64decode(enc)
    assert raw[0] == 0x0A
    assert raw[1] == len(cid)
    assert raw[2 : 2 + len(cid)].decode() == cid
    tail = raw[2 + len(cid) :]
    assert tail == bytes([0x10, 0x01, 0x32, 0x02, 0x18, 0x06, 0x4A, 0x02, 0x08, 0x02])
    assert enc.isascii()


def test_params_empty_channel() -> None:
    with pytest.raises(WebApiBuildError):
        build_create_backstage_post_params("")


def test_coords_square_full_frame() -> None:
    assert compute_preview_coordinates(1000, 1000, "center") == {
        "top": 0.0,
        "right": 1.0,
        "bottom": 1.0,
        "left": 0.0,
    }


def test_coords_16x9_center() -> None:
    c = compute_preview_coordinates(1280, 720, "center")
    assert c["left"] == pytest.approx(0.21875)
    assert c["right"] == pytest.approx(0.78125)
    assert c["top"] == 0.0
    assert c["bottom"] == 1.0


def test_coords_16x9_right() -> None:
    c = compute_preview_coordinates(1280, 720, "right")
    assert c["left"] == pytest.approx(0.4375)
    assert c["right"] == 1.0


def test_coords_16x9_left() -> None:
    c = compute_preview_coordinates(1280, 720, "left")
    assert c["left"] == 0.0
    assert c["right"] == pytest.approx(0.5625)


def test_coords_portrait_center() -> None:
    c = compute_preview_coordinates(720, 1280, "center")
    assert c["top"] == pytest.approx(0.21875)
    assert c["bottom"] == pytest.approx(0.78125)
    assert c["left"] == 0.0
    assert c["right"] == 1.0


def test_coords_unknown_size_full_frame() -> None:
    assert compute_preview_coordinates(None, None, "center") == {
        "top": 0.0,
        "right": 1.0,
        "bottom": 1.0,
        "left": 0.0,
    }


def test_coords_bad_crop() -> None:
    with pytest.raises(WebApiBuildError):
        compute_preview_coordinates(100, 50, "diagonal")


def _png_bytes(w: int, h: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">II", w, h)
    return sig + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x08\x02\x00\x00\x00" + b"\x00" * 4


def test_read_png_size(tmp_path: Path) -> None:
    p = tmp_path / "a.png"
    p.write_bytes(_png_bytes(1080, 1080))
    assert read_image_size(p) == (1080, 1080)


def test_read_gif_size(tmp_path: Path) -> None:
    p = tmp_path / "a.gif"
    p.write_bytes(b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 10)
    assert read_image_size(p) == (640, 480)


def test_read_jpeg_size(tmp_path: Path) -> None:
    app0 = (
        b"\xff\xe0"
        + struct.pack(">H", 16)
        + b"JFIF\x00"
        + b"\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00\x00"
    )
    sof = (
        b"\xff\xc0"
        + struct.pack(">H", 17)
        + b"\x08"
        + struct.pack(">HH", 720, 1280)
        + b"\x03"
        + b"\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    p = tmp_path / "a.jpg"
    p.write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")
    assert read_image_size(p) == (1280, 720)


def test_read_webp_vp8x_size(tmp_path: Path) -> None:
    w, h = 1200, 630
    wm, hm = w - 1, h - 1
    chunk = (
        b"VP8X"
        + struct.pack("<I", 10)
        + b"\x00\x00\x00\x00"
        + bytes([wm & 0xFF, (wm >> 8) & 0xFF, (wm >> 16) & 0xFF])
        + bytes([hm & 0xFF, (hm >> 8) & 0xFF, (hm >> 16) & 0xFF])
    )
    payload = b"WEBP" + chunk
    riff = b"RIFF" + struct.pack("<I", len(payload)) + payload
    p = tmp_path / "a.webp"
    p.write_bytes(riff)
    assert read_image_size(p) == (1200, 630)


def test_read_image_size_bad_file(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"not an image")
    assert read_image_size(p) is None
