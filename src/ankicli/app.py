"""The application: profiles, method dispatch and operation records."""
from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from typing import Any, Callable

from . import __version__
from .errors import ApiError, from_exception
from .methods import METHODS, Method
from .profiles import Profiles
from .services import Services
from .util import timestamp

log = logging.getLogger("ankicli.app")

LIMITS = {"maxRequestBytes": 16 * 1024 * 1024, "maxBatchItems": 100, "maxPageSize": 1000,
          "operationRetentionSeconds": 3600, "maxActiveOperations": 100, "maxRetainedOperations": 1000,
          "maxMediaBytes": 64 * 1024 * 1024}
STRIPPED_PARAMS = ("session", "confirm")


class Operations:
    """Operation records for v1 methods that complete asynchronously in Anki Desktop.

    anki-cli finishes the work before replying, so records are terminal on creation;
    clients that poll ``operations.get`` see the final result immediately."""

    def __init__(self) -> None:
        self._records: dict[str, dict] = {}
        self._lock = threading.Lock()

    def record(self, method: str, session: str | None, result: Any = None, error: ApiError | None = None) -> dict:
        now = timestamp()
        operation_id = uuid.uuid4().hex
        record = {"operationId": operation_id, "method": method, "session": session, "createdAt": now,
                  "updatedAt": now, "cancellable": False, "progress": None}
        if error is None:
            record.update(state="succeeded", result=result)
        else:
            record.update(state="failed", error=error.record())
        with self._lock:
            self._prune()
            self._records[operation_id] = record
        return {"operationId": operation_id, "method": method, "session": session}

    def get(self, operation_id: str) -> dict:
        with self._lock:
            record = self._records.get(operation_id)
        if record is None:
            raise ApiError("notFound", f"Operation not found: {operation_id}")
        return dict(record)

    def cancel(self, operation_id: str) -> dict:
        self.get(operation_id)
        return {"requested": False}

    def _prune(self) -> None:
        cutoff = timestamp(time.time() - LIMITS["operationRetentionSeconds"])
        stale = [key for key, value in self._records.items() if value["updatedAt"] < cutoff]
        for key in stale:
            del self._records[key]
        while len(self._records) >= LIMITS["maxRetainedOperations"]:
            del self._records[next(iter(self._records))]


