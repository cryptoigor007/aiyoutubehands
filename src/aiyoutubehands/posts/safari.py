"""macOS Safari automation for YouTube community posts.

Two publish paths:

* ``api`` (primary, default): in-page fetch replay of the web API flow
  captured on 08.10.2026 — upload init → finalize → ``backstage/create_post``.
  No native dialogs and no Accessibility permission required; needs only
  Safari + "Allow JavaScript from Apple Events" + a logged-in youtube.com tab.
* ``ui`` (fallback): DOM automation of the create-post dialog (text-only;
  image attachment via native picker is not supported in this path).

All platform-specific code is isolated here.  On non-Darwin systems every
public function raises ``SafariNotAvailableError`` so unit tests and Linux
CI stay green.
"""

from __future__ import annotations

import base64
import contextlib
import json
import platform
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from aiyoutubehands.posts import js as jsmod
from aiyoutubehands.posts.errors import (
    ElementTimeoutError,
    ImageAttachFailedError,
    PostsError,
    PublishRejectedError,
    SafariNotAvailableError,
)
from aiyoutubehands.posts.models import IMAGE_REQUIREMENTS_RU, PostPayload
from aiyoutubehands.posts.webapi import (
    build_create_backstage_post_params,
    compute_preview_coordinates,
    read_image_size,
)

#: base64 chars per do-JavaScript call (image buffer is chunked to keep each
#: AppleScript round-trip small; ~400k chars ≈ 300 KiB of image per chunk)
CHUNK_SIZE = 400_000

YOUTUBE_URL_PART = "www.youtube.com"

#: the finalized upload blob needs a moment of server-side processing before
#: ``create_post`` accepts it (publishing right away yields 400 badRequest)
BLOB_SETTLE_SECONDS = 6.0

#: create_post attempts on 400 (server-side blob processing lag); 403/429 and
#: other statuses stop immediately
CREATE_ATTEMPTS = 3
CREATE_RETRY_PAUSE_SECONDS = 6.0


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


def _do_javascript(js: str, *, timeout: float = 30.0) -> str:
    """Run JavaScript in the current tab of the frontmost Safari window.

    Requires: Safari → Develop → Allow JavaScript from Apple Events.
    The JS is written to a temp file and read back as *ASCII* text — this is
    the encoding-safe path (raw UTF-8 breaks AppleScript; every builder here
    is ASCII-only by contract).
    """
    _require_macos()
    if not js.isascii():
        raise SafariNotAvailableError(
            "внутренняя ошибка: JS не ASCII-safe (баг в билдере)"
        )
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", prefix="ayh_post_", delete=False, encoding="ascii"
    ) as f:
        f.write(js)
        path = f.name
    try:
        script = (
            f'set js to (read POSIX file "{path}" as text)\n'
            "tell application \"Safari\" to do JavaScript js "
            "in current tab of front window"
        )
        return _run_osascript(script, timeout=timeout)
    finally:
        with contextlib.suppress(OSError):
            Path(path).unlink()


def _js_json(js: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Run JS and parse its JSON-string result into a dict."""
    raw = _do_javascript(js, timeout=timeout)
    s = (raw or "").strip()
    if not s or s == "missing value":
        raise PostsError("Пустой ответ от Safari JS")
    try:
        data = json.loads(s)
    except json.JSONDecodeError as exc:
        raise PostsError(f"Некорректный ответ Safari JS: {s[:120]}") from exc
    if not isinstance(data, dict):
        raise PostsError(f"Неожиданный ответ Safari JS: {s[:120]}")
    return data


def _current_tab_url() -> str:
    try:
        return _run_osascript(
            'tell application "Safari" to get URL of current tab of front window'
        )
    except SafariNotAvailableError:
        return ""


def _focus_tab_with_url(url_part: str) -> bool:
    """Focus a window-1 tab whose URL contains ``url_part`` (if any)."""
    script = f'''
tell application "Safari"
  activate
  set out to "no"
  repeat with k from 1 to (count of tabs of window 1)
    if (URL of tab k of window 1) contains "{url_part}" then
      set current tab of window 1 to tab k of window 1
      set out to "yes"
      exit repeat
    end if
  end repeat
  return out
end tell
'''
    try:
        return _run_osascript(script).lower().startswith("yes")
    except SafariNotAvailableError:
        return False


def ensure_youtube_tab(channel_id: str, *, timeout_s: float = 25.0) -> None:
    """Make sure a logged-in ``www.youtube.com`` tab is frontmost.

    Reuses the current tab if it is already youtube.com, else focuses an
    existing youtube.com tab, else opens the channel /posts page.
    """
    _require_macos()
    if YOUTUBE_URL_PART in _current_tab_url():
        return
    if _focus_tab_with_url(YOUTUBE_URL_PART):
        return
    url = f"https://www.youtube.com/channel/{channel_id}/posts"
    _run_osascript(
        'tell application "Safari"\n'
        "  activate\n"
        f'  open location "{url}"\n'
        "end tell"
    )
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if YOUTUBE_URL_PART in _current_tab_url():
            return
        time.sleep(0.5)
    raise ElementTimeoutError(YOUTUBE_URL_PART, timeout_s)


def _wait_js_ok(
    js: str,
    *,
    timeout_s: float,
    poll: float = 0.5,
    expect_key: str = "ok",
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _js_json(js)
        if last.get(expect_key) is True:
            return last
        time.sleep(poll)
    raise ElementTimeoutError(str(js)[:60], timeout_s)


def _poll_result(
    *,
    expect_step: str,
    timeout_s: float,
    poll: float = 0.4,
) -> dict[str, Any]:
    """Poll ``window.__AYH_POST_RESULT`` until the expected async step lands."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = _do_javascript(jsmod.build_get_result_js())
        s = (raw or "").strip()
        if s and s != "missing value":
            try:
                data = json.loads(s)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict) and data.get("step") == expect_step:
                return data
        time.sleep(poll)
    raise ElementTimeoutError(f"результат шага «{expect_step}»", timeout_s)


