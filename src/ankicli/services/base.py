"""Shared machinery for the native service layer."""
from __future__ import annotations

import copy
import hashlib
import hmac
import secrets
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable

from ..errors import ApiError, from_exception
from ..util import entity_id, summary, timestamp

if TYPE_CHECKING:  # pragma: no cover
    from anki.collection import Collection

    from ..app import App
    from ..host import CollectionHost

TYPES = {0: "new", 1: "learning", 2: "review", 3: "relearning"}
QUEUES = {0: "new", 1: "learning", 2: "review", 3: "dayLearning", 4: "preview",
          -1: "suspended", -2: "buriedByScheduler", -3: "buriedByUser"}
RATINGS = ("again", "hard", "good", "easy")
KINDS = ("learning", "review", "relearning", "filtered", "manual", "rescheduled")

CURSOR_TTL = 600
MAX_CURSORS = 100
MAX_CURSOR_IDS = 1_000_000


class CursorStore:
    """Snapshots of ordered search results, consumed page by page."""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _prune(self) -> None:
        now = time.monotonic()
        for key in [k for k, v in self._items.items() if v["expires"] < now]:
            del self._items[key]
        while len(self._items) > MAX_CURSORS:
            oldest = min(self._items, key=lambda k: self._items[k]["created"])
            del self._items[oldest]

    def page(self, ids: list[int] | None, method: str, params: dict, session: str,
             exists: Callable[[list[int]], set[int]] | None = None) -> dict:
        limit = params.get("limit") or 100
        fingerprint = repr(sorted((k, repr(v)) for k, v in params.items() if k not in ("cursor", "session")))
        with self._lock:
            self._prune()
            if params.get("cursor"):
                entry = self._items.pop(params["cursor"], None)
                if (entry is None or entry["method"] != method or entry["session"] != session
                        or entry["fingerprint"] != fingerprint):
                    raise ApiError("staleCursor", "The cursor expired or does not match this request.")
                ids = entry["ids"]
            assert ids is not None
            if len(ids) > MAX_CURSOR_IDS:
                raise ApiError("busy", "The result is too large to paginate; narrow the search.")
            chunk, rest = ids[:limit], ids[limit:]
            if exists is not None and chunk:
                present = exists(chunk)
                chunk = [value for value in chunk if value in present]
            cursor = None
            if rest:
                cursor = secrets.token_urlsafe(18)
                now = time.monotonic()
                self._items[cursor] = {"ids": rest, "method": method, "session": session,
                                       "fingerprint": fingerprint, "expires": now + CURSOR_TTL, "created": now}
        return {"ids": [str(value) for value in chunk], "nextCursor": cursor}


class HostState:
    """Protocol state that belongs to one open collection."""

    def __init__(self) -> None:
        self.cursors = CursorStore()
        self.reviewer: dict[str, Any] = {"active": False}
        self.browser: dict[str, Any] = {"open": False, "query": "", "sort": None,
                                        "selectedCardIds": [], "selectedNoteIds": [], "mode": "cards"}
        self.editors: dict[str, dict] = {}
        self.timer_started: dict[int, float] = {}


def host_state(host: "CollectionHost") -> HostState:
    state = host.state.get("protocol")
    if state is None:
        state = host.state["protocol"] = HostState()
    return state


class Base:
    """Context for one method call: the app, the host and its open collection."""

    def __init__(self, app: "App", host: "CollectionHost", col: "Collection"):
        self.app = app
        self.host = host
        self.col = col
        self.state = host_state(host)
        self.undo_target: int | None | bool = False  # False: no grouping

    # -- identity --------------------------------------------------------------------------

    @property
    def session(self) -> str:
        return self.host.session

    @property
    def profile(self) -> str:
        return self.host.name

    # -- tokens ----------------------------------------------------------------------------

    def token(self, kind: str, parts: Any) -> str:
        payload = repr((kind, self.session, parts)).encode()
        digest = hmac.new(self.app.secret, payload, hashlib.sha256).hexdigest()[:40]
        return f"{kind[:3]}.{digest}"

    def check_token(self, token: str, kind: str, parts: Any, message: str = "The state token is stale.") -> None:
        if not isinstance(token, str) or not hmac.compare_digest(token, self.token(kind, parts)):
            raise ApiError("conflict", message)

    # -- change tracking -------------------------------------------------------------------

    def change(self, result: Any = None) -> Any:
        """Record a native write; merges undo entries inside grouped methods."""
        if self.undo_target is not False:
            if self.undo_target is None:
                self.undo_target = self.col.undo_status().last_step
            else:
                try:
                    self.col.merge_undo_entries(self.undo_target)
                except Exception:
                    pass
        return result

    # -- lookups ---------------------------------------------------------------------------

    def note(self, id: str | int):
        nid = id if isinstance(id, int) else entity_id(id)
        try:
            return self.col.get_note(nid)
        except Exception as error:
            raise ApiError("notFound", f"Note was not found: {nid}") from error

    def card(self, id: str | int):
        cid = id if isinstance(id, int) else entity_id(id)
        try:
            return self.col.get_card(cid)
        except Exception as error:
            raise ApiError("notFound", f"Card was not found: {cid}") from error

    def resolve(self, reference: dict, kind: str) -> dict:
        """Look up a deck or note type by ``{"id"}`` or ``{"name"}`` (copy of the dict)."""
        if kind == "deck":
            manager = self.col.decks
        elif kind == "noteType":
            manager = self.col.models
        else:
            raise ValueError(kind)
        if "id" in reference:
            ident = entity_id(reference["id"]) if isinstance(reference["id"], str) else int(reference["id"])
            value = manager.get(ident, default=False) if kind == "deck" else manager.get(ident)
        else:
            value = manager.by_name(reference["name"])
        if not value:
            label = "Deck" if kind == "deck" else "Note type"
            shown = reference.get("name", reference.get("id"))
            raise ApiError("notFound", f"{label} not found: {shown}")
        return copy.deepcopy(value)

    def summary(self, value: Any) -> dict:
        return summary(value)

    def deck_summary(self, did: int) -> dict:
        deck = self.col.decks.get(did, default=False)
        if not deck:
            raise ApiError("notFound", f"Deck not found: {did}")
        return {"id": str(deck["id"]), "name": deck["name"]}

    def many(self, values: list, function: Callable[[Any], Any], deduplicate: bool = False) -> dict:
        """Independent per-item results in the v1 ``{"items": [...]}`` envelope."""
        items, cache = [], {}
        for index, value in enumerate(values):
            key = repr(value)
            if deduplicate and key in cache:
                items.append({"index": index, **copy.deepcopy(cache[key])})
                continue
            try:
                entry = {"result": function(value)}
            except Exception as error:  # noqa: BLE001 - item errors are reported, not raised
                entry = {"error": from_exception(error).record()}
            cache[key] = entry
            items.append({"index": index, **entry})
        return {"items": items}

    def page(self, ids: list[int] | None, method: str, params: dict,
             exists: Callable[[list[int]], set[int]] | None = None) -> dict:
        return self.state.cursors.page(ids, method, params, self.session, exists)

    def stamp(self, seconds: float | None) -> str:
        return timestamp(seconds)

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex
