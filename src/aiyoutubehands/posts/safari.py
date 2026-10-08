"""macOS Safari automation for YouTube community posts.

All platform-specific code is isolated here.  On non-Darwin systems every
public function raises ``SafariNotAvailableError`` so unit tests and Linux
CI stay green.
"""

from __future__ import annotations

import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from aiyoutubehands.posts.errors import (
    AccessibilityDeniedError,
    ElementTimeoutError,
    ImageAttachFailedError,
    PublishRejectedError,
    SafariNotAvailableError,
)
from aiyoutubehands.posts.js import (
    build_check_error_banner_js,
    build_click_placeholder_js,
    build_dialog_visible_js,
    build_file_input_exists_js,
    build_publish_click_js,
    build_type_text_js,
)
from aiyoutubehands.posts.models import IMAGE_REQUIREMENTS_RU, PostPayload


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _require_macos() -> None:
    if not _is_macos():
        raise SafariNotAvailableError()


def _run_osascript(script: str, *, timeout: float = 30.0) -> str:
    """Execute an AppleScript string, return stdout."""
    _require_macos()
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SafariNotAvailableError("osascript не найден") from exc
    except subprocess.TimeoutExpired as exc:
        raise SafariNotAvailableError(f"osascript timeout ({timeout}s)") from exc
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise SafariNotAvailableError(f"osascript failed: {err}")
    return (result.stdout or "").strip()


def _do_javascript(js: str, *, tab: int = 1) -> str:
    """Run JavaScript in the frontmost Safari tab via Apple Events.

    Requires: Safari → Develop → Allow JavaScript from Apple Events.
    """
    # Escape the JS for embedding inside an AppleScript string.
    # We pass JS via a temporary approach: use quoted form carefully.
    # Safer: write JS to a temp file and tell Safari to execute it.
    # For simplicity and reliability we use do JavaScript with escaped content.
    escaped = js.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    script = (
        f'tell application "Safari"\n'
        f'  do JavaScript "{escaped}" in document {tab}\n'
        f"end tell"
    )
    return _run_osascript(script)


def open_posts_dialog(channel_id: str) -> None:
    """Open Safari at the create-post dialog URL."""
    _require_macos()
    url = (
        f"https://www.youtube.com/channel/{channel_id}/posts"
        f"?show_create_dialog=1"
    )
    script = f'''
tell application "Safari"
  activate
  open location "{url}"
end tell
'''
    _run_osascript(script)
    # Give the page a moment to load
    time.sleep(2.0)


def wait_for_dialog(timeout_s: float = 15.0, poll: float = 0.5) -> None:
    """Poll until the post dialog is visible."""
    _require_macos()
    deadline = time.monotonic() + timeout_s
    js = build_dialog_visible_js()
    while time.monotonic() < deadline:
        raw = _do_javascript(js)
        # osascript returns the JS result as string; we look for "visible:true"
        if "visible" in raw.lower() and "true" in raw.lower():
            return
        time.sleep(poll)
    raise ElementTimeoutError("ytd-backstage-post-dialog-renderer", timeout_s)


def click_placeholder() -> None:
    _require_macos()
    raw = _do_javascript(build_click_placeholder_js())
    if "ok" in raw.lower() and "false" in raw.lower():
        raise ElementTimeoutError("#placeholder-area", 0)


def type_text(text: str) -> None:
    _require_macos()
    raw = _do_javascript(build_type_text_js(text))
    if "ok" in raw.lower() and "false" in raw.lower():
        raise ElementTimeoutError("div#contenteditable-root", 0)


def click_publish() -> None:
    _require_macos()
    raw = _do_javascript(build_publish_click_js())
    if "ok" in raw.lower() and "false" in raw.lower():
        raise ElementTimeoutError("ytd-button-renderer#post-button button", 0)


