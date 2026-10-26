"""Typed API errors shared by every protocol.

The error kinds and numeric codes match Anki-Connect's API v1 so that clients can
switch between Anki-Connect and anki-cli without changing their error handling.
"""
from __future__ import annotations

from typing import Any

ERROR_CODES: dict[str, int] = {
    "parseError": -32700,
    "invalidRequest": -32600,
    "methodNotFound": -32601,
    "invalidParams": -32602,
    "internalError": -32603,
    "notFound": 1001,
    "validationFailed": 1002,
    "editorConflict": 1003,
    "collectionUnavailable": 1004,
    "staleSession": 1005,
    "unsupportedCapability": 1006,
    "cancelled": 1007,
    "conflict": 1008,
    "invalidState": 1009,
    "busy": 1010,
    "authenticationRequired": 1011,
    "ioError": 1012,
    "invalidSearch": 1013,
    "staleCursor": 1014,
    "vetoed": 1015,
    "compatibilityError": 1016,
}

RETRYABLE = {"busy", "collectionUnavailable"}


class ApiError(Exception):
    """An error with a stable machine-readable kind."""

    def __init__(self, kind: str, message: str, details: Any = None):
        if kind not in ERROR_CODES:
            kind = "internalError"
        super().__init__(message)
        self.kind = kind
        self.details = details

    @property
    def code(self) -> int:
        return ERROR_CODES[self.kind]

    def record(self) -> dict:
        data: dict[str, Any] = {"type": self.kind}
        if self.details is not None:
            data["details"] = self.details if isinstance(self.details, dict) else {"value": self.details}
        if self.kind in RETRYABLE:
            data["retryable"] = True
        return {"code": self.code, "message": str(self) or self.kind, "data": data}


def not_found(message: str) -> ApiError:
    return ApiError("notFound", message)


def invalid(message: str) -> ApiError:
    return ApiError("invalidParams", message)


def from_exception(error: BaseException) -> ApiError:
    """Map native Anki and OS exceptions to API errors."""
    if isinstance(error, ApiError):
        return error
    try:
        from anki.errors import (
            BackendError,
            BackendIOError,
            CardTypeError,
            CustomStudyError,
            DBError,
            DeckRenameError,
            ExistsError,
            FilteredDeckError,
            Interrupted,
            InvalidInput,
            NetworkError,
            NotFoundError,
            SearchError,
            SyncError,
            SyncErrorKind,
            TemplateError,
            UndoEmpty,
        )
    except Exception:  # pragma: no cover - anki always importable in practice
        return ApiError("internalError", str(error) or type(error).__name__)
    message = str(error) or type(error).__name__
    if isinstance(error, NotFoundError):
        return ApiError("notFound", message)
    if isinstance(error, SearchError):
        return ApiError("invalidSearch", message)
    if isinstance(error, (TemplateError, CardTypeError, CustomStudyError, DeckRenameError)):
        return ApiError("validationFailed", message)
    if isinstance(error, ExistsError):
        return ApiError("conflict", message)
    if isinstance(error, FilteredDeckError):
        return ApiError("invalidState", message)
    if isinstance(error, UndoEmpty):
        return ApiError("invalidState", "Nothing to undo.")
    if isinstance(error, Interrupted):
        return ApiError("cancelled", message)
    if isinstance(error, SyncError):
        auth = getattr(error, "kind", None) == SyncErrorKind.AUTH
        return ApiError("authenticationRequired" if auth else "ioError", message)
    if isinstance(error, BackendIOError):
        return ApiError("ioError", message)
    if isinstance(error, NetworkError):
        return ApiError("ioError", message)
    if isinstance(error, InvalidInput):
        return ApiError("invalidParams", message)
    if isinstance(error, DBError):
        return ApiError("internalError", message)
    if isinstance(error, OSError):
        return ApiError("ioError", message)
    if isinstance(error, BackendError):
        return ApiError("internalError", message)
    return ApiError("internalError", message)
