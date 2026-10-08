"""JavaScript helpers for Safari Apple Events automation.

Critical rule (verified 07.10.2026): any non-ASCII text passed into
``osascript`` / ``do JavaScript`` MUST be ASCII-safe.  Cyrillic and other
Unicode characters break AppleScript encoding when embedded raw.
Use ``json.dumps(..., ensure_ascii=True)`` (or the helpers below) so every
non-ASCII code point becomes a ``\\uXXXX`` escape.
"""

from __future__ import annotations

import json
from typing import Final

# Selectors verified in manual session 07.10.2026
PLACEHOLDER_SELECTOR: Final = "#placeholder-area"
CONTENT_EDITABLE_SELECTOR: Final = 'div#contenteditable-root[contenteditable="true"]'
POST_BUTTON_SELECTOR: Final = "ytd-button-renderer#post-button button"
DIALOG_SELECTOR: Final = "ytd-backstage-post-dialog-renderer"
FILE_INPUT_SELECTOR: Final = 'input[type="file"][accept*="image"]'


def ascii_safe_js_string(text: str) -> str:
    """Return a JS string literal that is pure ASCII (\\uXXXX for non-ASCII).

    Example::
        ascii_safe_js_string("Привет") → '"\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442"'
    """
    return json.dumps(text, ensure_ascii=True)


def build_click_placeholder_js() -> str:
    """JS that clicks the placeholder area to expand the post form."""
    return f"""
(function() {{
  var el = document.querySelector({ascii_safe_js_string(PLACEHOLDER_SELECTOR)});
  if (!el) return {{ok: false, error: "placeholder not found"}};
  var rect = el.getBoundingClientRect();
  if (rect.height < 1) return {{ok: false, error: "placeholder not visible"}};
  el.click();
  return {{ok: true}};
}})();
""".strip()


def build_type_text_js(text: str) -> str:
    """JS that inserts text into the contenteditable root via execCommand.

    Uses insertText so YouTube's internal handlers see a real edit.
    Text is fully ASCII-escaped.
    """
    safe = ascii_safe_js_string(text)
    return f"""
(function() {{
  var root = document.querySelector({ascii_safe_js_string(CONTENT_EDITABLE_SELECTOR)});
  if (!root) return {{ok: false, error: "contenteditable not found"}};
  root.focus();
  var ok = document.execCommand("insertText", false, {safe});
  if (!ok) {{
    // fallback: synthetic InputEvent / paste-like
    root.textContent = {safe};
    root.dispatchEvent(new InputEvent("input", {{bubbles: true, data: {safe}}}));
  }}
  return {{ok: true, length: root.textContent.length}};
}})();
""".strip()


def build_publish_click_js() -> str:
    """JS that clicks the *visible, enabled* Publish button.

    DOM contains a hidden disabled clone (0x0).  We must pick the one with
    ``rect.width > 0 && !disabled``.
    """
    return f"""
(function() {{
  var buttons = document.querySelectorAll({ascii_safe_js_string(POST_BUTTON_SELECTOR)});
  var target = null;
  for (var i = 0; i < buttons.length; i++) {{
    var b = buttons[i];
    var rect = b.getBoundingClientRect();
    if (rect.width > 0 && !b.disabled) {{
      target = b;
      break;
    }}
  }}
  if (!target) return {{ok: false, error: "visible enabled publish button not found"}};
  target.click();
  return {{ok: true}};
}})();
""".strip()


def build_dialog_visible_js() -> str:
    """JS that checks whether the post dialog is visible (height > 50)."""
    return f"""
(function() {{
  var d = document.querySelector({ascii_safe_js_string(DIALOG_SELECTOR)});
  if (!d) return {{ok: false, visible: false}};
  var rect = d.getBoundingClientRect();
  return {{ok: true, visible: rect.height > 50, height: rect.height}};
}})();
""".strip()


def build_check_error_banner_js() -> str:
    """JS that looks for the server error toast «Не удалось опубликовать запись»."""
    # The exact Russian string is escaped so the whole script stays ASCII-safe.
    err_phrase = ascii_safe_js_string("Не удалось опубликовать запись")
    return f"""
(function() {{
  var body = document.body ? document.body.innerText : "";
  if (body.indexOf({err_phrase}) !== -1) {{
    return {{ok: false, error: "server rejected post"}};
  }}
  return {{ok: true}};
}})();
""".strip()


def build_file_input_exists_js() -> str:
    """JS that reports whether the image file input is present."""
    return f"""
(function() {{
  var inp = document.querySelector({ascii_safe_js_string(FILE_INPUT_SELECTOR)});
  return {{ok: true, present: !!inp}};
}})();
""".strip()
