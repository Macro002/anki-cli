"""Notes and tags."""
from __future__ import annotations

import unicodedata
from typing import Any

from ..errors import ApiError
from ..util import entity_id
from .base import Base

FIELD_STATE_ISSUES = {1: "emptyFirstField", 3: "missingCloze", 4: "notClozeNoteType", 5: "notClozeField"}
ISSUE_MESSAGES = {
    "emptyFirstField": "The first field is empty.",
    "duplicate": "A note with the same first field exists.",
    "missingCloze": "The note has no cloze deletions.",
    "notClozeNoteType": "Cloze deletions are only allowed on cloze note types.",
    "notClozeField": "Cloze deletions are only allowed in cloze fields.",
    "emptyQuestions": "All generated questions are empty.",
}


def normalized_field(value: str) -> str:
    from anki.utils import strip_html_media
    return unicodedata.normalize("NFC", strip_html_media(value))


class Notes(Base):
    # -- records ---------------------------------------------------------------------------

    def note_record(self, note) -> dict:
        return {
            "id": str(note.id),
            "noteType": self.summary(note.note_type()),
            "fields": dict(note.items()),
            "tags": list(note.tags),
            "cardIds": [str(cid) for cid in note.card_ids()],
            "modifiedAt": self.stamp(note.mod),
        }

    def notes_get(self, id: str) -> dict:
        return self.note_record(self.note(id))

    def notes_getMany(self, ids: list[str]) -> dict:
        return self.many(ids, self.notes_get)

    # -- search ----------------------------------------------------------------------------

    def _search(self, kind: str, query: str, limit: int = 100, cursor: str | None = None,
                sort: dict | None = None) -> dict:
        params = {"query": query, "limit": limit, "sort": sort, "cursor": cursor}
        method = kind + ".search"
        table = "notes" if kind == "notes" else "cards"
        exists = lambda chunk: set(self.col.db.list(  # noqa: E731
            f"select id from {table} where id in ({','.join(map(str, chunk))})"))
        if cursor:
            return self.page(None, method, params, exists)
        order: Any = False
        if sort:
            from anki.collection import BrowserColumns
            column = self.col.get_browser_column(sort["column"])
            if column is None:
                raise ApiError("invalidParams", f"Unknown browser sort column: {sort['column']}")
            sorting = column.sorting_notes if kind == "notes" else column.sorting_cards
            if sorting == BrowserColumns.SORTING_NONE:
                raise ApiError("invalidParams", "This column cannot sort this search.")
            order = column
        try:
            finder = self.col.find_notes if kind == "notes" else self.col.find_cards
            ids = list(finder(query, order=order, reverse=bool(sort and sort["direction"] == "descending")))
        except Exception as error:
            raise ApiError("invalidSearch", str(error)) from error
        if not sort:
            ids.sort()
        return self.page(ids, method, params, exists)

    def notes_search(self, query: str, limit: int = 100, cursor: str | None = None, sort: dict | None = None) -> dict:
        return self._search("notes", query, limit, cursor, sort)

    def find_note_ids(self, query: str) -> list[int]:
        try:
            return list(self.col.find_notes(query))
        except Exception as error:
            raise ApiError("invalidSearch", str(error)) from error

    def find_card_ids(self, query: str) -> list[int]:
        try:
            return list(self.col.find_cards(query))
        except Exception as error:
            raise ApiError("invalidSearch", str(error)) from error

    # -- validation and creation -------------------------------------------------------------

    def resolve_cached(self, reference: dict, kind: str) -> dict:
        """``resolve`` without a copy per call, for read-only use within one request."""
        cache = self.__dict__.setdefault("_resolve_cache", {})
        key = (kind, reference.get("id"), reference.get("name"))
        if key not in cache:
            cache[key] = self.resolve(reference, kind)
        return cache[key]

    def prepare_note(self, data: dict):
        model = self.resolve_cached(data["noteType"], "noteType")
        deck = self.resolve_cached(data["deck"], "deck")
        if deck.get("dyn"):
            raise ApiError("validationFailed", "Cannot add a note to a filtered deck.")
        note = self.col.new_note(model)
        for name, value in data.get("fields", {}).items():
            if name not in note:
                raise ApiError("validationFailed", f"Unknown field: {name}",
                               {"issues": [{"type": "unknownField", "message": f"Unknown field: {name}",
                                            "field": name}]})
            note[name] = value
        note.tags = list(dict.fromkeys(data.get("tags", [])))
        return note, deck

    def empty_questions(self, note) -> bool:
        from anki.utils import to_json_bytes
        model = note.note_type()
        templates = model["tmpls"]
        backend_note = note._to_backend_note()
        if model["type"] == 1:
            ordinals = {n - 1 for n in self.col._backend.cloze_numbers_in_note(backend_note)} or {0}
            templates = [{**templates[0], "ord": index} for index in sorted(ordinals)]
        return all(self.col._backend.render_uncommitted_card_legacy(
            note=backend_note, card_ord=template["ord"], template=to_json_bytes(template),
            fill_empty=False, partial_render=True).is_empty for template in templates)

    def duplicate_ids(self, note, deck: dict, policy: dict | None) -> list[str]:
        from anki.utils import field_checksum
        policy = policy or {}
        if policy.get("allow", False):
            return []
        source = normalized_field(note.fields[0])
        candidates = self.col.db.list("select id from notes where csum=? and id!=?",
                                      field_checksum(note.fields[0]), note.id or 0)
        scope_decks = None
        if policy.get("scope", "collection") == "deck":
            target = self.resolve(policy.get("deck") or self.summary(deck), "deck")
            scope_decks = {target["id"]}
            if policy.get("includeChildren", False):
                scope_decks.update(did for _, did in self.col.decks.children(target["id"]))
        found = []
        for nid in candidates:
            other = self.col.get_note(nid)
            if not policy.get("acrossNoteTypes", False) and other.mid != note.mid:
                continue
            if normalized_field(other.fields[0]) != source:
                continue
            if scope_decks is not None and not any((card.odid or card.did) in scope_decks for card in other.cards()):
                continue
            found.append(str(nid))
        return found

    def validation(self, note, deck: dict, policy: dict | None, reject_empty: bool) -> dict:
        issues = []
        state = int(note.fields_check())
        if state in FIELD_STATE_ISSUES:
            kind = FIELD_STATE_ISSUES[state]
            issues.append({"type": kind, "message": ISSUE_MESSAGES[kind]})
        duplicates = self.duplicate_ids(note, deck, policy) if not note.fields[0] == "" else []
        if duplicates:
            issues.append({"type": "duplicate", "message": ISSUE_MESSAGES["duplicate"]})
        if reject_empty and not issues and self.empty_questions(note):
            issues.append({"type": "emptyQuestions", "message": ISSUE_MESSAGES["emptyQuestions"]})
        return {"valid": not issues, "issues": issues, "duplicateNoteIds": duplicates}

    def notes_validate(self, note: dict) -> dict:
        try:
            native, deck = self.prepare_note(note)
        except ApiError as error:
            if error.kind == "validationFailed" and error.details and "issues" in error.details:
                return {"valid": False, "issues": error.details["issues"], "duplicateNoteIds": []}
            raise
        return self.validation(native, deck, note.get("duplicates"), note.get("rejectEmptyQuestions", True))

    def notes_validateMany(self, notes: list[dict]) -> dict:
        return self.many(notes, self.notes_validate)

    def notes_create(self, noteType: dict, deck: dict, fields: dict, tags: list | None = None,
                     duplicates: dict | None = None, rejectEmptyQuestions: bool = True) -> dict:
        data = {"noteType": noteType, "deck": deck, "fields": fields, "tags": tags or [],
                "duplicates": duplicates, "rejectEmptyQuestions": rejectEmptyQuestions}
        note, target = self.prepare_note(data)
        result = self.validation(note, target, duplicates, rejectEmptyQuestions)
        if not result["valid"]:
            raise ApiError("validationFailed", "Note cannot be created: " + result["issues"][0]["message"], result)
        self.change(self.col.add_note(note, target["id"]))
        return {"noteId": str(note.id), "cardIds": [str(cid) for cid in note.card_ids()]}

    def prepare_notes(self, notes: list[dict]):
        """Validate an ordered batch without writing, including duplicates within it."""
        from anki.collection import AddNoteRequest
        from ..errors import from_exception
        prepared, errors = [], []
        seen: dict[str, list[tuple[int, int]]] = {}  # normalized first field -> [(note type, deck)]
        for index, data in enumerate(notes):
            try:
                note, deck = self.prepare_note(data)
                policy = data.get("duplicates") or {}
                result = self.validation(note, deck, policy, data.get("rejectEmptyQuestions", True))
                first = normalized_field(note.fields[0]) if note.fields[0] != "" else None
                if first is not None and not policy.get("allow", False) and first in seen:
                    scope = None
                    if policy.get("scope") == "deck":
                        scoped = self.resolve_cached(policy.get("deck") or self.summary(deck), "deck")["id"]
                        scope = {scoped}
                        if policy.get("includeChildren"):
                            scope.update(did for _, did in self.col.decks.children(scoped))
                    for mid, did in seen[first]:
                        if not policy.get("acrossNoteTypes", False) and mid != note.mid:
                            continue
                        if scope is not None and did not in scope:
                            continue
                        result["valid"] = False
                        result["issues"].append({"type": "duplicate", "message": "Duplicate within the batch."})
                        break
                if not result["valid"]:
                    raise ApiError("validationFailed", "Invalid note: " + result["issues"][0]["message"], result)
                prepared.append(AddNoteRequest(note=note, deck_id=deck["id"]))
                if first is not None:
                    seen.setdefault(first, []).append((note.mid, deck["id"]))
            except Exception as error:  # noqa: BLE001
                errors.append({"index": index, "error": from_exception(error).record()})
        return prepared, errors

    def notes_createMany(self, notes: list[dict], atomic: bool = False) -> dict:
        if not atomic:
            return self.many(notes, lambda data: self.notes_create(**data))
        prepared, errors = self.prepare_notes(notes)
        if errors:
            raise ApiError("validationFailed", "Atomic batch validation failed.", {"items": errors})
        if prepared:
            self.change(self.col.add_notes(prepared))
        return {"items": [{"index": index, "result": {"noteId": str(req.note.id),
                                                      "cardIds": [str(cid) for cid in req.note.card_ids()]}}
                          for index, req in enumerate(prepared)]}

    def notes_update(self, id: str, patch: dict) -> dict:
        note = self.note(id)
        for name, value in patch.get("fields", {}).items():
            if name not in note:
                raise ApiError("validationFailed", f"Unknown field: {name}")
            note[name] = value
        if "tags" in patch:
            note.tags = list(dict.fromkeys(patch["tags"]))
        self.change(self.col.update_note(note))
        return self.note_record(self.note(id))

    def notes_delete(self, ids: list[str]) -> dict:
        def delete(value: str) -> dict:
            note = self.note(value)
            self.change(self.col.remove_notes([note.id]))
            return {"changed": True}
        return self.many(ids, delete, True)

    # -- conversion --------------------------------------------------------------------------

    def notes_planConversion(self, source: dict, target: dict) -> dict:
        old, new = self.resolve(source, "noteType"), self.resolve(target, "noteType")
        info = self.col.models.change_notetype_info(old_notetype_id=old["id"], new_notetype_id=new["id"])

        def maps(key: str, indices) -> list[dict]:
            return [{"target": item["name"], "source": old[key][index]["name"] if index >= 0 else None}
                    for item, index in zip(new[key], indices)]
        templates = [] if info.input.is_cloze else maps("tmpls", info.input.new_templates)
        return {"source": self.summary(old), "target": self.summary(new),
                "fields": maps("flds", info.input.new_fields), "templates": templates,
                "token": self.token("conversion", (old["mod"], old["id"], new["mod"], new["id"]))}

    def notes_convert(self, ids: list[str], target: dict, fields: list[dict], templates: list[dict],
                      planToken: str) -> dict:
        if not ids:
            return {"changedCount": 0}
        notes = [self.note(value) for value in ids]
        old = notes[0].note_type()
        new = self.resolve(target, "noteType")
        if any(note.mid != old["id"] for note in notes):
            raise ApiError("validationFailed", "All notes must share one source note type.")
        self.check_token(planToken, "conversion", (old["mod"], old["id"], new["mod"], new["id"]),
                         "The conversion plan is stale; plan again.")
        info = self.col.models.change_notetype_info(old_notetype_id=old["id"], new_notetype_id=new["id"])

        def indices(mapping: list[dict], key: str) -> list[int]:
            if key == "tmpls" and info.input.is_cloze:
                if mapping:
                    raise ApiError("invalidParams", "Cloze conversion takes an empty template mapping.")
                return list(info.input.new_templates)
            by_name = {entry["target"]: entry["source"] for entry in mapping}
            if len(by_name) != len(mapping) or set(by_name) != {item["name"] for item in new[key]}:
                raise ApiError("invalidParams", "The mapping must name every target exactly once.")
            source_names = [item["name"] for item in old[key]]
            chosen = [by_name[item["name"]] for item in new[key]]
            used = [name for name in chosen if name is not None]
            if len(used) != len(set(used)) or any(name not in source_names for name in used):
                raise ApiError("invalidParams", "Unknown or repeated source in the mapping.")
            return [source_names.index(name) if name is not None else -1 for name in chosen]

        request = info.input
        request.note_ids.extend(note.id for note in notes)
        request.new_fields[:] = indices(fields, "flds")
        request.new_templates[:] = indices(templates, "tmpls")
        self.change(self.col.models.change_notetype_of_notes(request))
        return {"changedCount": len(set(ids))}

    def notes_findEmpty(self, criterion: str, query: str = "", limit: int = 100, cursor: str | None = None) -> dict:
        params = {"criterion": criterion, "query": query, "limit": limit, "cursor": cursor}
        if cursor:
            return self.page(None, "notes.findEmpty", params)
        matches = []
        for nid in self.find_note_ids(query):
            note = self.col.get_note(nid)
            if ((criterion == "noCards" and not note.card_ids())
                    or (criterion == "allFieldsEmpty" and all(not normalized_field(v).strip() for v in note.fields))
                    or (criterion == "allQuestionsEmpty" and self.empty_questions(note))):
                matches.append(nid)
        return self.page(sorted(matches), "notes.findEmpty", params)

    # -- tags --------------------------------------------------------------------------------

    def tags_list(self) -> list[str]:
        return list(self.col.tags.all())

    def _mutate_tags(self, noteIds: list[str], tags: list[str], remove: bool) -> dict:
        def mutate(value: str) -> dict:
            note = self.note(value)
            before = list(note.tags)
            for tag in tags:
                note.remove_tag(tag) if remove else note.add_tag(tag)
            changed = before != note.tags
            if changed:
                self.change(self.col.update_note(note))
            return {"changed": changed}
        return self.many(noteIds, mutate, True)

    def tags_add(self, noteIds: list[str], tags: list[str]) -> dict:
        return self._mutate_tags(noteIds, tags, False)

    def tags_remove(self, noteIds: list[str], tags: list[str]) -> dict:
        return self._mutate_tags(noteIds, tags, True)

    def tags_replace(self, **params: Any) -> dict:
        source, target = params["from"], params["to"]
        if params.get("allNotes"):
            ids = list(self.col.find_notes(""))
        else:
            ids = [entity_id(value) for value in params.get("noteIds") or []]
        changed = []
        for nid in dict.fromkeys(ids):
            note = self.note(nid)
            if note.has_tag(source):
                note.remove_tag(source)
                note.add_tag(target)
                changed.append(note)
        if changed:
            self.change(self.col.update_notes(changed))
        return {"changedCount": len(changed)}

    def tags_deleteUnused(self) -> dict:
        out = self.change(self.col.tags.clear_unused_tags())
        return {"changedCount": out.count}
