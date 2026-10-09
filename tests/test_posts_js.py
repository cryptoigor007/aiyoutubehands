"""Unit tests for posts JS helpers (ASCII-safe escaping)."""

from __future__ import annotations

from aiyoutubehands.posts.js import (
    BLOB_VAR,
    CONTENT_EDITABLE_SELECTOR,
    PLACEHOLDER_SELECTOR,
    POST_BUTTON_SELECTOR,
    RESULT_VAR,
    ascii_safe_js_string,
    build_check_error_banner_js,
    build_click_placeholder_js,
    build_create_post_js,
    build_dialog_visible_js,
    build_get_result_js,
    build_page_ready_js,
    build_publish_click_js,
    build_reset_result_js,
    build_reset_result_only_js,
    build_type_text_js,
    build_upload_chunk_js,
    build_upload_finalize_js,
    build_upload_init_js,
    build_verify_post_js,
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


# ---------------------------------------------------------------------------
# API flow builders
# ---------------------------------------------------------------------------


def test_ui_builders_return_json_strings() -> None:
    """do JavaScript must return strings — objects do not survive the bridge."""
    for js in (
        build_click_placeholder_js(),
        build_type_text_js("x"),
        build_publish_click_js(),
        build_dialog_visible_js(),
        build_check_error_banner_js(),
    ):
        assert "JSON.stringify" in js
        assert all(ord(c) < 128 for c in js)


def test_upload_init_js_structure() -> None:
    js = build_upload_init_js("UCtest123", 235772)
    assert all(ord(c) < 128 for c in js)
    assert "channel_image_upload" in js
    assert "X-YouTube-ChannelId" in js
    assert "X-Goog-Upload-Protocol" in js
    assert "resumable" in js
    assert "X-Goog-Upload-Command" in js
    assert "235772" in js


def test_upload_chunk_js_appends() -> None:
    js_first = build_upload_chunk_js("QUJD", first=True)
    js_next = build_upload_chunk_js("REVG", first=False)
    assert "QUJD" in js_first
    assert "__AYH_IMG_B64" in js_next
    assert all(ord(c) < 128 for c in js_first + js_next)


def test_upload_finalize_js_structure() -> None:
    js = build_upload_finalize_js("UCtest", "https://www.youtube.com/x?a=1&b=2")
    assert all(ord(c) < 128 for c in js)
    assert "upload, finalize" in js
    assert "encryptedBlobId" in js
    assert "X-Goog-Upload-Offset" in js


def test_create_post_js_cyrillic_and_structure() -> None:
    js = build_create_post_js(
        "ChhVQ0NY",
        "Привет, мир",
        {"top": 0.0, "right": 1.0, "bottom": 1.0, "left": 0.0},
    )
    assert all(ord(c) < 128 for c in js)
    assert "Привет" not in js
    assert "\\u" in js
    assert "backstage/create_post" in js
    assert "createBackstagePostParams" in js
    assert "commentText" in js
    assert "imagesAttachment" in js
    assert "encryptedBlobId" in js
    assert "previewCoordinates" in js
    assert "SAPISIDHASH" in js
    assert "SAPISID3PHASH" in js
    assert "USER_SESSION_ID" in js
    assert "_u SAPISID3PHASH" in js
    assert "buildAuth" in js
    assert "x-goog-authuser" in js
    assert "x-goog-visitor-id" in js
    assert "x-youtube-bootstrap-logged-in" in js
    assert "SESSION_INDEX" in js
    assert "VISITOR_DATA" in js
    assert "CompressionStream" in js


def test_reset_result_only_keeps_blob_var() -> None:
    js = build_reset_result_only_js()
    assert all(ord(c) < 128 for c in js)
    assert RESULT_VAR in js
    assert BLOB_VAR not in js


def test_page_ready_and_result_builders() -> None:
    js = build_page_ready_js()
    assert "INNERTUBE_CONTEXT" in js
    assert all(ord(c) < 128 for c in js)
    js2 = build_get_result_js()
    assert "__AYH_POST_RESULT" in js2
    js3 = build_reset_result_js()
    assert "reset" in js3


def test_verify_post_js_cyrillic_escaped() -> None:
    js = build_verify_post_js("UCtest", "Одиночество — это не когда")
    assert all(ord(c) < 128 for c in js)
    assert "Одиночество" not in js
    assert "\\u" in js
    assert "/posts" in js
