"""JavaScript helpers for Safari Apple Events automation.

Critical rules (verified 07–08.10.2026):

* Any non-ASCII text passed into ``osascript`` / ``do JavaScript`` MUST be
  ASCII-safe: use ``json.dumps(..., ensure_ascii=True)`` (``ascii_safe_js_string``)
  so every non-ASCII code point becomes ``\\uXXXX``.
* ``do JavaScript`` must return **strings** (we return ``JSON.stringify(...)``)
  — JS objects do not survive the AppleScript bridge reliably.
* The publish button has a hidden disabled clone (0x0): pick the visible one.

Two flows are supported:

* **api** (primary): in-page fetch replay of the captured web API flow —
  upload init → finalize → ``backstage/create_post``.  No native dialogs,
  no Accessibility permission.
* **ui** (fallback): DOM automation of the create-post dialog (text-only).
"""

from __future__ import annotations

import json
from typing import Any, Final

# Selectors verified in manual session 07.10.2026
PLACEHOLDER_SELECTOR: Final = "#placeholder-area"
CONTENT_EDITABLE_SELECTOR: Final = 'div#contenteditable-root[contenteditable="true"]'
POST_BUTTON_SELECTOR: Final = "ytd-button-renderer#post-button button"
DIALOG_SELECTOR: Final = "ytd-backstage-post-dialog-renderer"
FILE_INPUT_SELECTOR: Final = 'input[type="file"][accept*="image"]'

# Window variables used to carry async results between do-JavaScript calls
RESULT_VAR: Final = "__AYH_POST_RESULT"
B64_VAR: Final = "__AYH_IMG_B64"
BLOB_VAR: Final = "__AYH_BLOBID"


def ascii_safe_js_string(text: str) -> str:
    """Return a JS string literal that is pure ASCII (\\uXXXX for non-ASCII).

    Example::
        ascii_safe_js_string("Привет") → '"\\u041f\\u0440\\u0438\\u0432\\u0435\\u0442"'
    """
    return json.dumps(text, ensure_ascii=True)


# ---------------------------------------------------------------------------
# UI flow builders (fallback, text-only)
# ---------------------------------------------------------------------------


def build_click_placeholder_js() -> str:
    """JS that clicks the placeholder area to expand the post form."""
    return f"""
(function() {{
  var el = document.querySelector({ascii_safe_js_string(PLACEHOLDER_SELECTOR)});
  if (!el) return JSON.stringify({{ok: false, error: "placeholder not found"}});
  var rect = el.getBoundingClientRect();
  if (rect.height < 1) return JSON.stringify({{ok: false, error: "placeholder not visible"}});
  el.click();
  return JSON.stringify({{ok: true}});
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
  if (!root) return JSON.stringify({{ok: false, error: "contenteditable not found"}});
  root.focus();
  var ok = document.execCommand("insertText", false, {safe});
  if (!ok) {{
    var sel = window.getSelection();
    sel.removeAllRanges();
    var rng = document.createRange();
    rng.selectNodeContents(root);
    sel.addRange(rng);
    document.execCommand("delete");
    document.execCommand("insertText", false, {safe});
  }}
  var len = (root.innerText || "").length;
  return JSON.stringify({{ok: len > 0, length: len}});
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
  if (!target) return JSON.stringify({{
    ok: false,
    error: "visible enabled publish button not found"
  }});
  target.click();
  return JSON.stringify({{ok: true}});
}})();
""".strip()


def build_dialog_visible_js() -> str:
    """JS that checks whether the post dialog is visible (height > 50)."""
    return f"""
(function() {{
  var d = document.querySelector({ascii_safe_js_string(DIALOG_SELECTOR)});
  if (!d) return JSON.stringify({{ok: false, visible: false}});
  var rect = d.getBoundingClientRect();
  return JSON.stringify({{ok: true, visible: rect.height > 50, height: Math.round(rect.height)}});
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
    return JSON.stringify({{ok: false, error: "server rejected post"}});
  }}
  return JSON.stringify({{ok: true}});
}})();
""".strip()


