"""Clients for anki-cli: over HTTP, or in-process without a server.

    from ankicli.client import Client
    anki = Client("http://127.0.0.1:8765")
    anki.call("decks.list")
    anki.legacy("addNote", note={...})

Both clients expose the same ``call``/``legacy`` interface; operations (methods
that return an operation handle) are resolved to their final result.
"""
from __future__ import annotations

import http.client
import itertools
import threading
import urllib.parse
from typing import Any

from .errors import ApiError
from .util import dumps, loads

OPERATION_KEYS = {"operationId", "method", "session"}


class RemoteError(ApiError):
    """An error returned by a server, carrying its v1 error record."""

    def __init__(self, record: dict):
        kind = (record.get("data") or {}).get("type", "internalError")
        super().__init__(kind, record.get("message", kind), (record.get("data") or {}).get("details"))
        self.record_value = record


class Client:
    def __init__(self, url: str = "http://127.0.0.1:8765", key: str | None = None, profile: str | None = None,
                 timeout: float = 300):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("url must start with http:// or https://")
        self.scheme, self.host, self.port = parsed.scheme, parsed.hostname, parsed.port
        self.base = parsed.path.rstrip("/")
        self.key = key
        self.profile = profile
        self.timeout = timeout
        self._ids = itertools.count(1)
        self._local = threading.local()

    # -- transport ---------------------------------------------------------------------------

    def _connection(self) -> http.client.HTTPConnection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            factory = http.client.HTTPSConnection if self.scheme == "https" else http.client.HTTPConnection
            conn = factory(self.host, self.port, timeout=self.timeout)
            conn.connect()
            import socket
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._local.conn = conn
        return conn

    def _path(self, path: str) -> str:
        prefix = f"/profiles/{urllib.parse.quote(self.profile)}" if self.profile else ""
        return self.base + prefix + path

    def request(self, path: str, body: bytes | None, method: str = "POST", headers: dict | None = None):
        headers = {"Content-Type": "application/json", **(headers or {})}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        for attempt in (1, 2):
            conn = self._connection()
            try:
                conn.request(method, self._path(path), body=body, headers=headers)
                response = conn.getresponse()
                data = response.read()
                if response.getheader("Connection", "").lower() == "close":
                    self.close()
                return response.status, data
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                # A kept-alive connection the server already closed; reconnect once.
                self.close()
                if attempt == 2:
                    raise
        raise RuntimeError("unreachable")

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # -- API ---------------------------------------------------------------------------------

    def call(self, method: str, **params: Any) -> Any:
        """Call a v1 (or anki-cli extension) method and return its final result."""
        request_id = next(self._ids)
        status, data = self.request("/api/v1", dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                                                      "params": params}))
        if status == 401:
            raise ApiError("authenticationRequired", "The server requires an API key (--key).")
        if status != 200:
            raise ApiError("ioError", f"HTTP {status}")
        reply = loads(data)
        if "error" in reply:
            raise RemoteError(reply["error"])
        result = reply["result"]
        if isinstance(result, dict) and set(result) == OPERATION_KEYS and method not in ("operations.get",):
            record = self.call("operations.get", operationId=result["operationId"])
            if record["state"] != "succeeded":
                raise RemoteError(record.get("error") or {"message": record["state"]})
            return record["result"]
        return result

    def legacy(self, action: str, **params: Any) -> Any:
        """Call a legacy Anki-Connect action (version 6) and return its result."""
        body: dict[str, Any] = {"action": action, "version": 6, "params": params}
        if self.key:
            body["key"] = self.key
        status, data = self.request("/", dumps(body))
        if status != 200:
            raise ApiError("ioError", f"HTTP {status}")
        reply = loads(data)
        if reply.get("error") is not None:
            raise ApiError("internalError", reply["error"])
        return reply["result"]

    def health(self) -> bool:
        try:
            status, _ = self.request("/health", None, method="GET")
            return status == 200
        except OSError:
            return False


class LocalClient:
    """The same interface without a server: opens the collection in this process."""

    def __init__(self, base: str | None = None, collection: str | None = None, profile: str | None = None):
        from .app import App
        from .host import HostOptions
        from .profiles import Profiles
        self.app = App(Profiles(base, collection=collection, options=HostOptions(backup_minutes=0)))
        self.profile = profile

    def call(self, method: str, **params: Any) -> Any:
        result = self.app.call(method, params, profile=self.profile)
        if isinstance(result, dict) and set(result) == OPERATION_KEYS:
            record = self.app.operations.get(result["operationId"])
            if record["state"] != "succeeded":
                raise RemoteError(record["error"])
            return record["result"]
        return result

    def legacy(self, action: str, **params: Any) -> Any:
        from .legacy import Legacy
        reply = Legacy(self.app).handle({"action": action, "version": 6, "params": params}, profile=self.profile)
        if reply.get("error") is not None:
            raise ApiError("internalError", reply["error"])
        return reply["result"]

    def close(self) -> None:
        self.app.close()