def check_server_error() -> None:
    """Raise PublishRejectedError if the error banner is present."""
    _require_macos()
    raw = _do_javascript(build_check_error_banner_js())
    low = raw.lower()
    if ("server rejected" in low) or ("rejected" in low) or ("не удалось" in low):
        raise PublishRejectedError(raw)


def attach_image_via_system_events(image_path: Path) -> None:
    """Fallback: drive the native file picker with System Events.

    Requires Accessibility permission for the controlling process.
    """
    _require_macos()
    # First try to click the attach/button that opens the file dialog.
    # Exact selector may need adjustment after HAR; for now we rely on
    # the file input being present and trigger a programmatic click that
    # opens the OS dialog, then System Events fills the path.
    exists_raw = _do_javascript(build_file_input_exists_js())
    if "present" not in exists_raw.lower() or "true" not in exists_raw.lower():
        raise ImageAttachFailedError("input[type=file] не найден в DOM")

    # Trigger click on the file input (may open native dialog)
    trigger_js = """
(function() {
  var inp = document.querySelector('input[type="file"][accept*="image"]');
  if (!inp) return {ok: false};
  inp.click();
  return {ok: true};
})();
"""
    _do_javascript(trigger_js)
    time.sleep(0.8)

    # System Events: type the path into the file dialog and press Return
    path_str = str(image_path.resolve())
    # Escape for AppleScript
    path_as = path_str.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
  try
    keystroke "g" using {{command down, shift down}}
    delay 0.4
    keystroke "{path_as}"
    delay 0.3
    keystroke return
    delay 0.4
    keystroke return
  on error errMsg
    error "Accessibility or dialog error: " & errMsg
  end try
end tell
'''
    try:
        _run_osascript(script, timeout=20.0)
    except SafariNotAvailableError as exc:
        if "Accessibility" in str(exc) or "not allowed" in str(exc).lower():
            raise AccessibilityDeniedError() from exc
        raise ImageAttachFailedError(str(exc)) from exc


def publish_post(payload: PostPayload, *, attach_image: bool = True) -> dict[str, Any]:
    """Full flow: open dialog → type text → optional image → publish.

    Returns a small result dict.  Raises on failure.
    Does NOT verify that the post appears on /posts — caller should.
    """
    _require_macos()
    if not payload.channel_id:
        raise SafariNotAvailableError("channel_id пустой")

    open_posts_dialog(payload.channel_id)
    wait_for_dialog()
    click_placeholder()
    time.sleep(0.4)
    type_text(payload.text)
    time.sleep(0.3)

    if payload.image is not None:
        if not attach_image:
            raise ImageAttachFailedError("картинка указана, но attach отключён")
        attach_image_via_system_events(payload.image)
        time.sleep(1.0)

    click_publish()
    time.sleep(2.0)
    check_server_error()

    return {
        "ok": True,
        "channel_id": payload.channel_id,
        "text_len": len(payload.text),
        "has_image": payload.image is not None,
    }


def dry_run_plan(payload: PostPayload) -> dict[str, Any]:
    """Return a human-readable plan without touching Safari."""
    return {
        "dry_run": True,
        "url": payload.posts_url() if payload.channel_id else None,
        "text_preview": payload.text[:200] + ("…" if len(payload.text) > 200 else ""),
        "text_len": len(payload.text),
        "image": str(payload.image) if payload.image else None,
        "platform": platform.system(),
        "safari_available": _is_macos(),
        "steps": [
            "1. Открыть URL диалога в Safari",
            "2. Дождаться ytd-backstage-post-dialog-renderer",
            "3. Кликнуть #placeholder-area",
            "4. Вставить текст через execCommand/insertText (ASCII-safe)",
            "5. (если image) прикрепить через System Events / native picker",
            "6. Кликнуть видимую кнопку «Опубликовать»",
            "7. Проверить отсутствие баннера ошибки",
            "8. Верификация: пост виден на /posts",
        ],
        "image_requirements": IMAGE_REQUIREMENTS_RU if payload.image else None,
    }