class App:
    def __init__(self, profiles: Profiles, *, api_key: str | None = None, allow_exit: bool = False,
                 cors_origins: list[str] | None = None, ignore_origins: list[str] | None = None):
        self.profiles = profiles
        self.secret = secrets.token_bytes(32)
        self.operations = Operations()
        self.api_key = api_key
        self.allow_exit = allow_exit
        self.cors_origins = list(cors_origins if cors_origins is not None else ["http://localhost"])
        self.ignore_origins = list(ignore_origins or [])
        self.started = time.time()
        self.on_exit: Callable[[], None] | None = None

    # -- collection calls ----------------------------------------------------------------------

    def call(self, method: str, params: dict | None = None, *, profile: str | None = None,
             validate: bool = True) -> Any:
        """Run one API method and return its result (operations return handles)."""
        spec = METHODS.get(method)
        if spec is None:
            raise ApiError("methodNotFound", f"Unknown method: {method}")
        params = dict(params or {})
        if validate:
            params = spec.validate(params, "")
        if spec.scope == "application":
            result = self.application(method, params)
        else:
            result = self.collection_call(spec, params, profile)
        if spec.completion == "operation" and method != "api.execute":
            session = self.profiles.host(profile).session if spec.scope == "collection" else None
            return self.operations.record(method, session, result)
        return result

    def collection_call(self, spec: Method, params: dict, profile: str | None = None) -> Any:
        host = self.profiles.host(profile)
        session = params.get("session")
        arguments = {key: value for key, value in params.items() if key not in STRIPPED_PARAMS}

        def run(col):
            if session is not None and session != host.session:
                raise ApiError("staleSession", "The collection session changed; call collection.get again.")
            services = Services(self, host, col)
            handler = services.handler(spec.name)
            if handler is None:
                raise ApiError("unsupportedCapability", f"No implementation for {spec.name}")
            if spec.undo in ("single", "grouped"):
                services.undo_target = None
            try:
                return handler(**arguments)
            except ApiError:
                raise
            except Exception as error:  # noqa: BLE001
                mapped = from_exception(error)
                if mapped.kind == "internalError":
                    log.exception("%s failed", spec.name)
                raise mapped from error
        return host.run(run)

    def with_services(self, fn: Callable[[Services], Any], profile: str | None = None) -> Any:
        """Run ``fn(services)`` on a collection's thread (used by the legacy layer)."""
        host = self.profiles.host(profile)
        return host.run(lambda col: fn(Services(self, host, col)))

    # -- application methods ---------------------------------------------------------------------

    def application(self, method: str, params: dict) -> Any:
        if method == "api.describe":
            return self.describe()
        if method == "api.execute":
            return self.operations.record("api.execute", None, self.execute(params["commands"]))
        if method == "access.requestPermission":
            return {"permission": "granted", "requireApiKey": bool(self.api_key)}
        if method == "profiles.list":
            return [{"name": name} for name in self.profiles.names()]
        if method == "profiles.getActive":
            active = self.profiles.active
            return {"name": active} if active else None
        if method == "profiles.switch":
            self.profiles.switch(params["name"])
            return self.call("collection.get", {}, profile=params["name"])
        if method == "profiles.create":
            self.profiles.create(params["name"])
            return {"name": params["name"].strip()}
        if method == "profiles.rename":
            self.profiles.rename(params["name"], params["newName"])
            return {"name": params["newName"].strip()}
        if method == "profiles.delete":
            self.profiles.delete(params["name"])
            return {"changed": True}
        if method == "operations.get":
            return self.operations.get(params["operationId"])
        if method == "operations.cancel":
            return self.operations.cancel(params["operationId"])
        if method == "application.exit":
            if not self.allow_exit:
                raise ApiError("unsupportedCapability", "Remote shutdown is disabled (start with --allow-exit).")
            if self.on_exit:
                threading.Timer(0.2, self.on_exit).start()
            return {"accepted": True}
        if method == "server.info":
            return self.info()
        raise ApiError("methodNotFound", f"Unknown method: {method}")

    def execute(self, commands: list[dict]) -> dict:
        items = []
        for index, command in enumerate(commands):
            method = command["method"]
            try:
                if method in ("api.execute", "application.exit", "profiles.switch"):
                    raise ApiError("invalidParams", f"{method} is not allowed inside api.execute.")
                result = self.call(method, command.get("params") or {})
                if isinstance(result, dict) and set(result) == {"operationId", "method", "session"}:
                    record = self.operations.get(result["operationId"])
                    if record["state"] != "succeeded":
                        items.append({"index": index, "method": method, "error": record["error"]})
                        continue
                    result = record["result"]
                items.append({"index": index, "method": method, "result": result})
            except Exception as error:  # noqa: BLE001
                items.append({"index": index, "method": method, "error": from_exception(error).record()})
        return {"items": items}

    def describe(self) -> dict:
        from anki.buildinfo import version as anki_version
        return {"apiMajor": 1, "ankiVersion": anki_version, "schema": {"server": "anki-cli", "version": __version__},
                "methods": [{"name": name, "available": True, "reason": None} for name in sorted(METHODS)],
                "limits": dict(LIMITS)}

    def info(self) -> dict:
        from anki.buildinfo import version as anki_version
        return {"name": "anki-cli", "version": __version__, "ankiVersion": anki_version,
                "uptimeSeconds": int(time.time() - self.started), "activeProfile": self.profiles.active,
                "profiles": self.profiles.names(),
                "openCollections": [host.name for host in self.profiles.open_hosts() if host.is_open()]}

    def close(self) -> None:
        self.profiles.close()
