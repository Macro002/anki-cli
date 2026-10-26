"""Headless equivalents of Anki's reviewer, browser and editors.

Anki Desktop exposes these as windows; anki-cli keeps the same state in memory per
collection so that GUI-oriented API calls (``guiDeckReview``, ``guiCurrentCard``,
``reviewer.answer``, ``browser.open`` ...) work without a display.

The reviewer always presents the head of Anki's v3 queue and answers with the
scheduling states that the queue supplied, exactly like the desktop reviewer.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from ..errors import ApiError
from .base import Base


class Gui(Base):
    # -- reviewer ----------------------------------------------------------------------------

    def reviewer_start(self, deck: dict | None = None) -> dict:
        """Open a deck in the reviewer (like clicking a deck, then Study Now)."""
        if deck is not None:
            target = self.resolve(deck, "deck")
            self.col.decks.select(target["id"])
        self.state.reviewer = {"active": True, "cardId": None, "side": "question", "shownAt": None}
        current = self._reviewer_current()
        if current is None:
            self.state.reviewer["active"] = False
        return self.reviewer_get()

    def reviewer_stop(self) -> dict:
        self.state.reviewer = {"active": False}
        return {"changed": True}

    def _reviewer_current(self):
        """(card, states) at the head of the queue, or None when the deck is finished."""
        reviewer = self.state.reviewer
        if not reviewer.get("active"):
            return None
        queued = self.col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            reviewer.update(active=False, cardId=None)
            return None
        entry = queued.cards[0]
        from anki.cards import Card
        card = Card(self.col, backend_card=entry.card)
        if reviewer.get("cardId") != card.id:
            reviewer.update(cardId=card.id, side="question", shownAt=time.time())
            self.state.timer_started[card.id] = time.time()
        return card, entry.states, entry

    def _reviewer_token(self, card, side: str) -> str:
        return self.token("reviewer", (card.id, card.mod, side, self.col.sched.today))

    def reviewer_get(self) -> dict:
        current = self._reviewer_current()
        if current is None:
            return {"active": False, "card": None, "rendered": None, "side": "none", "stateToken": None,
                    "answers": [], "source": "reviewer"}
        card, states, _ = current
        side = self.state.reviewer.get("side", "question")
        return {"active": True, "card": self.card_record(card),  # type: ignore[attr-defined]
                "rendered": {"cardId": str(card.id), "questionHtml": card.question(),
                             "answerHtml": card.answer(), "css": card.note_type()["css"]},
                "side": side, "stateToken": self._reviewer_token(card, side),
                "answers": self.predictions(card, states),  # type: ignore[attr-defined]
                "source": "reviewer"}

    def counts(self) -> dict:
        queued = self.col.sched.get_queued_cards(fetch_limit=1)
        return {"new": queued.new_count, "learning": queued.learning_count, "review": queued.review_count}

    def _checked_current(self, stateToken: str):
        current = self._reviewer_current()
        if current is None:
            raise ApiError("invalidState", "The reviewer is not active.")
        card, states, entry = current
        self.check_token(stateToken, "reviewer", (card.id, card.mod, self.state.reviewer.get("side", "question"),
                                                  self.col.sched.today),
                         "The reviewer state changed; call reviewer.get again.")
        return card, states, entry

    def reviewer_startTimer(self, stateToken: str) -> dict:
        card, _, _ = self._checked_current(stateToken)
        self.state.timer_started[card.id] = time.time()
        return {"changed": True}

    def reviewer_showQuestion(self, stateToken: str) -> dict:
        self._checked_current(stateToken)
        changed = self.state.reviewer.get("side") != "question"
        self.state.reviewer["side"] = "question"
        return {"changed": changed}

    def reviewer_showAnswer(self, stateToken: str) -> dict:
        self._checked_current(stateToken)
        changed = self.state.reviewer.get("side") != "answer"
        self.state.reviewer["side"] = "answer"
        return {"changed": changed}

    def reviewer_playAudio(self, stateToken: str) -> dict:
        # Headless: there is no audio device. Clients play the tags from cards.audio.
        self._checked_current(stateToken)
        return {"changed": False}

    def reviewer_answer(self, stateToken: str, rating: str) -> dict:
        card, states, _ = self._checked_current(stateToken)
        if self.state.reviewer.get("side") != "answer":
            raise ApiError("invalidState", "Show the answer before answering.")
        self.answer_native(card, rating, states)  # type: ignore[attr-defined]
        review_id = self.col.db.scalar("select max(id) from revlog where cid=?", card.id)
        self.state.reviewer.update(cardId=None, side="question")
        self._reviewer_current()
        return {"cardId": str(card.id), "reviewId": str(review_id) if review_id else None,
                "scheduling": self.state_record(self.card(card.id))}  # type: ignore[attr-defined]

    def reviewer_undo(self) -> dict:
        """Undo the last answer and show that card again."""
        status = self.col.undo_status()
        if not status.undo:
            raise ApiError("invalidState", "Nothing to undo.")
        self.col.undo()
        self.state.reviewer.update(cardId=None, side="question")
        if not self.state.reviewer.get("active"):
            self.state.reviewer = {"active": True, "cardId": None, "side": "question", "shownAt": None}
        self._reviewer_current()
        return {"label": status.undo, "changed": True}

    # -- browser -----------------------------------------------------------------------------

    def browser_state(self) -> dict:
        browser = self.state.browser
        return {"open": browser["open"], "selectedNoteIds": list(browser["selectedNoteIds"]),
                "selectedCardIds": list(browser["selectedCardIds"])}

    def browser_open(self, query: str | None = None, sort: dict | None = None) -> dict:
        browser = self.state.browser
        if query is not None:
            browser["query"] = query
        if sort is not None:
            column = self.col.get_browser_column(sort["column"])
            if column is None:
                raise ApiError("invalidParams", f"invalid columnId: {sort['column']}")
            browser["sort"] = sort
        browser["open"] = True
        browser["selectedCardIds"], browser["selectedNoteIds"] = [], []
        return self.browser_state()

    def browser_results(self) -> list[int]:
        browser = self.state.browser
        sort = browser.get("sort")
        order: Any = False
        if sort:
            order = self.col.get_browser_column(sort["column"]) or False
        try:
            return list(self.col.find_cards(browser.get("query", ""), order=order,
                                             reverse=bool(sort and sort["direction"] == "descending")))
        except Exception as error:
            raise ApiError("invalidSearch", str(error)) from error

    def browser_getSelection(self) -> dict:
        return self.browser_state()

    def browser_select(self, cardIds: list[str] | None = None, noteIds: list[str] | None = None) -> dict:
        browser = self.state.browser
        if not browser["open"]:
            raise ApiError("invalidState", "The browser is not open.")
        if cardIds is not None:
            cards = [self.card(value) for value in cardIds]
            browser["selectedCardIds"] = [str(card.id) for card in cards]
            browser["selectedNoteIds"] = list(dict.fromkeys(str(card.nid) for card in cards))
        else:
            notes = [self.note(value) for value in noteIds or []]
            browser["selectedNoteIds"] = [str(note.id) for note in notes]
            browser["selectedCardIds"] = [str(cid) for note in notes for cid in note.card_ids()]
        return self.browser_state()

    def browser_close(self) -> dict:
        self.state.browser.update(open=False, selectedCardIds=[], selectedNoteIds=[])
        return {"changed": True}

    def browser_columns(self) -> list[dict]:
        """Columns usable for sorting searches (``sort.column``)."""
        return [{"key": column.key, "label": column.cards_mode_label, "notesLabel": column.notes_mode_label,
                 "sortsCards": bool(column.sorting_cards), "sortsNotes": bool(column.sorting_notes)}
                for column in self.col.all_browser_columns()]

    def browser_rows(self, ids: list[str], columns: list[str], mode: str = "cards") -> list[dict]:
        """Rendered browser rows (the same text Anki's browser table shows)."""
        self.col.set_browser_card_columns(columns) if mode == "cards" else self.col.set_browser_note_columns(columns)
        rows = []
        for value in ids:
            row = self.col.browser_row_for_id(int(value))
            rows.append({"id": value, "cells": [cell[0] for cell in row[0]], "color": int(row[1])})
        return rows

    # -- editors -------------------------------------------------------------------------------

    def editor_state(self, editor_id: str) -> dict:
        editor = self.state.editors.get(editor_id)
        if editor is None:
            raise ApiError("notFound", f"Editor not found: {editor_id}")
        model = self.col.models.get(editor["noteTypeId"])
        deck = self.col.decks.get(editor["deckId"], default=False) if editor.get("deckId") else None
        return {"id": editor_id, "kind": editor["kind"], "variant": "custom",
                "noteId": str(editor["noteId"]) if editor.get("noteId") else None,
                "deck": self.summary(deck) if deck else None, "noteType": self.summary(model),
                "fields": dict(editor["fields"]), "tags": list(editor["tags"]), "dirty": editor["dirty"],
                "session": self.session}

    def editors_openAdd(self, note: dict | None = None) -> dict:
        if note:
            model = self.resolve(note["noteType"], "noteType")
            deck = self.resolve(note["deck"], "deck")
        else:
            defaults = self.col.defaults_for_adding(current_review_card=None)
            model = self.col.models.get(defaults.notetype_id)
            deck = self.col.decks.get(defaults.deck_id)
        fields = {field["name"]: "" for field in model["flds"]}
        for name, value in (note or {}).get("fields", {}).items():
            if name not in fields:
                raise ApiError("validationFailed", f"Unknown field: {name}")
            fields[name] = value
        editor_id = uuid.uuid4().hex[:12]
        self.state.editors[editor_id] = {"kind": "add", "noteTypeId": model["id"], "deckId": deck["id"],
                                         "fields": fields, "tags": list((note or {}).get("tags", [])),
                                         "dirty": bool(note), "noteId": None}
        return self.editor_state(editor_id)

    def editors_openNote(self, noteId: str) -> dict:
        native = self.note(noteId)
        cards = native.cards()
        editor_id = uuid.uuid4().hex[:12]
        self.state.editors[editor_id] = {"kind": "note", "noteTypeId": native.mid,
                                         "deckId": cards[0].did if cards else None,
                                         "fields": dict(native.items()), "tags": list(native.tags),
                                         "dirty": False, "noteId": native.id}
        return self.editor_state(editor_id)

    def editors_updateDraft(self, editorId: str, patch: dict, mode: str = "replace") -> dict:
        editor = self.state.editors.get(editorId)
        if editor is None:
            raise ApiError("notFound", f"Editor not found: {editorId}")
        if "noteType" in patch:
            if editor["kind"] == "note":
                raise ApiError("invalidState", "Use notes.convert to change an existing note's type.")
            model = self.resolve(patch["noteType"], "noteType")
            old = editor["fields"]
            editor["noteTypeId"] = model["id"]
            editor["fields"] = {field["name"]: old.get(field["name"], "") for field in model["flds"]}
        if "deck" in patch:
            editor["deckId"] = self.resolve(patch["deck"], "deck")["id"]
        for name in patch.get("fields", {}):
            if name not in editor["fields"]:
                raise ApiError("validationFailed", f"Unknown field: {name}")
        for name, value in patch.get("fields", {}).items():
            editor["fields"][name] = editor["fields"][name] + value if mode == "append" else value
        if "tags" in patch:
            editor["tags"] = (list(dict.fromkeys(editor["tags"] + patch["tags"])) if mode == "append"
                              else list(patch["tags"]))
        editor["dirty"] = True
        return self.editor_state(editorId)

    def editors_save(self, editorId: str) -> dict:
        """Save a draft: add the note (Add editor) or write the changes (note editor)."""
        editor = self.state.editors.get(editorId)
        if editor is None:
            raise ApiError("notFound", f"Editor not found: {editorId}")
        if editor["kind"] == "add":
            created = self.notes_create(  # type: ignore[attr-defined]
                noteType={"id": str(editor["noteTypeId"])}, deck={"id": str(editor["deckId"])},
                fields=editor["fields"], tags=editor["tags"])
            editor.update(kind="note", noteId=int(created["noteId"]), dirty=False)
        else:
            self.notes_update(str(editor["noteId"]), {"fields": editor["fields"],  # type: ignore[attr-defined]
                                                      "tags": editor["tags"]})
            editor["dirty"] = False
        return self.editor_state(editorId)

    def editors_close(self, editorId: str) -> dict:
        return {"changed": self.state.editors.pop(editorId, None) is not None}

    def editors_list(self) -> list[dict]:
        return [self.editor_state(editor_id) for editor_id in list(self.state.editors)]

    # -- navigation and import -------------------------------------------------------------------

    def application_navigate(self, view: str, deck: dict | None = None) -> dict:
        if view == "deckBrowser":
            self.reviewer_stop()
        elif view == "deckOverview":
            target = self.resolve(deck or {}, "deck")
            self.col.decks.select(target["id"])
            self.reviewer_stop()
        elif view == "review":
            self.reviewer_start(deck)
        return {"changed": True}

    def application_importFile(self, path: str | None = None) -> dict:
        if not path:
            raise ApiError("invalidParams", "anki-cli has no file picker; pass a path.")
        lower = path.lower()
        if lower.endswith((".apkg", ".colpkg")):
            result = self.packages_import(path)  # type: ignore[attr-defined]
        elif lower.endswith((".csv", ".tsv", ".txt")):
            result = self.packages_importCsv(path)  # type: ignore[attr-defined]
        elif lower.endswith(".json"):
            self.change(self.col.import_json_file(path))
            result = {"completed": True}
        else:
            raise ApiError("invalidParams", "Supported files: .apkg, .colpkg, .csv, .tsv, .txt, .json")
        return {"completed": bool(result.get("completed"))}