def build_file_input_exists_js() -> str:
    """JS that reports whether the image file input is present."""
    return f"""
(function() {{
  var inp = document.querySelector({ascii_safe_js_string(FILE_INPUT_SELECTOR)});
  return JSON.stringify({{ok: true, present: !!inp}});
}})();
""".strip()


# ---------------------------------------------------------------------------
# API flow builders (primary): in-page fetch replay of the captured flow
# ---------------------------------------------------------------------------


def build_reset_result_js() -> str:
    """JS that clears the async-result slots before a new step."""
    return f"""
(function() {{
  window.{RESULT_VAR} = "";
  window.{B64_VAR} = "";
  window.{BLOB_VAR} = "";
  return "reset";
}})();
""".strip()


def build_get_result_js() -> str:
    """JS that returns the stored async result (a JSON string) or empty."""
    return f"""
(function() {{
  return String(window.{RESULT_VAR} || "");
}})();
""".strip()


def build_page_ready_js() -> str:
    """JS that checks the page has an InnerTube context (ytcfg) for API calls."""
    return """
(function() {
  var has = false;
  try {
    has = !!(window.ytcfg && window.ytcfg.get && window.ytcfg.get("INNERTUBE_CONTEXT"));
  } catch (e) {}
  return JSON.stringify({ok: has, href: String(location.href).slice(0, 140)});
})();
""".strip()


def build_upload_init_js(channel_id: str, content_length: int) -> str:
    """JS that starts the resumable image upload (step 1 of the captured flow)."""
    ch = ascii_safe_js_string(channel_id)
    return f"""
(function() {{
  window.{RESULT_VAR} = "";
  function done(o) {{ window.{RESULT_VAR} = JSON.stringify(o); }}
  try {{
    fetch("/channel_image_upload/posts", {{
      method: "POST",
      credentials: "same-origin",
      headers: {{
        "X-YouTube-ChannelId": {ch},
        "X-Goog-Upload-Header-Content-Length": String({int(content_length)}),
        "X-Goog-Upload-Protocol": "resumable",
        "X-Goog-Upload-Command": "start",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
      }}
    }}).then(function(resp) {{
      var url = "";
      try {{ url = resp.headers.get("X-Goog-Upload-URL") || ""; }} catch (e) {{}}
      done({{step: "init", ok: resp.status === 200 && !!url, status: resp.status, uploadUrl: url}});
    }}).catch(function(e) {{ done({{step: "init", ok: false, error: String(e)}}); }});
  }} catch (e) {{ done({{step: "init", ok: false, error: String(e)}}); }}
  return "started";
}})();
""".strip()


def build_upload_chunk_js(chunk_b64: str, *, first: bool) -> str:
    """JS that appends a base64 chunk of the image to the page-side buffer."""
    s = ascii_safe_js_string(chunk_b64)
    init = '""' if first else f'String(window.{B64_VAR} || "")'
    return f"""
(function() {{
  window.{B64_VAR} = {init} + {s};
  return String(window.{B64_VAR}.length);
}})();
""".strip()


def build_upload_finalize_js(channel_id: str, upload_url: str) -> str:
    """JS that uploads the buffered image bytes and finalizes the upload."""
    ch = ascii_safe_js_string(channel_id)
    uu = ascii_safe_js_string(upload_url)
    return f"""
(function() {{
  window.{RESULT_VAR} = "";
  function done(o) {{ window.{RESULT_VAR} = JSON.stringify(o); }}
  try {{
    var b64 = String(window.{B64_VAR} || "");
    if (!b64) {{
      done({{step: "finalize", ok: false, error: "empty image buffer"}});
      return "started";
    }}
    var bin = atob(b64);
    var arr = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) {{ arr[i] = bin.charCodeAt(i) & 0xFF; }}
    fetch({uu}, {{
      method: "POST",
      credentials: "same-origin",
      headers: {{
        "X-YouTube-ChannelId": {ch},
        "X-Goog-Upload-Command": "upload, finalize",
        "X-Goog-Upload-Offset": "0",
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
      }},
      body: arr
    }}).then(function(resp) {{
      return resp.text().then(function(t) {{ return {{status: resp.status, text: t}}; }});
    }}).then(function(r) {{
      var blobId = "";
      try {{ blobId = String((JSON.parse(r.text) || {{}}).encryptedBlobId || ""); }} catch (e) {{}}
      window.{BLOB_VAR} = blobId;
      done({{step: "finalize", ok: r.status === 200 && !!blobId,
        status: r.status, blobIdLen: blobId.length}});
    }}).catch(function(e) {{ done({{step: "finalize", ok: false, error: String(e)}}); }});
  }} catch (e) {{ done({{step: "finalize", ok: false, error: String(e)}}); }}
  return "started";
}})();
""".strip()


