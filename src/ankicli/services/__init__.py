"""The native service layer: one implementation behind every protocol."""
from __future__ import annotations

from .base import Base, HostState, host_state
from .cards import Cards
from .decks import Decks
from .gui import Gui
from .history import History
from .media import Media
from .notes import Notes
from .notetypes import NoteTypes
from .sync import Sync


class Services(Notes, Cards, Decks, NoteTypes, Media, History, Gui, Sync):
    """All collection-scoped methods. ``notes.get`` is implemented by ``notes_get``."""

    def handler(self, method: str):
        return getattr(self, method.replace(".", "_"), None)


__all__ = ["Base", "HostState", "Services", "host_state"]
