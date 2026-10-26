"""One open Anki collection, owned by a dedicated worker thread.

Anki's Python collection object is not thread-safe, and SQLite gives the best
latency when a single connection is reused. Every operation on a collection is
therefore queued to the thread that opened it and executed serially. HTTP threads
only wait for results, so any number of clients can be connected at once.

Durability comes from Anki itself: the collection runs in WAL mode and every
operation commits before its result is returned. The host additionally makes
periodic native backups and closes the collection cleanly on shutdown.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from .errors import ApiError, from_exception

log = logging.getLogger("ankicli.host")
T = TypeVar("T")

_STOP = object()
_lang_lock = threading.Lock()
_lang_ready = False


def ensure_language() -> None:
    """Anki's text helpers need a UI language, as Anki Desktop sets at startup."""
    global _lang_ready
    with _lang_lock:
        if not _lang_ready:
            import anki.lang
            anki.lang.set_lang(os.environ.get("ANKICLI_LANG", "en"))
            _lang_ready = True


@dataclass
class HostOptions:
    #: Minutes between automatic backups (0 disables them). Anki's own backup
    #: limits (daily/weekly/monthly retention) still apply.
    backup_minutes: int = 30
    #: Close the collection after this many idle seconds (0 keeps it open).
    idle_close_seconds: int = 0


class CollectionHost:
    def __init__(self, path: str | os.PathLike, name: str, options: HostOptions | None = None):
        self.path = Path(path).absolute()
        self.name = name
        self.options = options or HostOptions()
        self.session = uuid.uuid4().hex
        self.col = None
        self.lifecycle = False  # true while a full sync/reopen is in progress
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._last_backup = time.monotonic()
        self._last_used = time.monotonic()
        self._closed = False
        #: Per-collection protocol state (cursors, tokens, reviewer...), owned by callers.
        self.state: dict[str, Any] = {}

    # -- lifecycle -----------------------------------------------------------------

    def _ensure_thread(self) -> None:
        with self._start_lock:
            if self._closed:
                raise ApiError("collectionUnavailable", "Collection is closed.")
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name=f"anki:{self.name}", daemon=True)
                self._thread.start()

    def _open(self) -> None:
        from anki.collection import Collection
        ensure_language()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.col = Collection(str(self.path))
        except Exception as error:
            message = str(error)
            if "already open" in message.lower():
                raise ApiError("busy", f"The collection {self.path} is open in another program "
                                       "(Anki Desktop or another anki-cli). Close it and retry.") from error
            raise ApiError("collectionUnavailable", f"Could not open {self.path}: {message}") from error
        self.session = uuid.uuid4().hex
        log.info("opened %s", self.path)

    def _close_col(self, downgrade: bool = False) -> None:
        if self.col is not None:
            try:
                self.col.close(downgrade=downgrade)
            finally:
                self.col = None
                log.info("closed %s", self.path)

    def _loop(self) -> None:
        while True:
            timeout = 30.0 if (self.options.backup_minutes or self.options.idle_close_seconds) else None
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                self._maintenance()
                continue
            if item is _STOP:
                try:
                    self._close_col()
                except Exception:
                    log.exception("closing %s failed", self.path)
                return
            fn, future, needs_col = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                if needs_col and self.col is None:
                    self._open()
                self._last_used = time.monotonic()
                future.set_result(fn(self.col))
            except BaseException as error:  # noqa: BLE001 - forwarded to the caller
                future.set_exception(error)
            self._maintenance()

    def _maintenance(self) -> None:
        if self.col is None:
            return
        now = time.monotonic()
        if self.options.backup_minutes and now - self._last_backup >= self.options.backup_minutes * 60:
            self._last_backup = now
            try:
                self.col.create_backup(backup_folder=str(self.backup_dir), force=False,
                                       wait_for_completion=False)
            except Exception:
                log.exception("automatic backup of %s failed", self.path)
        if (self.options.idle_close_seconds and self._queue.empty()
                and now - self._last_used >= self.options.idle_close_seconds):
            self._close_col()

    @property
    def backup_dir(self) -> Path:
        return self.path.parent / "backups"

    # -- execution -------------------------------------------------------------------

    def submit(self, fn: Callable[[Any], T], *, needs_col: bool = True) -> Future:
        self._ensure_thread()
        future: Future = Future()
        self._queue.put((fn, future, needs_col))
        return future

    def run(self, fn: Callable[[Any], T], *, needs_col: bool = True) -> T:
        """Run ``fn(col)`` on the collection thread and return its result."""
        if self._thread is not None and threading.current_thread() is self._thread:
            # Re-entrant call from inside a task (e.g. a nested batch).
            if needs_col and self.col is None:
                self._open()
            return fn(self.col)
        future = self.submit(fn, needs_col=needs_col)
        try:
            return future.result()
        except ApiError:
            raise
        except BaseException as error:  # noqa: BLE001
            raise from_exception(error) from error

    def is_open(self) -> bool:
        return self.col is not None

    def on_worker(self) -> bool:
        return self._thread is not None and threading.current_thread() is self._thread

    def close(self, timeout: float | None = 60) -> None:
        """Flush and close the collection; waits for queued work to finish first."""
        with self._start_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
        if thread is not None and thread.is_alive():
            self._queue.put(_STOP)
            thread.join(timeout)

    def reopen(self) -> None:
        """Close and reopen on the worker thread, e.g. after replacing the file."""
        def cycle(_col: Any) -> None:
            self._close_col()
            self._open()
        self.run(cycle, needs_col=False)
