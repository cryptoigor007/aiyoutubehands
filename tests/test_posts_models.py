"""Unit tests for posts payload validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from aiyoutubehands.posts.models import (
    MAX_TEXT_CHARS,
    PostPayload,
    PostValidationError,
    validate_image_path,
    validate_text_file,
)


def test_validate_text_file_ok(tmp_path: Path) -> None:
    f = tmp_path / "post.txt"
    f.write_text("Привет, это тестовая запись.\n", encoding="utf-8")
    text = validate_text_file(f)
    assert text == "Привет, это тестовая запись."


def test_validate_text_file_missing(tmp_path: Path) -> None:
    with pytest.raises(PostValidationError, match="не найден"):
        validate_text_file(tmp_path / "nope.txt")


def test_validate_text_file_empty(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_text("   \n  ", encoding="utf-8")
    with pytest.raises(PostValidationError, match="пустой"):
        validate_text_file(f)


def test_validate_text_file_too_long(tmp_path: Path) -> None:
    f = tmp_path / "long.txt"
    f.write_text("x" * (MAX_TEXT_CHARS + 1), encoding="utf-8")
    with pytest.raises(PostValidationError, match="длинный"):
        validate_text_file(f)


def test_validate_text_file_non_utf8(tmp_path: Path) -> None:
    f = tmp_path / "bad.txt"
    f.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(PostValidationError, match="UTF-8"):
        validate_text_file(f)


def test_validate_image_path_none() -> None:
    assert validate_image_path(None) is None


def test_validate_image_path_ok(tmp_path: Path) -> None:
    img = tmp_path / "pic.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")
    p = validate_image_path(img)
    assert p is not None
    assert p.suffix == ".jpg"


def test_validate_image_path_bad_suffix(tmp_path: Path) -> None:
    img = tmp_path / "pic.bmp"
    img.write_bytes(b"data")
    with pytest.raises(PostValidationError, match="формат"):
        validate_image_path(img)


def test_validate_image_path_missing(tmp_path: Path) -> None:
    with pytest.raises(PostValidationError, match="не найден"):
        validate_image_path(tmp_path / "missing.png")


def test_validate_image_path_empty(tmp_path: Path) -> None:
    img = tmp_path / "empty.png"
    img.write_bytes(b"")
    with pytest.raises(PostValidationError, match="пустой"):
        validate_image_path(img)


def test_post_payload_from_files(tmp_path: Path) -> None:
    tf = tmp_path / "t.txt"
    tf.write_text("Текст записи", encoding="utf-8")
    img = tmp_path / "i.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    payload = PostPayload.from_files(tf, img, channel_id="UCtest123")
    assert payload.text == "Текст записи"
    assert payload.image is not None
    assert payload.channel_id == "UCtest123"
    assert "UCtest123" in payload.posts_url()
    assert "show_create_dialog=1" in payload.posts_url()


def test_post_payload_posts_url_requires_channel(tmp_path: Path) -> None:
    tf = tmp_path / "t.txt"
    tf.write_text("x", encoding="utf-8")
    payload = PostPayload.from_files(tf)
    with pytest.raises(PostValidationError, match="channel_id"):
        payload.posts_url()

def test_validate_image_path_too_large(tmp_path: Path) -> None:
    from aiyoutubehands.posts.models import MAX_IMAGE_BYTES
    img = tmp_path / "big.jpg"
    # create sparse-like oversized content without using full 16MB RAM if possible
    img.write_bytes(b"x" * (MAX_IMAGE_BYTES + 1))
    with pytest.raises(PostValidationError, match="большая|16"):
        validate_image_path(img)