# ---------------------------------------------------------------------------
# UI flow (fallback, text-only)
# ---------------------------------------------------------------------------


def open_posts_dialog(channel_id: str) -> None:
    """Open Safari at the create-post dialog URL."""
    _require_macos()
    url = f"https://www.youtube.com/channel/{channel_id}/posts?show_create_dialog=1"
    _run_osascript(
        'tell application "Safari"\n'
        "  activate\n"
        f'  open location "{url}"\n'
        "end tell"
    )
    time.sleep(2.0)


def wait_for_dialog(timeout_s: float = 20.0, poll: float = 0.5) -> None:
    """Poll until the post dialog is visible."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        d = _js_json(jsmod.build_dialog_visible_js())
        if d.get("visible") is True:
            return
        time.sleep(poll)
    raise ElementTimeoutError(jsmod.DIALOG_SELECTOR, timeout_s)


def click_placeholder() -> None:
    d = _js_json(jsmod.build_click_placeholder_js())
    if not d.get("ok"):
        raise ElementTimeoutError("#placeholder-area", 0)


def type_text(text: str) -> None:
    d = _js_json(jsmod.build_type_text_js(text))
    if not d.get("ok"):
        raise PostsError("Текст не вставился в редактор записи")


def click_publish() -> None:
    d = _js_json(jsmod.build_publish_click_js())
    if not d.get("ok"):
        raise ElementTimeoutError("видимая кнопка «Опубликовать»", 0)


def check_server_error() -> None:
    """Raise PublishRejectedError if the error banner is present."""
    d = _js_json(jsmod.build_check_error_banner_js())
    if not d.get("ok"):
        raise PublishRejectedError(str(d.get("error") or ""))


# ---------------------------------------------------------------------------
# API flow (primary)
# ---------------------------------------------------------------------------


def publish_post_api(
    payload: PostPayload,
    *,
    progress: Callable[[str], None] | None = None,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Publish a community post via the captured in-page web API flow.

    Steps: ensure youtube.com tab → (image) upload init → chunked bytes →
    finalize (encryptedBlobId) → ``backstage/create_post`` → verify on /posts.
    Raises on failure; never publishes without the image if one was requested.
    """
    _require_macos()
    say = progress or (lambda msg: None)
    if not payload.channel_id:
        raise SafariNotAvailableError("channel_id пустой")

    ensure_youtube_tab(payload.channel_id)
    say("Safari: страница youtube.com готова, ждём InnerTube-контекст…")
    _wait_js_ok(jsmod.build_page_ready_js(), timeout_s=25.0)

    blob_id_len = 0
    if payload.image is not None:
        size = payload.image.stat().st_size
        say(f"Картинка ({size} байт): старт загрузки…")
        _do_javascript(jsmod.build_reset_result_js())
        _do_javascript(jsmod.build_upload_init_js(payload.channel_id, size))
        res = _poll_result(expect_step="init", timeout_s=timeout_s)
        if not res.get("ok"):
            raise ImageAttachFailedError(
                f"upload init: {res.get('error') or res.get('status')}"
            )
        upload_url = str(res.get("uploadUrl") or "")

        b64 = base64.b64encode(payload.image.read_bytes()).decode("ascii")
        say(f"Картинка: передаю байты ({len(b64)} b64-симв.)…")
        first = True
        for i in range(0, len(b64), CHUNK_SIZE):
            chunk = b64[i : i + CHUNK_SIZE]
            _do_javascript(jsmod.build_upload_chunk_js(chunk, first=first))
            first = False

        _do_javascript(jsmod.build_upload_finalize_js(payload.channel_id, upload_url))
        res = _poll_result(expect_step="finalize", timeout_s=timeout_s)
        if not res.get("ok"):
            raise ImageAttachFailedError(
                f"upload finalize: {res.get('error') or res.get('status')}"
            )
        blob_id_len = int(res.get("blobIdLen") or 0)
        say(f"Картинка загружена (blobId: {blob_id_len} симв.)")

    wh = read_image_size(payload.image) if payload.image else None
    w, h = wh if wh else (None, None)
    coords = compute_preview_coordinates(w, h, crop=payload.crop)
    if payload.image is not None and wh is None:
        say("ВНИМАНИЕ: размеры картинки не распознаны — кадр выставлен полный.")

    if payload.image is not None:
        time.sleep(BLOB_SETTLE_SECONDS)

    params = build_create_backstage_post_params(payload.channel_id)
    say("Публикация: create_post…")
    res = {}
    for attempt in range(1, CREATE_ATTEMPTS + 1):
        _do_javascript(jsmod.build_reset_result_only_js())
        _do_javascript(jsmod.build_create_post_js(params, payload.text, coords))
        res = _poll_result(expect_step="create", timeout_s=timeout_s)
        if res.get("ok"):
            break
        if res.get("status") == 400 and attempt < CREATE_ATTEMPTS:
            say(f"create_post: сервер ещё не готов (400), повтор {attempt + 1}…")
            time.sleep(CREATE_RETRY_PAUSE_SECONDS)
            continue
        break
    if not res.get("ok"):
        detail = res.get("responseHead") or res.get("error") or res.get("status")
        raise PublishRejectedError(str(detail)[:300])

    say("Сервер принял публикацию. Проверяю ленту /posts…")
    verified = verify_post_appeared(payload.channel_id, payload.text)

    return {
        "ok": True,
        "via": "api",
        "verified": verified,
        "has_image": payload.image is not None,
        "blob_id_len": blob_id_len,
        "used_auth": bool(res.get("usedAuth")),
        "crop": payload.crop,
    }


