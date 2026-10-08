"""Unit tests for posts JS helpers (ASCII-safe escaping)."""

from __future__ import annotations

from aiyoutubehands.posts.js import (
    CONTENT_EDITABLE_SELECTOR,
    PLACEHOLDER_SELECTOR,
    POST_BUTTON_SELECTOR,
    ascii_safe_js_string,
    build_check_error_banner_js,
    build_click_placeholder_js,
    build_dialog_visible_js,
    build_publish_click_js,
    build_type_text_js,
)


def test_ascii_safe_js_string_ascii_only() -> None:
    s = ascii_safe_js_string("hello world")
    assert s == '"hello world"'
    assert all(ord(c) < 128 for c in s)


def test_ascii_safe_js_string_cyrillic() -> None:
    s = ascii_safe_js_string("Привет")
    assert all(ord(c) < 128 for c in s)
    assert "\\u041f" in s  # П
    assert "\\u0440" in s  # р
    assert "Привет" not in s


def test_ascii_safe_js_string_mixed() -> None:
    s = ascii_safe_js_string("Test: Запись #1")
    assert all(ord(c) < 128 for c in s)
    assert "\\u0417" in s  # З
    assert "Test:" in s


def test_ascii_safe_js_string_empty() -> None:
    assert ascii_safe_js_string("") == '""'


def test_ascii_safe_js_string_quotes_and_newlines() -> None:
    s = ascii_safe_js_string('line1\n"quoted"')
    assert all(ord(c) < 128 for c in s)
    assert "\\n" in s
    assert '\\"' in s or "\\u0022" in s


def test_build_click_placeholder_js_is_ascii() -> None:
    js = build_click_placeholder_js()
    assert all(ord(c) < 128 for c in js)
    assert PLACEHOLDER_SELECTOR in js or "placeholder" in js


def test_build_type_text_js_cyrillic_escaped() -> None:
    text = "Это тестовая запись с кириллицей"
    js = build_type_text_js(text)
    assert all(ord(c) < 128 for c in js)
    assert "\\u" in js
    assert text not in js  # raw Cyrillic must not appear
    assert CONTENT_EDITABLE_SELECTOR in js or "contenteditable" in js


def test_build_type_text_js_insert_text_command() -> None:
    js = build_type_text_js("hello")
    assert "insertText" in js
    assert "execCommand" in js


def test_build_publish_click_js_visible_check() -> None:
    js = build_publish_click_js()
    assert all(ord(c) < 128 for c in js)
    assert "width > 0" in js or "rect.width" in js
    assert "disabled" in js
    assert POST_BUTTON_SELECTOR in js or "post-button" in js


def test_build_dialog_visible_js() -> None:
    js = build_dialog_visible_js()
    assert all(ord(c) < 128 for c in js)
    assert "height > 50" in js or "rect.height" in js


def test_build_check_error_banner_js_cyrillic_escaped() -> None:
    js = build_check_error_banner_js()
    assert all(ord(c) < 128 for c in js)
    # The Russian error phrase must be present only as \\u escapes
    assert "Не удалось" not in js
    assert "\\u" in js
