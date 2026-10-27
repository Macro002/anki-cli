"""Anki's own web pages: the Statistics screen, Deck Options, Card Info and Congrats.

Anki Desktop builds these screens as one SvelteKit app that talks to the Rust backend by
POSTing protobuf messages to ``/_anki/<method>``. anki-cli serves the same app under
``[/profiles/<name>]/pages/`` and answers those calls from the collection, so the pages
look and behave exactly as on the desktop.

The app ships inside the ``aqt`` package (Anki's GUI), which depends on Qt. Rather than
installing Qt, anki-cli downloads the ``aqt`` wheel matching the installed ``anki`` once,
checks its SHA-256 against PyPI, and keeps only the web files (about 5 MB) in a cache
folder (``ANKICLI_PAGES_DIR``, default ``~/.cache/anki-cli/pages/<version>``). For
machines without internet access, ``anki-cli pages install --wheel aqt-….whl`` does the
same from a downloaded file.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .errors import ApiError

log = logging.getLogger("ankicli.pages")

WHEEL_PREFIX = "_aqt/data/web/sveltekit/"
ROUTES = ("graphs", "deck-options", "card-info", "congrats")
BRIDGE_PATH = "_ankicli/bridge.js"

# Backend methods the pages may call (Anki Desktop's list, minus the editor, importers and
# media, which these pages don't use). Called as ``col._backend.<name>_raw(bytes)``.
BACKEND_METHODS = {
    "i18n_resources", "get_deck_names", "get_deck", "get_config_bool", "get_notetype_names",
    # statistics
    "graphs", "get_graph_preferences", "set_graph_preferences", "card_stats", "get_review_logs",
    "congrats_info",
    # deck options and FSRS
    "get_deck_configs_for_update", "update_deck_configs", "get_ignored_before_count",
    "get_retention_workload", "compute_fsrs_params", "compute_optimal_retention",
    "evaluate_params_legacy", "get_optimal_retention_parameters", "simulate_fsrs_review",
    "simulate_fsrs_workload",
}
# Safe to call while a long operation (an FSRS optimization) holds the collection.
UNQUEUED_METHODS = {"latest_progress", "set_wants_abort"}
# Desktop window plumbing: acknowledged, and reported to an embedding page by the bridge.
WINDOW_METHODS = {"deck_options_ready", "deck_options_require_close"}

_lock = threading.Lock()
_CSP_META = re.compile(rb'<meta http-equiv="content-security-policy" content="[^"]*">')
_INLINE_SCRIPT = re.compile(rb"<script>(.*?)</script>", re.S)

# Defines the hooks the pages expect from the desktop window, and tells a parent frame
# (e.g. a web app embedding the page) when deck options were saved or want to close.
BRIDGE_JS = """\
(() => {
  const post = (event, detail) => {
    if (window.parent !== window) window.parent.postMessage({ source: "anki-cli", event, detail }, "*");
  };
  window.bridgeCommand = window.pycmd = (command, callback) => {
    post("bridgeCommand", command);
    if (callback) callback(null);
  };
  // What Anki Desktop injects into its web views: font, background and theme classes.
  // Dark mode: ?theme=dark or #night, else the system setting.
  const theme = new URLSearchParams(location.search).get("theme");
  const night = theme ? theme === "dark"
    : location.hash === "#night" || matchMedia("(prefers-color-scheme: dark)").matches;
  if (night) document.documentElement.classList.add("night-mode");
  document.documentElement.dataset.bsTheme = night ? "dark" : "light";
  const style = document.createElement("style");
  style.textContent = `
    html { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    html, body { background-color: var(--canvas); }
    button { font-family: inherit; }
    :root { --canvas: #f5f5f5; }
    :root[class*=night-mode] { --canvas: #2c2c2c; }
    textarea:focus, input:focus, input[type]:focus { outline: 0 none; border-color: #3b82f6; }`;
  document.head.appendChild(style);
  document.addEventListener("DOMContentLoaded", () => {
    document.body.classList.add(/Mac|iPhone|iPad/.test(navigator.platform) ? "isMac" : "isLin", "fancy");
    if (night) document.body.classList.add("nightMode", "night_mode");
  });
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const response = await realFetch(input, init);
    const url = typeof input === "string" ? input : input.url;
    const method = url.slice(url.lastIndexOf("/") + 1);
    if (response.ok && method === "updateDeckConfigs") post("deckOptionsSaved");
    if (method === "deckOptionsRequireClose") post("deckOptionsClose");
    if (method === "deckOptionsReady") post("deckOptionsReady");
    return response;
  };
})();
"""


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


CAMEL_METHODS = {camel(name): name for name in BACKEND_METHODS | UNQUEUED_METHODS | WINDOW_METHODS}


# -- the page bundle --------------------------------------------------------------------------

def anki_version() -> str:
    """The installed anki version as PyPI spells it (26.09.3 -> 26.9.3)."""
    from anki.buildinfo import version
    return ".".join(str(int(part)) if part.isdigit() else part for part in version.split("."))


def cache_dir() -> Path:
    env = os.environ.get("ANKICLI_PAGES_DIR")
    if env:
        return Path(env).expanduser()
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(cache) / "anki-cli" / "pages" / anki_version()


def installed() -> bool:
    return (cache_dir() / "index.html").is_file()


def _wheel_url(version: str) -> tuple[str, str]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/aqt/{version}/json", timeout=30) as response:
        release = json.load(response)
    for file in release.get("urls", []):
        if file.get("packagetype") == "bdist_wheel" and file["filename"].endswith(".whl"):
            return file["url"], file["digests"]["sha256"]
    raise ApiError("unsupportedCapability", f"PyPI has no aqt {version} wheel to take Anki's pages from.")


def install(wheel: str | os.PathLike | None = None) -> Path:
    """Extract the pages from an aqt wheel (downloaded from PyPI unless one is given)."""
    target = cache_dir()
    with _lock:
        if wheel is None and installed():
            return target
        if wheel is None:
            url, digest = _wheel_url(anki_version())
            log.info("downloading Anki's pages from %s", url)
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != digest:
                raise ApiError("internalError", "The downloaded aqt wheel doesn't match PyPI's checksum.")
            archive = zipfile.ZipFile(io.BytesIO(data))
        else:
            archive = zipfile.ZipFile(wheel)
        members = [name for name in archive.namelist()
                   if name.startswith(WHEEL_PREFIX) and not name.endswith("/")]
        if not any(name == WHEEL_PREFIX + "index.html" for name in members):
            raise ApiError("invalidParams", "That wheel doesn't contain Anki's web pages.")
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".pages-", dir=target.parent))
        try:
            for name in members:
                relative = name[len(WHEEL_PREFIX):]
                if relative.startswith("/") or ".." in Path(relative).parts:
                    continue
                path = staging / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
            if target.exists():
                shutil.rmtree(target)
            os.replace(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        _rewritten.clear()
        return target


def ensure() -> Path:
    if installed():
        return cache_dir()
    try:
        return install()
    except ApiError:
        raise
    except Exception as error:  # noqa: BLE001 - network problems
        raise ApiError("unsupportedCapability",
                       f"Anki's pages aren't installed and couldn't be downloaded ({error}). "
                       "Run `anki-cli pages install --wheel <aqt wheel>` to install them offline.") from error


# -- serving files ----------------------------------------------------------------------------

_rewritten: dict[tuple[str, str], bytes] = {}  # (prefix, path) -> body; prefixes come from clients


def _remember(key: tuple[str, str], body: bytes) -> bytes:
    if len(_rewritten) > 256:
        _rewritten.clear()
    _rewritten[key] = body
    return body


def _index(prefix: str) -> bytes:
    html = (cache_dir() / "index.html").read_bytes()
    quoted = prefix.encode()
    html = html.replace(b'"/_app/', b'"' + quoted + b"/_app/")
    html = html.replace(b'href="/favicon.ico"', b'href="data:,"')
    html = html.replace(b'base: ""', b'base: ' + json.dumps(prefix).encode())
    match = _INLINE_SCRIPT.search(html)
    script_hash = ""
    if match:
        digest = base64.b64encode(hashlib.sha256(match.group(1)).digest()).decode()
        script_hash = f" 'sha256-{digest}'"
    html = _CSP_META.sub(b"", html)
    bridge = f'<script src="{prefix}/{BRIDGE_PATH}"></script>'.encode()
    html = html.replace(b"<head>", b"<head>\n\t\t" + bridge, 1)
    # Kept in the tag (not a header) so a reverse proxy can't drop it.
    csp = f"script-src 'self'{script_hash}".encode()
    html = html.replace(b"<head>", b'<head>\n\t\t<meta http-equiv="content-security-policy" content="' + csp + b'">', 1)
    return html


def select_deck(host: Any, deck_id: str) -> None:
    """The Statistics page shows ``deck:current``; Anki Desktop selects the deck before opening it."""
    if not deck_id.isdigit():
        raise ApiError("invalidParams", "deck must be a deck id")

    def select(col: Any) -> None:
        if col.decks.get(int(deck_id), default=False) is None:
            raise ApiError("notFound", f"Deck not found: {deck_id}")
        col.decks.select(int(deck_id))
    host.run(select)


def file(path: str, prefix: str) -> tuple[bytes, str, bool] | None:
    """(body, content type, immutable) for a page or asset path below ``pages/``."""
    ensure()
    if path == BRIDGE_PATH:
        return BRIDGE_JS.encode(), "text/javascript", False
    route = path.split("/", 1)[0]
    if route in ROUTES:
        key = (prefix, "index.html")
        body = _rewritten.get(key) or _remember(key, _index(prefix))
        return body, "text/html; charset=utf-8", False
    if not path.startswith("_app/"):
        return None
    base = cache_dir().resolve()
    full = (base / path).resolve()
    if base not in full.parents or not full.is_file():
        return None
    content_type = {".mjs": "text/javascript", ".js": "text/javascript", ".css": "text/css",
                    ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
                    ".woff2": "font/woff2", ".ttf": "font/ttf"}.get(full.suffix, "application/octet-stream")
    body = full.read_bytes()
    if full.suffix == ".mjs" and b"`/_anki/" in body:
        key = (prefix, path)
        body = _rewritten.get(key) or _remember(key, body.replace(b"`/_anki/", f"`{prefix}/_anki/".encode()))
        return body, content_type, False
    return body, content_type, "/immutable/" in path


# -- backend calls ----------------------------------------------------------------------------

def call(host: Any, method: str, data: bytes) -> bytes:
    """Answer one ``/_anki/<method>`` call from a page."""
    name = CAMEL_METHODS.get(method)
    if name is None:
        if method in ("getConfigJson", "getProfileConfigJson", "getMetaJson"):
            return _get_setting(host, method, data)
        if method in ("setConfigJson", "setProfileConfigJson", "setMetaJson"):
            return _set_setting(host, method, data)
        raise ApiError("methodNotFound", f"{method} isn't available to pages.")
    if name in WINDOW_METHODS:
        return b""
    if name in UNQUEUED_METHODS:
        col = host.col or host.run(lambda col: col)
        return getattr(col._backend, f"{name}_raw")(data)
    return host.run(lambda col: getattr(col._backend, f"{name}_raw")(data))


def _get_setting(host: Any, method: str, data: bytes) -> bytes:
    from anki import generic_pb2
    request = generic_pb2.String()
    request.ParseFromString(data)
    if method == "getConfigJson":
        value = host.run(lambda col: col.get_config(request.val, None))
    else:  # desktop profile settings: per-page memory only
        value = host.state.setdefault("pageSettings", {}).get(request.val)
    return generic_pb2.Json(json=json.dumps(value).encode()).SerializeToString()


def _set_setting(host: Any, method: str, data: bytes) -> bytes:
    from anki import frontend_pb2
    request = frontend_pb2.SetSettingJsonRequest()
    request.ParseFromString(data)
    value = json.loads(request.value_json or b"null")
    if method == "setConfigJson":
        host.run(lambda col: col.set_config(request.key, value))
    else:
        host.state.setdefault("pageSettings", {})[request.key] = value
    return b""