def verify_post_appeared(
    channel_id: str, text: str, *, timeout_s: float = 25.0
) -> bool:
    """Best-effort: fetch /posts in-page and look for the post text."""
    snippet = (text.strip().splitlines()[0] if text.strip() else "")[:60]
    if not snippet:
        return False
    _do_javascript(jsmod.build_reset_result_js())
    _do_javascript(jsmod.build_verify_post_js(channel_id, snippet))
    try:
        res = _poll_result(expect_step="verify", timeout_s=timeout_s)
    except PostsError:
        return False
    return bool(res.get("ok"))


def publish_post_ui(
    payload: PostPayload,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fallback DOM automation of the create-post dialog (text-only)."""
    _require_macos()
    if payload.image is not None:
        raise ImageAttachFailedError(
            "UI-путь не поддерживает картинку — используйте API-путь "
            "(--via api, он по умолчанию)"
        )
    say = progress or (lambda msg: None)
    say("UI-путь: открываю диалог записи…")
    open_posts_dialog(payload.channel_id)
    wait_for_dialog()
    click_placeholder()
    time.sleep(0.4)
    type_text(payload.text)
    time.sleep(0.3)
    say("UI-путь: нажимаю «Опубликовать»…")
    click_publish()
    time.sleep(2.0)
    check_server_error()
    return {"ok": True, "via": "ui", "verified": None, "has_image": False}


def publish_post(
    payload: PostPayload,
    *,
    via: str = "api",
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Dispatch to the requested publish path."""
    if via == "ui":
        return publish_post_ui(payload, progress=progress)
    return publish_post_api(payload, progress=progress)


def dry_run_plan(payload: PostPayload, *, via: str = "api") -> dict[str, Any]:
    """Return a human-readable plan without touching Safari."""
    wh = read_image_size(payload.image) if payload.image else None
    coords = None
    if payload.image:
        w, h = wh if wh else (None, None)
        coords = compute_preview_coordinates(w, h, crop=payload.crop)
    if via == "ui":
        steps = [
            "1. Открыть URL диалога в Safari",
            "2. Дождаться ytd-backstage-post-dialog-renderer",
            "3. Кликнуть #placeholder-area",
            "4. Вставить текст через execCommand/insertText (ASCII-safe)",
            "5. Кликнуть видимую кнопку «Опубликовать» (только текст)",
            "6. Проверить отсутствие баннера ошибки",
        ]
    else:
        steps = [
            "1. Safari: открыть/найти вкладку youtube.com (InnerTube-контекст)",
            "2. (если image) upload init → передача байтов → finalize (encryptedBlobId)",
            "3. create_post: commentText + imagesAttachment + previewCoordinates",
            "4. Проверка: пост виден на /posts (best-effort)",
        ]
    return {
        "dry_run": True,
        "via": via,
        "url": payload.posts_url() if payload.channel_id else None,
        "text_preview": payload.text[:200] + ("…" if len(payload.text) > 200 else ""),
        "text_len": len(payload.text),
        "image": str(payload.image) if payload.image else None,
        "image_size": f"{wh[0]}×{wh[1]}" if wh else None,
        "crop": payload.crop,
        "preview_coordinates": coords,
        "platform": platform.system(),
        "safari_available": _is_macos(),
        "steps": steps,
        "image_requirements": IMAGE_REQUIREMENTS_RU if payload.image else None,
    }
