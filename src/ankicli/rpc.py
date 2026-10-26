"""JSON-RPC 2.0 front end for the v1 API (``POST /api/v1``)."""
from __future__ import annotations

import logging
from typing import Any

from .errors import ApiError, from_exception
from .methods import METHODS

log = logging.getLogger("ankicli.rpc")
MAX_BATCH = 100


def reply(request_id: Any, result: Any = None, error: ApiError | None = None) -> dict:
    if error is not None:
        return {"jsonrpc": "2.0", "id": request_id, "error": error.record()}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def valid_id(value: Any) -> bool:
    return value is None or isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


class Rpc:
    def __init__(self, app):
        self.app = app

    def handle(self, payload: Any, profile: str | None = None) -> Any:
        """Return a response object, a list (batch), or None (notifications only)."""
        if isinstance(payload, list):
            if not payload:
                return reply(None, error=ApiError("invalidRequest", "Empty batch."))
            if len(payload) > MAX_BATCH:
                return reply(None, error=ApiError("invalidRequest", f"Batches are limited to {MAX_BATCH} requests."))
            responses = []
            for item in payload:
                if isinstance(item, list):
                    responses.append(reply(None, error=ApiError("invalidRequest", "Nested batches are not allowed.")))
                    continue
                response = self.single(item, profile)
                if response is not None:
                    responses.append(response)
            return responses or None
        return self.single(payload, profile)

    def single(self, request: Any, profile: str | None) -> dict | None:
        if not isinstance(request, dict):
            return reply(None, error=ApiError("invalidRequest", "Requests must be objects."))
        notification = "id" not in request
        request_id = request.get("id")
        if not valid_id(request_id):
            return reply(None, error=ApiError("invalidRequest", "Invalid request id."))
        if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str) or (
                "params" in request and not isinstance(request["params"], dict)) or (
                set(request) - {"jsonrpc", "id", "method", "params"}):
            if notification:
                return None
            return reply(request_id, error=ApiError("invalidRequest", "Invalid JSON-RPC request."))
        method = request["method"]
        params = request.get("params") or {}
        spec = METHODS.get(method)
        if notification:
            # Notifications may only read; side effects need an id and a reply.
            if spec is not None and spec.effect == "read":
                try:
                    self.app.call(method, params, profile=profile)
                except Exception:  # noqa: BLE001
                    pass
            return None
        if spec is None:
            return reply(request_id, error=ApiError("methodNotFound", f"Unknown method: {method}"))
        try:
            return reply(request_id, self.app.call(method, params, profile=profile))
        except Exception as error:  # noqa: BLE001
            mapped = from_exception(error)
            if mapped.kind == "internalError":
                log.exception("%s failed", method)
            return reply(request_id, error=mapped)
