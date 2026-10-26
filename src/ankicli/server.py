"""HTTP transport: the legacy endpoint, JSON-RPC v1, media files and health checks.

Routes (all may be prefixed with ``/profiles/<name>`` to target a profile other
than the active one, which lets one server host many collections at once):

    POST /            legacy Anki-Connect actions (GET with a JSON body also works)
    POST /api/v1      JSON-RPC 2.0
    GET  /media/<f>   a media file of the collection (Range requests supported)
    GET  /health      liveness probe
"""
from __future__ import annotations

import hmac
import logging
import mimetypes
import os
import re
import signal
import socket
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import __version__
from .app import App
from .errors import ApiError
from .legacy import API_VERSION, Legacy
from .rpc import Rpc, reply
from .util import dumps, loads

log = logging.getLogger("ankicli.server")

MAX_LEGACY_BYTES = 128 * 1024 * 1024
MAX_RPC_BYTES = 16 * 1024 * 1024
LOCAL_PREFIXES = ("http://127.0.0.1:", "https://127.0.0.1:", "chrome-extension://", "moz-extension://",
                  "safari-web-extension://")
PROFILE_PATH = re.compile(r"^/profiles/([^/]+)(/.*)?$")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"anki-cli/{__version__}"
    server: "Server"
    # Buffer the response so headers and body leave in one segment, and disable
    # Nagle: otherwise small keep-alive replies stall ~40 ms on delayed ACKs.
    wbufsize = -1

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        log.debug("%s - %s", self.address_string(), format % args)

    # -- helpers ------------------------------------------------------------------------------

    def origin_allowed(self) -> tuple[bool, str]:
        origins = self.server.app.cors_origins
        origin = self.headers.get("Origin", "")
        if "*" in origins:
            return True, "*"
        allowed = not origin or origin in origins
        if "http://localhost" in origins and (origin.startswith(LOCAL_PREFIXES)
                                              or origin in ("http://127.0.0.1", "https://127.0.0.1")):
            allowed = True
        return allowed, origin if allowed and origin else "http://localhost"

    def send_body(self, status: int, body: bytes = b"", content_type: str = "application/json",
                  extra: dict | None = None) -> None:
        _, cors = self.origin_allowed()
        if self.command == "OPTIONS" and self.headers.get("Origin"):
            # Preflight carries no body, so it can't be a permission request; let the
            # browser send the POST, which is still checked for origin and key.
            cors = self.headers["Origin"]
        self.send_response(status)
        if body or status == 200:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", cors)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Anki-Profile, *")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)
        self.wfile.flush()

    def read_body(self, limit: int) -> bytes | None:
        if "Transfer-Encoding" in self.headers:
            self.send_body(400)
            return None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_body(400)
            return None
        if length < 0:
            self.send_body(400)
            return None
        if length > limit:
            self.send_body(413)
            self.close_connection = True
            return None
        return self.rfile.read(length) if length else b""

    def route(self) -> tuple[str | None, str, dict]:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        profile = self.headers.get("X-Anki-Profile") or None
        match = PROFILE_PATH.match(path)
        if match:
            profile = urllib.parse.unquote(match.group(1))
            path = match.group(2) or "/"
        query = dict(urllib.parse.parse_qsl(parsed.query))
        return profile, path, query

    def bearer_ok(self, query: dict | None = None) -> bool:
        key = self.server.app.api_key
        if key is None:
            return True
        header = self.headers.get("Authorization", "")
        if hmac.compare_digest(header.encode(), f"Bearer {key}".encode()):
            return True
        return bool(query and hmac.compare_digest(str(query.get("key", "")).encode(), key.encode()))

    # -- methods ---------------------------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        extra = {}
        if self.headers.get("Access-Control-Request-Private-Network") == "true":
            extra["Access-Control-Allow-Private-Network"] = "true"
        self.send_body(200, extra=extra)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_GET(self) -> None:  # noqa: N802
        profile, path, query = self.route()
        if path == "/health":
            self.send_body(200, dumps({"status": "ok", "version": __version__}))
        elif path.startswith("/media/"):
            self.serve_media(profile, urllib.parse.unquote(path[len("/media/"):]), query)
        elif path == "/":
            self.legacy(profile)
        elif path == "/api/v1":
            self.send_body(405)
        else:
            self.send_body(404)

    def do_POST(self) -> None:  # noqa: N802
        profile, path, _ = self.route()
        if path == "/":
            self.legacy(profile)
        elif path == "/api/v1":
            self.rpc(profile)
        else:
            self.send_body(404)

    # -- endpoints -------------------------------------------------------------------------------

    def legacy(self, profile: str | None) -> None:
        allowed, _ = self.origin_allowed()
        body = self.read_body(MAX_LEGACY_BYTES)
        if body is None:
            return
        if not body.strip():
            if not allowed:
                self.send_body(403)
                return
            self.send_body(200, dumps({"apiVersion": f"AnkiConnect v.{API_VERSION}"}))
            return
        try:
            request = loads(body)
        except ValueError:
            if not allowed:
                self.send_body(403)
                return
            self.send_body(200, dumps({"result": None, "error": "Invalid JSON."}))
            return
        permission = isinstance(request, dict) and request.get("action") == "requestPermission"
        if not allowed and not permission:
            self.send_body(403)
            return
        if permission:
            params = request.get("params") if isinstance(request.get("params"), dict) else {}
            request = {**request, "params": {**params, "origin": self.headers.get("Origin", ""),
                                             "allowed": allowed}}
        response = self.server.legacy.handle(request, profile=profile)
        self.send_body(200, dumps(response))

    def rpc(self, profile: str | None) -> None:
        allowed, _ = self.origin_allowed()
        body = self.read_body(MAX_RPC_BYTES)
        if body is None:
            return
        try:
            payload = loads(body)
        except ValueError:
            if not allowed:
                self.send_body(403)
                return
            self.send_body(200, dumps(reply(None, error=ApiError("parseError", "Invalid JSON."))))
            return
        permission = isinstance(payload, dict) and payload.get("method") == "access.requestPermission"
        if not allowed and not permission:
            self.send_body(403)
            return
        if not permission and not self.bearer_ok():
            self.send_body(401)
            return
        if permission and isinstance(payload, dict) and not allowed:
            self.send_body(200, dumps({"jsonrpc": "2.0", "id": payload.get("id"),
                                       "result": {"permission": "denied", "requireApiKey": bool(self.server.app.api_key)}}))
            return
        response = self.server.rpc.handle(payload, profile)
        if response is None:
            self.send_body(204)
        else:
            self.send_body(200, dumps(response))

    def serve_media(self, profile: str | None, name: str, query: dict) -> None:
        if not self.bearer_ok(query):
            self.send_body(401)
            return
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\0" in name:
            self.send_body(404)
            return
        try:
            host = self.server.app.profiles.host(profile or query.get("profile"))
            directory = host.run(lambda col: col.media.dir())
        except ApiError:
            self.send_body(404)
            return
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            self.send_body(404)
            return
        size = os.path.getsize(path)
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = 200
        ranged = self.headers.get("Range", "")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", ranged.strip()) if ranged else None
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            if start > end or start >= size:
                self.send_body(416, extra={"Content-Range": f"bytes */{size}"})
                return
            status = 206
        with open(path, "rb") as file:
            file.seek(start)
            data = file.read(end - start + 1)
        extra = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400"}
        if status == 206:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.send_body(status, data, content_type, extra)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128

    def __init__(self, address: tuple[str, int], app: App):
        super().__init__(address, Handler)
        self.app = app
        self.legacy = Legacy(app)
        self.rpc = Rpc(app)

    def handle_error(self, request: Any, client_address: Any) -> None:
        log.exception("unhandled error serving %s", client_address)


def serve(app: App, host: str = "127.0.0.1", port: int = 8765, ready: threading.Event | None = None) -> None:
    """Serve until SIGINT/SIGTERM, then close every collection cleanly."""
    server = Server((host, port), app)
    stopping = threading.Event()

    def shutdown(*_: Any) -> None:
        if not stopping.is_set():
            stopping.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    app.on_exit = shutdown
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)
    log.info("anki-cli %s listening on http://%s:%s", __version__, host, server.server_address[1])
    if ready is not None:
        ready.set()
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        started = time.monotonic()
        app.close()
        log.info("collections closed in %.2fs", time.monotonic() - started)