def build_create_post_js(
    params_b64: str,
    text: str,
    coords: dict[str, Any],
) -> str:
    """JS that publishes the post via ``backstage/create_post``.

    Mirrors the captured web-client request (08.10.2026): sends
    ``x-goog-authuser`` (``SESSION_INDEX``), ``x-goog-visitor-id``
    (``VISITOR_DATA``), ``x-youtube-bootstrap-logged-in`` and an
    ``authorization`` header computed up-front exactly like the web client
    (reversed from the kevlar bundle):

    * cookie = ``SAPISID`` or (fallback) ``__Secure-3PAPISID``;
    * ``sha1("<USER_SESSION_ID> <ts> <cookie> https://www.youtube.com")``
      when ``USER_SESSION_ID`` is present, otherwise ``sha1("<cookie>
      https://www.youtube.com")``;
    * value = ``SAPISIDHASH <ts>_<hash>_u SAPISID3PHASH <ts>_<hash>_u``
      (or ``SAPISIDHASH <hash> SAPISID3PHASH <hash>`` without the session id).

    If the server still answers 401/403, retries once **without** the
    authorization header (cookies-only fallback).

    The JSON body is gzip-compressed via ``CompressionStream`` when available
    (same as the web client); falls back to a plain JSON body.
    """
    p = ascii_safe_js_string(params_b64)
    t = ascii_safe_js_string(text)
    c = json.dumps(coords, ensure_ascii=True)
    return f"""
(function() {{
  window.{RESULT_VAR} = "";
  function done(o) {{ window.{RESULT_VAR} = JSON.stringify(o); }}
  function cfg(key) {{
    try {{ return (window.ytcfg && window.ytcfg.get) ? window.ytcfg.get(key) : undefined; }}
    catch (e) {{ return undefined; }}
  }}
  function buildHeaders(authHeader) {{
    var headers = {{
      "content-type": "application/json",
      "x-origin": "https://www.youtube.com",
      "x-youtube-client-name": "1",
      "x-youtube-client-version": String(cfg("INNERTUBE_CLIENT_VERSION") || ""),
      "x-youtube-bootstrap-logged-in": "true"
    }};
    var authuser = cfg("SESSION_INDEX");
    if (authuser !== undefined && authuser !== null && authuser !== "") {{
      headers["x-goog-authuser"] = String(authuser);
    }}
    var visitor = cfg("VISITOR_DATA");
    if (visitor) {{ headers["x-goog-visitor-id"] = String(visitor); }}
    if (authHeader) {{ headers["authorization"] = authHeader; }}
    return headers;
  }}
  function send(authHeader, retried) {{
    try {{
      var payload = {{
        context: (window.ytcfg && window.ytcfg.get) ? window.ytcfg.get("INNERTUBE_CONTEXT") : null,
        createBackstagePostParams: {p},
        commentText: {t},
        imagesAttachment: {{ imagesData: [{{
          encryptedBlobId: String(window.{BLOB_VAR} || ""),
          previewCoordinates: {c}
        }}] }}
      }};
      var raw = new TextEncoder().encode(JSON.stringify(payload));
      var headers = buildHeaders(authHeader);
      function finish(bodyBytes, gz) {{
        if (gz) {{ headers["content-encoding"] = "gzip"; }}
        fetch("/youtubei/v1/backstage/create_post?prettyPrint=false", {{
          method: "POST",
          credentials: "same-origin",
          headers: headers,
          body: bodyBytes
        }}).then(function(resp) {{
          return resp.text().then(function(t2) {{ return {{status: resp.status, text: t2}}; }});
        }}).then(function(r) {{
          if ((r.status === 401 || r.status === 403) && authHeader && !retried) {{
            send("", true);
            return;
          }}
          done({{step: "create", ok: r.status === 200, status: r.status,
            usedAuth: !!authHeader, responseHead: String(r.text || "").slice(0, 300)}});
        }}).catch(function(e) {{ done({{step: "create", ok: false, error: String(e)}}); }});
      }}
      if (typeof CompressionStream !== "undefined") {{
        try {{
          var cs = new CompressionStream("gzip");
          var w = cs.writable.getWriter();
          w.write(raw);
          w.close();
          var chunks = [];
          var reader = cs.readable.getReader();
          var pump = function() {{
            reader.read().then(function(res) {{
              if (res.done) {{
                var total = 0;
                chunks.forEach(function(c2) {{ total += c2.length; }});
                var out = new Uint8Array(total);
                var off = 0;
                chunks.forEach(function(c2) {{ out.set(c2, off); off += c2.length; }});
                finish(out, true);
              }} else {{ chunks.push(res.value); pump(); }}
            }}).catch(function() {{ finish(raw, false); }});
          }};
          pump();
          return;
        }} catch (e) {{ finish(raw, false); return; }}
      }}
      finish(raw, false);
    }} catch (e) {{ done({{step: "create", ok: false, error: String(e)}}); }}
  }}
  function buildAuth() {{
    return new Promise(function(resolve) {{
      try {{
        var m = document.cookie.match(/(?:^|;\\s*)(?:__Secure-3PAPISID|SAPISID)=([^;]+)/);
        var cookie = m ? decodeURIComponent(m[1]) : "";
        var usid = String(cfg("USER_SESSION_ID") || "");
        if (!cookie || !(window.crypto && crypto.subtle)) {{ resolve(""); return; }}
        var ts = Math.floor(Date.now() / 1000);
        var source = usid
          ? usid + " " + ts + " " + cookie + " https://www.youtube.com"
          : cookie + " https://www.youtube.com";
        crypto.subtle.digest("SHA-1", new TextEncoder().encode(source))
          .then(function(hash) {{
            var hex = "";
            var b = new Uint8Array(hash);
            for (var i = 0; i < b.length; i++) {{ hex += ("0" + b[i].toString(16)).slice(-2); }}
            resolve(usid
              ? "SAPISIDHASH " + ts + "_" + hex + "_u SAPISID3PHASH " + ts + "_" + hex + "_u"
              : "SAPISIDHASH " + hex + " SAPISID3PHASH " + hex);
          }})
          .catch(function() {{ resolve(""); }});
      }} catch (e) {{ resolve(""); }}
    }});
  }}
  buildAuth().then(function(auth) {{ send(auth, false); }});
  return "started";
}})();
""".strip()


def build_verify_post_js(channel_id: str, snippet: str) -> str:
    """JS that fetches the channel /posts page and looks for the post snippet.

    Checks both the raw snippet and its JSON-escaped form (ytInitialData may
    contain either).
    """
    ch = ascii_safe_js_string(channel_id)
    sn = ascii_safe_js_string(snippet)
    sn_escaped = ascii_safe_js_string(json.dumps(snippet, ensure_ascii=True)[1:-1])
    return f"""
(function() {{
  window.{RESULT_VAR} = "";
  function done(o) {{ window.{RESULT_VAR} = JSON.stringify(o); }}
  fetch("/channel/" + {ch} + "/posts", {{credentials: "same-origin"}})
    .then(function(r) {{ return r.text(); }})
    .then(function(t) {{
      var hit = t.indexOf({sn}) !== -1 || t.indexOf({sn_escaped}) !== -1;
      done({{step: "verify", ok: hit, pageLen: t.length}});
    }})
    .catch(function(e) {{ done({{step: "verify", ok: false, error: String(e)}}); }});
  return "started";
}})();
""".strip()
