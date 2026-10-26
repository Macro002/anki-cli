"""The legacy Anki-Connect protocol (``POST /`` with ``action``/``version``/``params``).

Every one of Anki-Connect's 122 legacy actions is implemented on top of the native
services, preserving its parameter names, coercion rules, result shapes and
historical error strings, so existing clients (Yomitan, Obsidian_to_Anki,
asbplayer, AnkiBase ...) work unchanged.
"""
from __future__ import annotations

import base64
import copy
import html
import os
import re
import time
from typing import Any, Callable

from .errors import ApiError, from_exception
from .services import Services
from .services.base import RATINGS
from .services.media import ILLEGAL, acquire

API_VERSION = 6
MAX_MULTI_DEPTH = 16

# action -> ordered (parameter, default) pairs; REQUIRED marks required parameters.
REQUIRED = object()
SIGNATURES: dict[str, tuple] = {
    "version": (), "requestPermission": (("origin", REQUIRED), ("allowed", REQUIRED)),
    "getProfiles": (), "getActiveProfile": (), "loadProfile": (("name", REQUIRED),), "sync": (),
    "multi": (("actions", REQUIRED),), "getNumCardsReviewedToday": (), "getNumCardsReviewedByDay": (),
    "getCollectionStatsHTML": (("wholeCollection", True),), "deckNames": (), "deckNamesAndIds": (),
    "getDecks": (("cards", REQUIRED),), "createDeck": (("deck", REQUIRED),),
    "changeDeck": (("cards", REQUIRED), ("deck", REQUIRED)),
    "deleteDecks": (("decks", REQUIRED), ("cardsToo", False)), "getDeckConfig": (("deck", REQUIRED),),
    "saveDeckConfig": (("config", REQUIRED),), "setDeckConfigId": (("decks", REQUIRED), ("configId", REQUIRED)),
    "cloneDeckConfigId": (("name", REQUIRED), ("cloneFrom", "1")), "removeDeckConfigId": (("configId", REQUIRED),),
    "getDeckStats": (("decks", REQUIRED),),
    "storeMediaFile": (("filename", REQUIRED), ("data", None), ("path", None), ("url", None), ("skipHash", None),
                       ("deleteExisting", True)),
    "retrieveMediaFile": (("filename", REQUIRED),), "getMediaFilesNames": (("pattern", "*"),),
    "deleteMediaFile": (("filename", REQUIRED),), "getMediaDirPath": (),
    "addNote": (("note", REQUIRED),), "canAddNote": (("note", REQUIRED),),
    "canAddNoteWithErrorDetail": (("note", REQUIRED),), "updateNoteFields": (("note", REQUIRED),),
    "updateNote": (("note", REQUIRED),), "updateNoteModel": (("note", REQUIRED),),
    "updateNoteTags": (("note", REQUIRED), ("tags", REQUIRED)), "getNoteTags": (("note", REQUIRED),),
    "addTags": (("notes", REQUIRED), ("tags", REQUIRED), ("add", True)),
    "removeTags": (("notes", REQUIRED), ("tags", REQUIRED)), "getTags": (), "clearUnusedTags": (),
    "replaceTags": (("notes", REQUIRED), ("tag_to_replace", REQUIRED), ("replace_with_tag", REQUIRED)),
    "replaceTagsInAllNotes": (("tag_to_replace", REQUIRED), ("replace_with_tag", REQUIRED)),
    "setEaseFactors": (("cards", REQUIRED), ("easeFactors", REQUIRED)),
    "setSpecificValueOfCard": (("card", REQUIRED), ("keys", REQUIRED), ("newValues", REQUIRED),
                               ("warning_check", False)),
    "getEaseFactors": (("cards", REQUIRED),), "suspend": (("cards", REQUIRED), ("suspend", True)),
    "unsuspend": (("cards", REQUIRED),), "suspended": (("card", REQUIRED),), "areSuspended": (("cards", REQUIRED),),
    "areDue": (("cards", REQUIRED),), "getIntervals": (("cards", REQUIRED), ("complete", False)),
    "modelNames": (),
    "createModel": (("modelName", REQUIRED), ("inOrderFields", REQUIRED), ("cardTemplates", REQUIRED),
                    ("css", None), ("isCloze", False)),
    "modelNamesAndIds": (), "findModelsById": (("modelIds", REQUIRED),),
    "findModelsByName": (("modelNames", REQUIRED),), "modelNameFromId": (("modelId", REQUIRED),),
    "modelFieldNames": (("modelName", REQUIRED),), "modelFieldDescriptions": (("modelName", REQUIRED),),
    "modelFieldFonts": (("modelName", REQUIRED),), "modelFieldsOnTemplates": (("modelName", REQUIRED),),
    "modelTemplates": (("modelName", REQUIRED),), "modelStyling": (("modelName", REQUIRED),),
    "updateModelTemplates": (("model", REQUIRED),), "updateModelStyling": (("model", REQUIRED),),
    "findAndReplaceInModels": (("modelName", REQUIRED), ("findText", REQUIRED), ("replaceText", REQUIRED),
                               ("front", True), ("back", True), ("css", True)),
    "modelTemplateRename": (("modelName", REQUIRED), ("oldTemplateName", REQUIRED), ("newTemplateName", REQUIRED)),
    "modelTemplateReposition": (("modelName", REQUIRED), ("templateName", REQUIRED), ("index", REQUIRED)),
    "modelTemplateAdd": (("modelName", REQUIRED), ("template", REQUIRED)),
    "modelTemplateRemove": (("modelName", REQUIRED), ("templateName", REQUIRED)),
    "modelFieldRename": (("modelName", REQUIRED), ("oldFieldName", REQUIRED), ("newFieldName", REQUIRED)),
    "modelFieldReposition": (("modelName", REQUIRED), ("fieldName", REQUIRED), ("index", REQUIRED)),
    "modelFieldAdd": (("modelName", REQUIRED), ("fieldName", REQUIRED), ("index", None)),
    "modelFieldRemove": (("modelName", REQUIRED), ("fieldName", REQUIRED)),
    "modelFieldSetFont": (("modelName", REQUIRED), ("fieldName", REQUIRED), ("font", REQUIRED)),
    "modelFieldSetFontSize": (("modelName", REQUIRED), ("fieldName", REQUIRED), ("fontSize", REQUIRED)),
    "modelFieldSetDescription": (("modelName", REQUIRED), ("fieldName", REQUIRED), ("description", REQUIRED)),
    "deckNameFromId": (("deckId", REQUIRED),), "findNotes": (("query", None),), "findCards": (("query", None),),
    "cardsInfo": (("cards", REQUIRED), ("fields", None)), "cardsModTime": (("cards", REQUIRED),),
    "forgetCards": (("cards", REQUIRED),), "relearnCards": (("cards", REQUIRED),),
    "answerCards": (("answers", REQUIRED),), "cardReviews": (("deck", REQUIRED), ("startID", REQUIRED)),
    "getReviewsOfCards": (("cards", REQUIRED),), "setDueDate": (("cards", REQUIRED), ("days", REQUIRED)),
    "reloadCollection": (), "getLatestReviewID": (("deck", REQUIRED),), "insertReviews": (("reviews", REQUIRED),),
    "notesInfo": (("notes", None), ("query", None)), "notesModTime": (("notes", REQUIRED),),
    "deleteNotes": (("notes", REQUIRED),), "removeEmptyNotes": (), "cardsToNotes": (("cards", REQUIRED),),
    "guiBrowse": (("query", None), ("reorderCards", None)), "guiEditNote": (("note", REQUIRED),),
    "guiSelectNote": (("note", REQUIRED),), "guiSelectCard": (("card", REQUIRED),), "guiSelectedNotes": (),
    "guiAddNoteSetData": (("note", REQUIRED), ("append", False)), "guiAddCards": (("note", None),),
    "guiReviewActive": (), "guiCurrentCard": (), "guiStartCardTimer": (), "guiShowQuestion": (),
    "guiShowAnswer": (), "guiAnswerCard": (("ease", REQUIRED),), "guiPlayAudio": (), "guiUndo": (),
    "guiDeckOverview": (("name", REQUIRED),), "guiDeckBrowser": (), "guiDeckReview": (("name", REQUIRED),),
    "guiImportFile": (("path", None),), "guiExitAnki": (), "guiCheckDatabase": (),
    "addNotes": (("notes", REQUIRED),), "canAddNotes": (("notes", REQUIRED),),
    "canAddNotesWithErrorDetail": (("notes", REQUIRED),),
    "exportPackage": (("deck", REQUIRED), ("path", REQUIRED), ("includeSched", False)),
    "importPackage": (("path", REQUIRED),), "apiReflect": (("scopes", None), ("actions", None)),
}
ACTIONS = list(SIGNATURES)
APP_ACTIONS = {"version", "requestPermission", "apiReflect", "getProfiles", "getActiveProfile", "loadProfile",
               "multi", "guiExitAnki"}

VALIDATION_MESSAGES = {
    "emptyFirstField": "cannot create note because it is empty",
    "duplicate": "cannot create note because it is a duplicate",
    "emptyQuestions": "The field values you have provided would make an empty question on all cards.",
    "missingCloze": "cannot create note for unknown reason",
    "notClozeNoteType": "cannot create note for unknown reason",
    "notClozeField": "cannot create note for unknown reason",
}


class LegacyError(Exception):
    """An error whose message is returned verbatim in the legacy envelope."""


# -- input normalization -----------------------------------------------------------------------

def integer(value: Any) -> Any:
    """Accept decimal strings and integral floats without rounding."""
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]{1,19}", value.strip()):
        return int(value)
    if type(value) is float and value.is_integer() and abs(value) <= 9007199254740991:
        return int(value)
    return value


def boolean(value: Any, default: bool, label: str) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        value = {"true": True, "false": False, "1": True, "0": False}.get(value.strip().lower(), value)
    if type(value) is int and value in (0, 1):
        value = bool(value)
    if type(value) is not bool:
        raise ApiError("invalidParams", f"{label} must be boolean")
    return value


def array(value: Any) -> list:
    return [] if value is None else value if isinstance(value, list) else [value]


def identifier(value: Any) -> int:
    value = integer(value)
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise ApiError("invalidParams", "Expected a positive signed 64-bit decimal ID.")
    return value


def legacy_request(request: Any) -> dict:
    if not isinstance(request, dict):
        raise ApiError("invalidParams", "Legacy requests must be objects.")
    request = dict(request)
    version = integer(request.get("version")) if request.get("version") is not None else 4
    if type(version) is not int:
        raise ApiError("invalidParams", "version must be an integer.")
    request["version"] = version
    params = request.get("params")
    if params is None or params == []:
        params = {}
    if not isinstance(params, dict):
        raise ApiError("invalidParams", "params must be an object.")
    request["params"] = dict(params)
    return request


def bind(name: str, params: dict) -> dict:
    """Bind params like Anki-Connect's Python signature binder (surplus keys ignored)."""
    signature = SIGNATURES[name]
    known = {key for key, _ in signature}
    bound = {key: value for key, value in params.items() if key in known}
    missing = []
    for key, default in signature:
        if bound.get(key) is None and default is not REQUIRED:
            bound[key] = default
        elif key not in bound and default is REQUIRED:
            missing.append(key)
    if missing:
        quoted = [f"'{m}'" for m in missing]
        if len(quoted) == 1:
            names = quoted[0]
        elif len(quoted) == 2:
            names = " and ".join(quoted)
        else:
            names = ", ".join(quoted[:-1]) + ", and " + quoted[-1]
        noun = "argument" if len(missing) == 1 else "arguments"
        raise LegacyError(f"AnkiConnect.{name}() missing {len(missing)} required positional {noun}: {names}")
    return normalize_params(name, bound)


def normalize_params(name: str, params: dict) -> dict:
    p = dict(params)
    note_lists = name in ("addNotes", "canAddNotes", "canAddNotesWithErrorDetail")
    for key in ("cards", "notes", "decks", "modelIds", "modelNames", "easeFactors", "keys", "newValues",
                "answers", "inOrderFields", "cardTemplates"):
        if key in p and not (name == "notesInfo" and key == "notes" and p[key] is None):
            p[key] = array(p[key])
    for key in ("cards", "modelIds", "notes"):
        if key in p and p[key] is not None and not (key == "notes" and note_lists):
            p[key] = [identifier(value) for value in p[key]]
    for key in ("card", "note", "deckId", "modelId", "configId", "cloneFrom", "ease", "index", "fontSize", "startID"):
        if key in p:
            p[key] = integer(p[key])
    if "easeFactors" in p:
        p["easeFactors"] = [integer(value) for value in p["easeFactors"]]
    if name == "setDueDate" and type(p.get("days")) is int:
        p["days"] = str(p["days"])
    defaults = {"cardsToo": False, "deleteExisting": True, "add": True, "warning_check": False, "suspend": True,
                "complete": False, "isCloze": False, "front": True, "back": True, "append": False,
                "includeSched": False, "wholeCollection": True}
    if name == "findAndReplaceInModels":
        defaults["css"] = True
    for key, default in defaults.items():
        if key in p:
            p[key] = boolean(p[key], default, key)
    if name == "cardsInfo" and p.get("fields") is not None:
        p["fields"] = array(p["fields"])
    if name == "apiReflect":
        if p.get("scopes") is None:
            p["scopes"] = []
        for key in ("scopes", "actions"):
            if isinstance(p.get(key), str):
                p[key] = array(p[key])
    if isinstance(p.get("note"), dict):
        p["note"] = normalize_note(p["note"])
    if note_lists and "notes" in p:
        p["notes"] = [normalize_note(note) if isinstance(note, dict) else note for note in p["notes"]]
    if name == "answerCards":
        p["answers"] = [{**answer, **{key: integer(answer[key]) for key in ("cardId", "ease") if key in answer}}
                        if isinstance(answer, dict) else answer for answer in p["answers"]]
    return p


def normalize_note(note: dict) -> dict:
    note = dict(note)
    if "id" in note:
        note["id"] = integer(note["id"])
    if note.get("options") is None:
        note["options"] = {}
    options = note["options"]
    if isinstance(options, dict):
        options = note["options"] = dict(options)
        scoped = options.get("duplicateScopeOptions")
        options["duplicateScopeOptions"] = dict(scoped) if isinstance(scoped, dict) else ({} if scoped is None else scoped)
    for kind in ("audio", "video", "picture"):
        if note.get(kind):
            entries = []
            for entry in array(note[kind]):
                if isinstance(entry, dict):
                    entry = dict(entry)
                    if "deleteExisting" in entry:
                        entry["deleteExisting"] = boolean(entry["deleteExisting"], True, "deleteExisting")
                entries.append(entry)
            note[kind] = entries
    return note


def normalize_tags(tags: Any) -> list[str]:
    if tags is None:
        return []
    entries = [tags] if isinstance(tags, str) else tags
    if not isinstance(entries, list) or any(tag is not None and not isinstance(tag, str) for tag in entries):
        raise ApiError("invalidParams", "Must provide tags as a list of strings")
    return list(dict.fromkeys(tag for entry in entries if entry is not None for tag in entry.split()))


def field_name(name: Any, names) -> str | None:
    if name in names:
        return name
    matches = [value for value in names if isinstance(name, str) and value.lower() == name.strip().lower()]
    if len(matches) > 1:
        raise ApiError("compatibilityError", "Ambiguous field name.")
    return matches[0] if matches else None


def match_fields(values: Any, names) -> dict:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ApiError("invalidParams", "Fields must be provided as a dictionary")
    result: dict[str, str] = {}
    for key, value in values.items():
        actual = field_name(key, names)
        if actual is None:
            continue
        value = "" if value is None else value
        if not isinstance(value, str):
            raise ApiError("invalidParams", f"Field values must be strings: {key}")
        if actual in values and key != actual:
            continue
        if actual in result and result[actual] != value:
            raise ApiError("compatibilityError", "Ambiguous field name.")
        result[actual] = value
    return result


def media_targets(entry: dict, fields) -> list[str]:
    return list(dict.fromkeys(actual for field in array(entry.get("fields"))
                              if (actual := field_name(field, fields)) is not None))


def validation_message(result: dict) -> str | None:
    issues = result.get("issues") or []
    if issues:
        return VALIDATION_MESSAGES.get(issues[0]["type"], issues[0]["message"])
    return None


# -- the protocol --------------------------------------------------------------------------------

class Legacy:
    def __init__(self, app):
        self.app = app

    # -- envelope ----------------------------------------------------------------------------

    def handle(self, request: Any, depth: int = 0, profile: str | None = None) -> Any:
        version = 4
        try:
            request = legacy_request(request)
            version = request["version"]
            name = request.get("action", "")
            if name != "requestPermission" and request.get("key") != self.app.api_key:
                raise LegacyError("valid api key must be provided")
            if not isinstance(name, str) or name not in SIGNATURES:
                raise LegacyError("unsupported action")
            params = bind(name, request["params"])
            if name == "multi":
                if depth == 0:
                    self.validate_multi(params["actions"])
                value = [self.handle(action, depth + 1, profile) for action in params["actions"]]
            else:
                value = self.call(name, params, profile)
            return value if version <= 4 else {"result": value, "error": None}
        except Exception as error:  # noqa: BLE001 - every failure becomes an envelope
            return {"result": None, "error": self.message(error)}

    @staticmethod
    def message(error: Exception) -> str:
        if isinstance(error, ApiError) and error.kind == "collectionUnavailable":
            return "collection is not available"
        if isinstance(error, (ApiError, LegacyError)):
            return str(error)
        mapped = from_exception(error)
        return str(mapped) or type(error).__name__

    def validate_multi(self, actions: Any, depth: int = 0, state: dict | None = None) -> None:
        state = state if state is not None else {"exit": False}
        if depth > MAX_MULTI_DEPTH:
            raise LegacyError("multi nesting limit exceeded")
        if not isinstance(actions, list):
            raise LegacyError("multi actions must be an array")
        for item in actions:
            if not isinstance(item, dict):
                raise LegacyError("multi actions must be request objects")
            try:
                item = legacy_request(item)
                name = item.get("action", "")
                if name not in SIGNATURES:
                    continue
                params = bind(name, item["params"])
            except Exception:  # noqa: BLE001 - invalid items fail in their own slot
                continue
            if name == "multi":
                self.validate_multi(params["actions"], depth + 1, state)
            else:
                if state["exit"]:
                    raise LegacyError("guiExitAnki must be the last executable multi action")
                state["exit"] = name == "guiExitAnki"

    # -- dispatch ------------------------------------------------------------------------------

    def call(self, name: str, p: dict, profile: str | None = None) -> Any:
        if name in APP_ACTIONS:
            return self.application(name, p)
        if name == "sync":
            return self.app.with_services(lambda s: self._sync(s), profile)
        handler: Callable[[Services, dict], Any] = getattr(self, "a_" + name)
        return self.app.with_services(lambda services: handler(services, p), profile)

    def application(self, name: str, p: dict) -> Any:
        if name == "version":
            return API_VERSION
        if name == "requestPermission":
            if p.get("allowed"):
                return {"permission": "granted", "requireApikey": bool(self.app.api_key), "version": API_VERSION}
            return {"permission": "denied"}
        if name == "apiReflect":
            if not isinstance(p["scopes"], list):
                raise ApiError("invalidParams", "scopes has invalid value")
            if not (p["actions"] is None or isinstance(p["actions"], list)):
                raise ApiError("invalidParams", "actions has invalid value")
            if "actions" not in p["scopes"]:
                return {"scopes": []}
            names = p["actions"] if p["actions"] is not None else ACTIONS
            return {"scopes": ["actions"], "actions": [n for n in names if n in SIGNATURES]}
        if name == "getProfiles":
            return self.app.profiles.names()
        if name == "getActiveProfile":
            return self.app.profiles.active
        if name == "loadProfile":
            if p["name"] not in self.app.profiles.names():
                return False
            self.app.profiles.switch(p["name"])
            self.app.profiles.host(p["name"]).run(lambda col: None)
            return True
        if name == "guiExitAnki":
            if self.app.allow_exit and self.app.on_exit:
                import threading
                threading.Timer(0.2, self.app.on_exit).start()
            return None
        raise LegacyError("unsupported action")

    # -- notes ---------------------------------------------------------------------------------

    def model_or_error(self, s: Services, name: Any) -> dict:
        model = s.col.models.by_name(name) if isinstance(name, str) else None
        if not model:
            raise ApiError("notFound", f"model was not found: {name}")
        return copy.deepcopy(model)

    def deck_or_error(self, s: Services, name: Any) -> dict:
        deck = s.col.decks.by_name(name) if isinstance(name, str) else None
        if not deck:
            raise ApiError("notFound", f"deck was not found: {name}")
        return deck

    def note_input(self, s: Services, source: Any, placeholders: bool = False) -> dict:
        """Translate a legacy note into a native NoteInput (no media acquired).

        With ``placeholders`` the attachment references are appended using their
        requested filenames, as Anki-Connect does when checking eligibility."""
        if not isinstance(source, dict):
            raise ApiError("invalidParams", "note must be an object")
        source = normalize_note(source)
        if "modelName" not in source:
            raise LegacyError("'modelName'")
        if "deckName" not in source:
            raise LegacyError("'deckName'")
        model = self.model_or_error(s, source["modelName"])
        self.deck_or_error(s, source["deckName"])
        fields = {field["name"]: "" for field in model["flds"]}
        fields.update(match_fields(source.get("fields"), fields))
        options = source.get("options") or {}
        scoped = options.get("duplicateScopeOptions") or {}
        allow = boolean(options.get("allowDuplicate"), False, 'option parameter "allowDuplicate"')
        children = boolean(scoped.get("checkChildren"), False, 'option parameter "duplicateScopeOptions.checkChildren"')
        all_models = boolean(scoped.get("checkAllModels"), False,
                             'option parameter "duplicateScopeOptions.checkAllModels"')
        scope = "deck" if options.get("duplicateScope") == "deck" else "collection"
        duplicates: dict[str, Any] = {"allow": allow, "scope": scope, "includeChildren": children,
                                      "acrossNoteTypes": all_models}
        if scope == "deck":
            deck_name = scoped.get("deckName")
            target = source["deckName"] if deck_name is None else deck_name
            self.deck_or_error(s, target)
            duplicates["deck"] = {"name": target}
        if placeholders:
            for kind in ("audio", "video", "picture"):
                for entry in array(source.get(kind)):
                    if isinstance(entry, dict) and entry:
                        escaped = html.escape(str(entry.get("filename", "")), quote=True)
                        content = f'<img src="{escaped}">' if kind == "picture" else f"[sound:{escaped}]"
                        for field in media_targets(entry, fields):
                            fields[field] += content
        return {"noteType": {"name": model["name"]}, "deck": {"name": source["deckName"]}, "fields": fields,
                "tags": normalize_tags(source.get("tags")), "duplicates": duplicates,
                "rejectEmptyQuestions": False}

    def validate_note(self, s: Services, source: Any) -> dict:
        try:
            result = s.notes_validate(self.note_input(s, source, placeholders=True))
            if not result["valid"]:
                return {"canAdd": False, "error": validation_message(result)}
            return {"canAdd": True}
        except Exception as error:  # noqa: BLE001
            return {"canAdd": False, "error": self.message(error)}

    def store_attachment(self, s: Services, entry: dict, data: bytes) -> str | None:
        filename = ILLEGAL.sub("", os.path.basename(str(entry.get("filename", ""))))
        if not filename:
            raise ApiError("invalidParams", "Attachment filename is empty.")
        skip = {"algorithm": "md5", "digest": entry["skipHash"]} if entry.get("skipHash") else None
        collision = "replace" if entry.get("deleteExisting", True) else "rename"
        return s.store_bytes(filename, data, collision, skip)["filename"]

    def attach(self, s: Services, fields: dict, source: dict) -> None:
        """Download/store inline media and append references to the target fields."""
        for kind in ("audio", "video", "picture"):
            for entry in array(source.get(kind)):
                if not entry or not isinstance(entry, dict):
                    continue
                try:
                    data = acquire(entry)
                except ApiError as error:
                    if str(error) == "Media exceeds the size limit.":
                        raise
                    message = html.escape(str(error), quote=False)
                    for field in media_targets(entry, fields):
                        fields[field] += message
                    continue
                filename = self.store_attachment(s, entry, data)
                if filename is None:
                    continue
                escaped = html.escape(filename, quote=True)
                content = f'<img src="{escaped}">' if kind == "picture" else f"[sound:{escaped}]"
                for field in media_targets(entry, fields):
                    fields[field] += content

    def add_one(self, s: Services, source: dict) -> int:
        result = s.notes_validate(self.note_input(s, source, placeholders=True))
        if not result["valid"]:
            raise LegacyError(validation_message(result) or "cannot create note for unknown reason")
        data = self.note_input(s, source)
        self.attach(s, data["fields"], normalize_note(source))
        data = {**data, "duplicates": {**data["duplicates"], "allow": True}}
        return int(s.notes_create(**data)["noteId"])

    def a_addNote(self, s: Services, p: dict) -> int:
        return self.add_one(s, p["note"])

    def a_addNotes(self, s: Services, p: dict) -> list[int]:
        prepared, errors = [], {}
        for index, source in enumerate(p["notes"]):
            try:
                prepared.append((index, source, self.note_input(s, source)))
            except Exception as error:  # noqa: BLE001
                errors[index] = self.message(error)
        _, failures = s.prepare_notes([self.note_input(s, source, placeholders=True) for _, source, _ in prepared])
        for failure in failures:
            index = prepared[failure["index"]][0]
            details = failure["error"].get("data", {}).get("details") or {}
            errors[index] = validation_message(details) or failure["error"]["message"]
        if errors:
            raise LegacyError(str([errors[index] for index in sorted(errors)]))
        for _, source, data in prepared:
            self.attach(s, data["fields"], normalize_note(source))
        out = s.notes_createMany([data for _, _, data in prepared], atomic=True)
        return [int(item["result"]["noteId"]) for item in out["items"]]

    def a_canAddNote(self, s: Services, p: dict) -> bool:
        return self.validate_note(s, p["note"])["canAdd"]

    def a_canAddNoteWithErrorDetail(self, s: Services, p: dict) -> dict:
        return self.validate_note(s, p["note"])

    def a_canAddNotes(self, s: Services, p: dict) -> list[bool]:
        return [self.validate_note(s, note)["canAdd"] for note in p["notes"]]

    def a_canAddNotesWithErrorDetail(self, s: Services, p: dict) -> list[dict]:
        return [self.validate_note(s, note) for note in p["notes"]]

    def get_note(self, s: Services, nid: Any):
        nid = integer(nid)
        if type(nid) is not int:
            raise ApiError("invalidParams", "Expected a positive signed 64-bit decimal ID.")
        try:
            return s.col.get_note(nid)
        except Exception as error:
            raise ApiError("notFound", f"Note was not found: {nid}") from error

    def update_note(self, s: Services, source: dict, tags_only: bool = False, fields_only: bool = False) -> None:
        note = self.get_note(s, source.get("id"))
        names = list(note.keys())
        patch_fields = None
        if not tags_only and ("fields" in source or any(source.get(k) for k in ("audio", "video", "picture"))):
            patch_fields = match_fields(source.get("fields"), names)
            for kind in ("audio", "video", "picture"):
                for entry in array(source.get(kind)):
                    if isinstance(entry, dict):
                        for field in media_targets(entry, names):
                            patch_fields.setdefault(field, note[field])
        tags = None
        if not fields_only and "tags" in source:
            tags = normalize_tags(source["tags"])
        if patch_fields is None and tags is None:
            raise ApiError("invalidParams", 'Must provide a "fields" or "tags" property.')
        if patch_fields is not None:
            self.attach(s, patch_fields, source)
            for name, value in patch_fields.items():
                note[name] = value
        if tags is not None:
            note.tags = tags
        s.col.update_note(note)

    def a_updateNoteFields(self, s: Services, p: dict) -> None:
        if not isinstance(p["note"], dict):
            raise ApiError("invalidParams", "note must be an object")
        self.update_note(s, p["note"], fields_only=True)

    def a_updateNote(self, s: Services, p: dict) -> None:
        if not isinstance(p["note"], dict):
            raise ApiError("invalidParams", "note must be an object")
        self.update_note(s, p["note"])

    def a_updateNoteTags(self, s: Services, p: dict) -> None:
        self.update_note(s, {"id": p["note"], "tags": p["tags"]}, tags_only=True)

    def a_updateNoteModel(self, s: Services, p: dict) -> None:
        source = p["note"]
        if not isinstance(source, dict) or not source.get("id"):
            raise ApiError("invalidParams", "Note ID is required")
        if not source.get("modelName"):
            raise ApiError("invalidParams", "Model name is required")
        if not source.get("fields") or not isinstance(source["fields"], dict):
            raise ApiError("invalidParams", "Fields must be provided as a dictionary")
        note = self.get_note(s, source["id"])
        target = s.col.models.by_name(source["modelName"])
        if not target:
            raise ApiError("notFound", f"Model '{source['modelName']}' not found")
        tags = normalize_tags(source["tags"]) if "tags" in source else None
        target_names = [field["name"] for field in target["flds"]]
        new_fields = match_fields(source["fields"], target_names)
        old = note.note_type()
        plan = s.notes_planConversion({"id": str(old["id"])}, {"id": str(target["id"])})
        for key, mapping in (("flds", plan["fields"]), ("tmpls", plan["templates"])):
            names = [[item["name"] for item in old[key] if item["name"].lower() == entry["target"].lower()]
                     for entry in mapping]
            for matches in names:
                if len(matches) > 1 or (key == "tmpls" and not matches and len(old[key]) > 1):
                    raise ApiError("compatibilityError", "Explicit conversion mappings are required.")
            if key == "tmpls" and not any(names):
                continue
            for entry, matches in zip(mapping, names):
                entry["source"] = matches[0] if matches else None
        s.notes_convert([str(note.id)], {"id": str(target["id"])}, plan["fields"], plan["templates"], plan["token"])
        note = s.col.get_note(note.id)
        for name, value in new_fields.items():
            note[name] = value
        if tags is not None:
            note.tags = tags
        s.col.update_note(note)

    def a_getNoteTags(self, s: Services, p: dict) -> list[str]:
        return list(self.get_note(s, p["note"]).tags)

    def _tags(self, s: Services, nids: list[int], tags: list[str], remove: bool) -> None:
        changed = []
        for nid in dict.fromkeys(nids):
            try:
                note = s.col.get_note(nid)
            except Exception:
                continue
            before = list(note.tags)
            for tag in tags:
                note.remove_tag(tag) if remove else note.add_tag(tag)
            if note.tags != before:
                changed.append(note)
        if changed:
            s.col.update_notes(changed)

    def a_addTags(self, s: Services, p: dict) -> None:
        self._tags(s, p["notes"], normalize_tags(p["tags"]), not p.get("add", True))

    def a_removeTags(self, s: Services, p: dict) -> None:
        self._tags(s, p["notes"], normalize_tags(p["tags"]), True)

    def a_getTags(self, s: Services, p: dict) -> list[str]:
        return s.tags_list()

    def a_clearUnusedTags(self, s: Services, p: dict) -> None:
        s.col.tags.clear_unused_tags()

    def a_replaceTags(self, s: Services, p: dict) -> None:
        existing = [nid for nid in p["notes"] if s.col.db.scalar("select 1 from notes where id=?", nid)]
        s.tags_replace(**{"from": p["tag_to_replace"], "to": p["replace_with_tag"],
                          "noteIds": [str(nid) for nid in existing]})

    def a_replaceTagsInAllNotes(self, s: Services, p: dict) -> None:
        s.tags_replace(**{"from": p["tag_to_replace"], "to": p["replace_with_tag"], "allNotes": True})

    def a_findNotes(self, s: Services, p: dict) -> list[int]:
        return [] if p["query"] is None else sorted(s.find_note_ids(p["query"]))

    def a_findCards(self, s: Services, p: dict) -> list[int]:
        return [] if p["query"] is None else sorted(s.find_card_ids(p["query"]))

    def note_info(self, s: Services, nid: int) -> dict:
        try:
            note = s.col.get_note(nid)
        except Exception:
            return {}
        model = note.note_type()
        return {"noteId": note.id, "profile": s.profile, "tags": list(note.tags),
                "fields": {field["name"]: {"value": note.fields[index], "order": index}
                           for index, field in enumerate(model["flds"])},
                "modelName": model["name"], "mod": note.mod, "cards": list(note.card_ids())}

    def a_notesInfo(self, s: Services, p: dict) -> list[dict]:
        ids = p.get("notes")
        if p.get("query") is not None:
            ids = sorted(s.find_note_ids(p["query"]))
        if ids is None:
            raise ApiError("invalidParams", 'Must provide either "notes" or a "query"')
        return [self.note_info(s, nid) for nid in ids]

    def a_notesModTime(self, s: Services, p: dict) -> list[dict]:
        out = []
        for nid in p["notes"]:
            mod = s.col.db.scalar("select mod from notes where id=?", nid)
            out.append({"noteId": nid, "mod": mod} if mod is not None else {})
        return out

    def a_deleteNotes(self, s: Services, p: dict) -> None:
        existing = [nid for nid in dict.fromkeys(p["notes"]) if s.col.db.scalar("select 1 from notes where id=?", nid)]
        if existing:
            s.col.remove_notes(existing)

    def a_removeEmptyNotes(self, s: Services, p: dict) -> None:
        raise ApiError("compatibilityError", "Use notes.findEmpty with explicit criteria, then notes.delete.")

    def a_cardsToNotes(self, s: Services, p: dict) -> list[int]:
        out = []
        for cid in p["cards"]:
            nid = s.col.db.scalar("select nid from cards where id=?", cid)
            if nid is not None:
                out.append(nid)
        return list(dict.fromkeys(out))

    # -- cards -----------------------------------------------------------------------------

    def get_card(self, s: Services, cid: Any):
        cid = integer(cid)
        if type(cid) is not int:
            raise ApiError("invalidParams", "Expected a positive signed 64-bit decimal ID.")
        try:
            return s.col.get_card(cid)
        except Exception as error:
            raise ApiError("notFound", f"Card was not found: {cid}") from error

    def card_info(self, s: Services, cid: int, fields: list | None = None) -> dict:
        try:
            card = s.col.get_card(cid)
        except Exception:
            return {}
        result: dict[str, Any] = {"cardId": card.id, "fieldOrder": card.ord, "ord": card.ord, "factor": card.factor,
                                  "interval": card.ivl, "note": card.nid, "type": card.type, "queue": card.queue,
                                  "due": card.due, "reps": card.reps, "lapses": card.lapses, "left": card.left,
                                  "mod": card.mod, "flags": card.flags}
        requested = None if fields is None else set(fields)
        if requested is None or requested & {"fields", "modelName", "css"}:
            note = card.note()
            model = note.note_type()
            if requested is None or "fields" in requested:
                result["fields"] = {field["name"]: {"value": note.fields[index], "order": index}
                                    for index, field in enumerate(model["flds"])}
            if requested is None or "modelName" in requested:
                result["modelName"] = model["name"]
            if requested is None or "css" in requested:
                result["css"] = model["css"]
        if requested is None or "deckName" in requested:
            result["deckName"] = s.col.decks.name(card.did)
        if requested is None or requested & {"question", "answer"}:
            result["question"] = card.question()
            result["answer"] = card.answer()
        if requested is None or "nextReviews" in requested:
            try:
                states = s.col._backend.get_scheduling_states(card.id)
                result["nextReviews"] = list(s.col._backend.describe_next_states(states))
            except Exception:
                result["nextReviews"] = []
        return result if requested is None else {key: value for key, value in result.items() if key in requested}

    def a_cardsInfo(self, s: Services, p: dict) -> list[dict]:
        fields = p.get("fields")
        if fields is not None and (not isinstance(fields, list) or not all(isinstance(f, str) for f in fields)):
            raise ApiError("invalidParams", "fields must be a list of card record field names.")
        return [self.card_info(s, cid, fields) for cid in p["cards"]]

    def a_cardsModTime(self, s: Services, p: dict) -> list[dict]:
        out = []
        for cid in p["cards"]:
            mod = s.col.db.scalar("select mod from cards where id=?", cid)
            out.append({"cardId": cid, "mod": mod} if mod is not None else {})
        return out

    def a_suspend(self, s: Services, p: dict) -> bool:
        cards = [self.get_card(s, cid) for cid in p["cards"]]
        target = p["suspend"]
        changed = [card.id for card in {c.id: c for c in cards}.values() if (card.queue == -1) != target]
        if changed:
            (s.col.sched.suspend_cards if target else s.col.sched.unsuspend_cards)(changed)
        return bool(changed)

    def a_unsuspend(self, s: Services, p: dict) -> None:
        cards = [self.get_card(s, cid) for cid in p["cards"]]
        changed = [card.id for card in cards if card.queue == -1]
        if changed:
            s.col.sched.unsuspend_cards(changed)

    def a_suspended(self, s: Services, p: dict) -> bool:
        return self.get_card(s, p["card"]).queue == -1

    def a_areSuspended(self, s: Services, p: dict) -> list:
        out = []
        for cid in p["cards"]:
            queue = s.col.db.scalar("select queue from cards where id=?", cid)
            out.append(None if queue is None else queue == -1)
        return out

    def a_areDue(self, s: Services, p: dict) -> list[bool]:
        out = []
        for cid in p["cards"]:
            if s.col.find_cards(f"cid:{cid} is:new"):
                out.append(True)
                continue
            rows = s.col.db.all("select id/1000.0, ivl from revlog where cid = ?", cid)
            if not rows:
                raise LegacyError("list index out of range")
            date, ivl = rows[-1]
            out.append(bool(s.col.find_cards(f"cid:{cid} is:due")) if ivl >= -1200 else date - ivl <= time.time())
        return out

    def a_getIntervals(self, s: Services, p: dict) -> list:
        out: list = []
        for cid in p["cards"]:
            if s.col.find_cards(f"cid:{cid} is:new"):
                out.append(0)
                continue
            intervals = s.col.db.list("select ivl from revlog where cid = ?", cid)
            if p["complete"]:
                out.append(intervals)
            else:
                if not intervals:
                    raise LegacyError("list index out of range")
                out.append(intervals[-1])
        return out

    def a_getEaseFactors(self, s: Services, p: dict) -> list:
        return [s.col.db.scalar("select factor from cards where id=?", cid) for cid in p["cards"]]

    def a_setEaseFactors(self, s: Services, p: dict) -> list[bool]:
        out = []
        for index, cid in enumerate(p["cards"]):
            try:
                card = s.col.get_card(cid)
            except Exception:
                out.append(False)
                continue
            card.factor = p["easeFactors"][index]
            s.col.update_card(card)
            out.append(True)
        return out

    def a_setSpecificValueOfCard(self, s: Services, p: dict) -> Any:
        protected = {"did", "id", "ivl", "lapses", "left", "mod", "nid", "odid", "odue", "ord", "queue", "reps",
                     "type", "usn"}
        if (type(p["card"]) is not int or not isinstance(p["keys"], list) or not isinstance(p["newValues"], list)
                or len(p["keys"]) != len(p["newValues"])):
            return False
        if not p["warning_check"] and protected.intersection(p["keys"]):
            return False
        if len(set(p["keys"])) != len(p["keys"]):
            raise ApiError("compatibilityError", "Duplicate card keys.")
        mapping = {"factor": "sm2EasePermille", "ivl": "intervalDays", "reps": "repetitions", "lapses": "lapses",
                   "custom_data": "customData"}
        if any(key not in {*mapping, "did", "flags"} for key in p["keys"]):
            raise ApiError("compatibilityError", "Use native scheduling commands for protected state.")
        if any(key in p["keys"] for key in ("did", "flags")) and len(p["keys"]) != 1:
            raise ApiError("compatibilityError", "Separate deck/flag edits from metadata edits.")
        try:
            card = self.get_card(s, p["card"])
            values = dict(zip(p["keys"], p["newValues"]))
            if "did" in values:
                deck = s.col.decks.get(int(values["did"]), default=False)
                if not deck or deck.get("dyn"):
                    raise ApiError("notFound", "deck was not found: " + str(values["did"]))
                s.col.set_deck([card.id], deck["id"])
            elif "flags" in values:
                s.col.set_user_flag_for_cards(int(values["flags"]), [card.id])
            else:
                patch = {}
                for key, value in values.items():
                    patch[mapping[key]] = value if key == "custom_data" else int(value)
                s.advanced_cards_update(str(card.id), patch)
            return [True]
        except Exception as error:  # noqa: BLE001
            return [[False, self.message(error)]]

    def a_forgetCards(self, s: Services, p: dict) -> None:
        for cid in p["cards"]:
            self.get_card(s, cid)
        s.scheduling_reset([str(cid) for cid in p["cards"]])

    def answer(self, s: Services, cid: int, ease: Any) -> bool:
        if ease not in (1, 2, 3, 4):
            raise ApiError("invalidParams", "Invalid ease.")
        try:
            card = s.col.get_card(cid)
        except Exception:
            return False
        if card.queue < 0 or card.queue == 4:
            raise ApiError("invalidState", "This card cannot be answered outside the reviewer.")
        s.answer_native(card, RATINGS[ease - 1], elapsed_ms=None)
        return True

    def a_relearnCards(self, s: Services, p: dict) -> None:
        cards = [self.get_card(s, cid) for cid in p["cards"]]
        for card in cards:
            if card.queue != 2 or card.odid:
                raise ApiError("invalidState", "Relearning requires an unfiltered active review card.")
        for card in cards:
            self.answer(s, card.id, 1)

    def a_answerCards(self, s: Services, p: dict) -> list[bool]:
        out = []
        for answer in p["answers"]:
            if not isinstance(answer, dict):
                raise ApiError("invalidParams", "answers must be objects")
            out.append(self.answer(s, answer.get("cardId"), answer.get("ease")))
        return out

    def a_setDueDate(self, s: Services, p: dict) -> bool:
        cids = [self.get_card(s, cid).id for cid in p["cards"]]
        if cids:
            s.col.sched.set_due_date(cids, str(p["days"]))
        return True

    # -- decks ---------------------------------------------------------------------------------

    def a_deckNames(self, s: Services, p: dict) -> list[str]:
        return [entry.name for entry in s.col.decks.all_names_and_ids()]

    def a_deckNamesAndIds(self, s: Services, p: dict) -> dict:
        return {entry.name: entry.id for entry in s.col.decks.all_names_and_ids()}

    def a_getDecks(self, s: Services, p: dict) -> dict:
        out: dict[str, list] = {}
        for cid in p["cards"]:
            card = self.get_card(s, cid)
            out.setdefault(s.col.decks.name(card.did), []).append(cid)
        return out

    def a_createDeck(self, s: Services, p: dict) -> int:
        if not isinstance(p["deck"], str) or not p["deck"].strip():
            raise ApiError("invalidParams", "Deck name must be a non-empty string.")
        return int(s.decks_create(p["deck"])["id"])

    def a_changeDeck(self, s: Services, p: dict) -> None:
        target = s.decks_create(p["deck"])
        deck = s.col.decks.get(int(target["id"]))
        if deck.get("dyn"):
            raise ApiError("invalidState", "Filtered decks cannot be move destinations.")
        cards = [self.get_card(s, cid) for cid in p["cards"]]
        move = [card.id for card in cards if card.odid or card.did != deck["id"]]
        if move:
            s.col.set_deck(move, deck["id"])

    def a_deleteDecks(self, s: Services, p: dict) -> None:
        if not p["cardsToo"]:
            raise ApiError("invalidParams",
                           "Since Anki 2.1.28 it's not possible to delete decks without deleting cards as well")
        ids = [deck["id"] for name in p["decks"] if (deck := s.col.decks.by_name(name))]
        if ids:
            s.col.decks.remove(ids)

    def a_getDeckConfig(self, s: Services, p: dict) -> Any:
        deck = s.col.decks.by_name(p["deck"]) if isinstance(p["deck"], str) else None
        if not deck or deck.get("dyn"):
            return False
        return copy.deepcopy(s.col.decks.get_config(deck["conf"]))

    @staticmethod
    def preset_or_none(s: Services, config_id: Any) -> dict | None:
        """Anki's get_config falls back to the Default preset; legacy callers need None."""
        if type(config_id) is not int:
            return None
        if not any(conf["id"] == config_id for conf in s.col.decks.all_config()):
            return None
        return s.col.decks.get_config(config_id)

    def a_saveDeckConfig(self, s: Services, p: dict) -> bool:
        config = p["config"]
        try:
            if not isinstance(config, dict) or "id" not in config:
                return False
            baseline = self.preset_or_none(s, integer(config["id"]))
            if not baseline:
                return False
            merged = copy.deepcopy(baseline)
            for key, value in config.items():
                if key in ("mod", "usn", "id"):
                    continue
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
            s.col.decks.update_config(merged)
            return True
        except Exception:  # noqa: BLE001 - legacy reports false
            return False

    def a_setDeckConfigId(self, s: Services, p: dict) -> bool:
        config_id = integer(p["configId"])
        if not self.preset_or_none(s, config_id):
            return False
        decks = [s.col.decks.by_name(name) for name in p["decks"]]
        if not all(decks) or any(deck.get("dyn") for deck in decks):
            return False
        for deck in decks:
            deck["conf"] = config_id
            s.col.decks.save(deck)
        return True

    def a_cloneDeckConfigId(self, s: Services, p: dict) -> Any:
        source = integer(p["cloneFrom"])
        conf = self.preset_or_none(s, source)
        if not conf:
            return False
        return s.col.decks.add_config_returning_id(p["name"], conf)

    def a_removeDeckConfigId(self, s: Services, p: dict) -> bool:
        config_id = integer(p["configId"])
        if config_id == 1 or not self.preset_or_none(s, config_id):
            return False
        s.col.decks.remove_config(config_id)
        return True

    def a_getDeckStats(self, s: Services, p: dict) -> dict:
        out = {}
        for name in p["decks"]:
            deck = s.decks_create(name)
            counts = s.decks_getCounts({"id": deck["id"]})
            out[deck["id"]] = {"deck_id": int(deck["id"]), "name": name, "new_count": counts["new"],
                               "learn_count": counts["learning"], "review_count": counts["review"],
                               "total_in_deck": counts["total"]}
        return out

    def a_deckNameFromId(self, s: Services, p: dict) -> str:
        deck = s.col.decks.get(p["deckId"], default=False) if type(p["deckId"]) is int else None
        if not deck:
            raise ApiError("notFound", f"deck was not found: {p['deckId']}")
        return deck["name"]

    # -- media ---------------------------------------------------------------------------------

    def a_storeMediaFile(self, s: Services, p: dict) -> Any:
        data = acquire({key: p.get(key) for key in ("data", "path", "url")})
        return self.store_attachment(s, {"filename": p["filename"], "skipHash": p.get("skipHash"),
                                         "deleteExisting": p["deleteExisting"]}, data)

    def a_retrieveMediaFile(self, s: Services, p: dict) -> Any:
        name = os.path.basename(str(p["filename"]))
        path = os.path.join(s.col.media.dir(), name)
        if not name or not os.path.isfile(path):
            return False
        with open(path, "rb") as file:
            return base64.b64encode(file.read()).decode("ascii")

    def a_getMediaFilesNames(self, s: Services, p: dict) -> list[str]:
        return s.media_list(p["pattern"])

    def a_deleteMediaFile(self, s: Services, p: dict) -> None:
        try:
            s.media_delete(p["filename"])
        except ApiError as error:
            if error.kind != "notFound":
                raise

    def a_getMediaDirPath(self, s: Services, p: dict) -> str:
        return s.media_getDirectory()["path"]

    # -- note types ------------------------------------------------------------------------------

    def a_modelNames(self, s: Services, p: dict) -> list[str]:
        return [entry.name for entry in s.col.models.all_names_and_ids()]

    def a_modelNamesAndIds(self, s: Services, p: dict) -> dict:
        return {entry.name: entry.id for entry in s.col.models.all_names_and_ids()}

    def a_findModelsById(self, s: Services, p: dict) -> list[dict]:
        out = []
        for mid in p["modelIds"]:
            model = s.col.models.get(mid)
            if not model:
                raise ApiError("notFound", f"model was not found: {mid}")
            out.append(copy.deepcopy(model))
        return out

    def a_findModelsByName(self, s: Services, p: dict) -> list[dict]:
        return [self.model_or_error(s, name) for name in p["modelNames"]]

    def a_modelNameFromId(self, s: Services, p: dict) -> str:
        model = s.col.models.get(p["modelId"]) if type(p["modelId"]) is int else None
        if not model:
            raise ApiError("notFound", f"model was not found: {p['modelId']}")
        return model["name"]

    def a_modelFieldNames(self, s: Services, p: dict) -> list[str]:
        return [field["name"] for field in self.model_or_error(s, p["modelName"])["flds"]]

    def a_modelFieldDescriptions(self, s: Services, p: dict) -> list[str]:
        return [field.get("description", "") or "" for field in self.model_or_error(s, p["modelName"])["flds"]]

    def a_modelFieldFonts(self, s: Services, p: dict) -> dict:
        return {field["name"]: {"font": field["font"], "size": field["size"]}
                for field in self.model_or_error(s, p["modelName"])["flds"]}

    def a_modelFieldsOnTemplates(self, s: Services, p: dict) -> dict:
        self.model_or_error(s, p["modelName"])
        usage = s.noteTypes_getTemplateUsage({"name": p["modelName"]})
        return {item["templateName"]: [item["questionFields"],
                                       [f for f in item["answerFields"] if f not in item["questionFields"]]]
                for item in usage}

    def a_modelTemplates(self, s: Services, p: dict) -> dict:
        return {template["name"]: {"Front": template["qfmt"], "Back": template["afmt"]}
                for template in self.model_or_error(s, p["modelName"])["tmpls"]}

    def a_modelStyling(self, s: Services, p: dict) -> dict:
        return {"css": self.model_or_error(s, p["modelName"])["css"]}

    def a_createModel(self, s: Services, p: dict) -> dict:
        if not p["inOrderFields"]:
            raise ApiError("invalidParams", "Must provide at least one field for inOrderFields")
        if not p["cardTemplates"]:
            raise ApiError("invalidParams", "Must provide at least one card for cardTemplates")
        if s.col.models.by_name(p["modelName"]):
            raise ApiError("conflict", "Model name already exists")
        templates = []
        for index, template in enumerate(p["cardTemplates"]):
            if not isinstance(template, dict) or "Front" not in template or "Back" not in template:
                raise ApiError("invalidParams", "Card templates need Front and Back.")
            templates.append({"name": template.get("Name") or f"Card {index + 1}", "questionHtml": template["Front"],
                              "answerHtml": template["Back"]})
        created = s.noteTypes_create(name=p["modelName"], fields=[{"name": name} for name in p["inOrderFields"]],
                                     templates=templates, kind="cloze" if p["isCloze"] else "normal",
                                     css=p["css"] if p["css"] is not None else "")
        return copy.deepcopy(s.col.models.get(int(created["id"])))

    def a_updateModelTemplates(self, s: Services, p: dict) -> None:
        model_input = p["model"]
        model = self.model_or_error(s, model_input.get("name"))
        templates = model_input.get("templates") or {}
        changed = False
        for template in model["tmpls"]:
            value = templates.get(template["name"], {})
            for old, new in (("Front", "qfmt"), ("Back", "afmt")):
                if value.get(old):
                    template[new] = value[old]
                    changed = True
        if changed:
            s.col.models.update_dict(model)

    def a_updateModelStyling(self, s: Services, p: dict) -> None:
        model = self.model_or_error(s, p["model"].get("name"))
        model["css"] = p["model"]["css"]
        s.col.models.update_dict(model)

    def a_findAndReplaceInModels(self, s: Services, p: dict) -> int:
        targets = [new for old, new in (("front", "question"), ("back", "answer"), ("css", "css")) if p[old]]
        if not targets:
            return 0
        selector = {"noteTypes": [{"name": p["modelName"]}]} if p["modelName"] else {"allNoteTypes": True}
        if p["modelName"]:
            self.model_or_error(s, p["modelName"])
        return s.noteTypes_replaceText(find=p["findText"], replace=p["replaceText"], targets=targets,
                                       **selector)["changedCount"]

    def _edit(self, s: Services, model_name: str, edits: list[dict]) -> None:
        model = self.model_or_error(s, model_name)
        names = {"field": {f["name"] for f in model["flds"]}, "template": {t["name"] for t in model["tmpls"]}}
        for edit in edits:
            kind = "field" if edit["op"].endswith("Field") else "template"
            if edit["op"].startswith("add"):
                names[kind].add(edit[kind]["name"])
                continue
            if edit["name"] not in names[kind]:
                raise ApiError("notFound", f"{kind} was not found in {model['name']}: {edit['name']}")
        s.noteTypes_editStructure({"name": model_name}, edits)

    def a_modelTemplateRename(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "updateTemplate", "name": p["oldTemplateName"],
                                        "patch": {"name": p["newTemplateName"]}}])

    def a_modelTemplateReposition(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "moveTemplate", "name": p["templateName"], "index": p["index"]}])

    def a_modelTemplateAdd(self, s: Services, p: dict) -> None:
        template = p["template"]
        data = {"name": template["Name"], "questionHtml": template["Front"], "answerHtml": template["Back"]}
        model = self.model_or_error(s, p["modelName"])
        if template["Name"] in [t["name"] for t in model["tmpls"]]:
            edits = [{"op": "updateTemplate", "name": template["Name"], "patch": data}]
        else:
            edits = [{"op": "addTemplate", "template": data}]
        self._edit(s, p["modelName"], edits)

    def a_modelTemplateRemove(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "removeTemplate", "name": p["templateName"]}])

    def a_modelFieldRename(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "updateField", "name": p["oldFieldName"],
                                        "patch": {"name": p["newFieldName"]}}])

    def a_modelFieldReposition(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "moveField", "name": p["fieldName"], "index": p["index"]}])

    def a_modelFieldAdd(self, s: Services, p: dict) -> None:
        model = self.model_or_error(s, p["modelName"])
        edits = []
        if p["fieldName"] not in [f["name"] for f in model["flds"]]:
            edits.append({"op": "addField", "field": {"name": p["fieldName"]}})
        if p["index"] is not None:
            edits.append({"op": "moveField", "name": p["fieldName"], "index": p["index"]})
        if edits:
            self._edit(s, p["modelName"], edits)

    def a_modelFieldRemove(self, s: Services, p: dict) -> None:
        self._edit(s, p["modelName"], [{"op": "removeField", "name": p["fieldName"]}])

    def _set_field(self, s: Services, p: dict, key: str, source: str, expected: type, label: str) -> None:
        if not isinstance(p[source], expected) or (expected is int and isinstance(p[source], bool)):
            raise ApiError("invalidParams", f"{source} should be {label}: {p[source]}")
        self._edit(s, p["modelName"], [{"op": "updateField", "name": p["fieldName"], "patch": {key: p[source]}}])

    def a_modelFieldSetFont(self, s: Services, p: dict) -> None:
        self._set_field(s, p, "fontFamily", "font", str, "a string")

    def a_modelFieldSetFontSize(self, s: Services, p: dict) -> None:
        self._set_field(s, p, "fontSize", "fontSize", int, "an integer")

    def a_modelFieldSetDescription(self, s: Services, p: dict) -> bool:
        self._set_field(s, p, "description", "description", str, "a string")
        return True

    # -- statistics and review history -----------------------------------------------------------

    def a_getNumCardsReviewedToday(self, s: Services, p: dict) -> int:
        return s.statistics_getToday()["count"]

    def a_getNumCardsReviewedByDay(self, s: Services, p: dict) -> list:
        return [[entry["day"], entry["count"]] for entry in s.statistics_getReviewDays()]

    def a_getCollectionStatsHTML(self, s: Services, p: dict) -> str:
        deck = None if p["wholeCollection"] else {"id": str(s.col.decks.selected())}
        return s.statistics_getHtml(deck)["html"]

    def a_cardReviews(self, s: Services, p: dict) -> list:
        deck = s.decks_create(p["deck"]) if isinstance(p["deck"], str) else None
        if deck is None:
            raise ApiError("invalidParams", "deck must be a name")
        start = integer(p["startID"]) or 0
        rows = s.col.db.all(
            "select id,cid,usn,ease,ivl,lastIvl,factor,time,type from revlog where id>? and cid in "
            "(select id from cards where did=?) order by id", start, int(deck["id"]))
        return [list(row) for row in rows]

    def a_getReviewsOfCards(self, s: Services, p: dict) -> dict:
        out: dict[str, list] = {str(cid): [] for cid in p["cards"]}
        if not p["cards"]:
            return out
        rows = s.col.db.all(
            f"select id,cid,usn,ease,ivl,lastIvl,factor,time,type from revlog where cid in "
            f"({','.join(map(str, p['cards']))}) order by id")
        for rid, cid, usn, ease, ivl, last, factor, elapsed, kind in rows:
            out[str(cid)].append({"id": rid, "usn": usn, "ease": ease, "ivl": ivl, "lastIvl": last,
                                  "factor": factor, "time": elapsed, "type": kind})
        return out

    def a_getLatestReviewID(self, s: Services, p: dict) -> int:
        deck = s.decks_create(p["deck"])
        value = s.col.db.scalar("select max(id) from revlog where cid in (select id from cards where did=?)",
                                int(deck["id"]))
        return int(value or 0)

    def a_insertReviews(self, s: Services, p: dict) -> None:
        values = []
        for row in array(p["reviews"]):
            if not isinstance(row, (list, tuple)) or len(row) != 9 or not all(type(v) is int for v in row):
                raise ApiError("invalidParams", "Review rows require nine integers.")
            rid, cid, _usn, ease, ivl, last, factor, elapsed, kind = row
            if not 0 <= ease <= 4 or not 0 <= kind <= 5:
                raise ApiError("invalidParams", "Invalid review rating/kind.")
            values.append({"id": str(rid), "cardId": str(cid), "rating": RATINGS[ease - 1] if ease else None,
                           "interval": {"value": abs(ivl), "unit": "seconds" if ivl < 0 else "days"},
                           "previousInterval": {"value": abs(last), "unit": "seconds" if last < 0 else "days"},
                           "factor": {"encoding": "unknown", "value": max(0, factor)}, "elapsedMs": max(0, elapsed),
                           "kind": ("learning", "review", "relearning", "filtered", "manual", "rescheduled")[kind]})
        if values:
            s.advanced_reviews_import(values)

    # -- packages and collection ---------------------------------------------------------------

    def a_exportPackage(self, s: Services, p: dict) -> bool:
        if not isinstance(p["deck"], str) or not s.col.decks.by_name(p["deck"]):
            return False
        s.packages_export({"name": p["deck"]}, p["path"], includeScheduling=p["includeSched"])
        return True

    def a_importPackage(self, s: Services, p: dict) -> bool:
        path = p["path"]
        if not os.path.isabs(path):
            path = os.path.join(s.col.media.dir(), path)
        with open(path, "rb"):
            pass
        s.packages_import(path)
        return True

    def a_reloadCollection(self, s: Services, p: dict) -> None:
        s.collection_refresh("cachesAndWindows")

    def _sync(self, s: Services) -> None:
        result = s.sync_run("auto")
        if result.get("fullSync") == "either":
            raise ApiError("invalidState", "A full sync is required; choose upload or download with sync.run.")

    # -- GUI ---------------------------------------------------------------------------------------

    def a_guiBrowse(self, s: Services, p: dict) -> list[int]:
        sort = p["reorderCards"]
        if sort is not None:
            if not isinstance(sort, dict):
                raise ApiError("invalidParams", "reorderCards should be a dict: " + str(sort))
            if "columnId" not in sort or "order" not in sort:
                raise ApiError("invalidParams", 'Must provide a "columnId" and a "order" property"')
            if sort["order"] not in ("ascending", "descending"):
                raise ApiError("invalidParams", "invalid card order: " + str(sort["order"]))
            if s.col.get_browser_column(sort["columnId"]) is None:
                raise ApiError("invalidParams", "invalid columnId: " + str(sort["columnId"]))
            sort = {"column": sort["columnId"], "direction": sort["order"]}
        s.browser_open(p["query"], sort)
        if p["query"] is None:
            return []
        return s.browser_results() if sort else sorted(s.find_card_ids(p["query"]))

    def a_guiSelectCard(self, s: Services, p: dict) -> bool:
        if not s.state.browser["open"]:
            return False
        s.browser_select(cardIds=[str(p["card"])])
        return True

    def a_guiSelectNote(self, s: Services, p: dict) -> bool:
        if not s.state.browser["open"]:
            return False
        s.browser_select(cardIds=[str(p["note"])])
        return True

    def a_guiSelectedNotes(self, s: Services, p: dict) -> list[int]:
        return [int(nid) for nid in s.browser_state()["selectedNoteIds"]]

    def a_guiEditNote(self, s: Services, p: dict) -> None:
        s.editors_openNote(str(p["note"]))

    def _add_editor(self, s: Services) -> str | None:
        drafts = [key for key, value in s.state.editors.items() if value["kind"] == "add"]
        return drafts[-1] if drafts else None

    def a_guiAddCards(self, s: Services, p: dict) -> int:
        note = p["note"]
        draft = None
        if note:
            data = self.note_input(s, note)
            self.attach(s, data["fields"], normalize_note(note))
            draft = {"noteType": data["noteType"], "deck": data["deck"], "fields": data["fields"],
                     "tags": data["tags"]}
        existing = self._add_editor(s)
        if existing and s.state.editors[existing]["dirty"] and draft:
            raise ApiError("editorConflict", "The Add dialog has unsaved content.")
        if existing:
            s.editors_close(existing)
        s.editors_openAdd(draft)
        return 0

    def a_guiAddNoteSetData(self, s: Services, p: dict) -> Any:
        editor_id = self._add_editor(s)
        if editor_id is None:
            return {"error": "Add Note dialog is not open", "code": 1}
        source = copy.deepcopy(p["note"]) if isinstance(p["note"], dict) else {}
        patch: dict[str, Any] = {}
        for key, kind, label in (("deckName", "deck", "Deck"), ("modelName", "noteType", "Model")):
            if key in source:
                manager = s.col.decks if kind == "deck" else s.col.models
                if not manager.by_name(source[key]):
                    raise ApiError("notFound", f'{label} "{source[key]}" not found')
                patch[kind] = {"name": source[key]}
        if "fields" in source:
            editor = s.state.editors[editor_id]
            names = list(editor["fields"])
            if "modelName" in source:
                names = [f["name"] for f in s.col.models.by_name(source["modelName"])["flds"]]
            for field in source["fields"] or {}:
                if field_name(field, names) is None:
                    raise ApiError("notFound", f'Field "{field}" not found in current note')
            fields = match_fields(source["fields"], names)
            self.attach(s, fields, normalize_note(source))
            patch["fields"] = fields
        if "tags" in source:
            patch["tags"] = normalize_tags(source["tags"])
        if patch:
            s.editors_updateDraft(editor_id, patch, "append" if p["append"] else "replace")
        return True

    def a_guiReviewActive(self, s: Services, p: dict) -> bool:
        return s.reviewer_get()["active"]

    def a_guiCurrentCard(self, s: Services, p: dict) -> dict:
        state = s.reviewer_get()
        if not state["active"]:
            raise ApiError("invalidState", "Gui review is not currently active.")
        card = s.col.get_card(int(state["card"]["id"]))
        info = self.card_info(s, card.id)
        keep = ("cardId", "fields", "fieldOrder", "question", "answer", "modelName", "deckName", "css")
        return {**{key: info[key] for key in keep}, "buttons": [1, 2, 3, 4],
                "nextReviews": [answer["label"] for answer in state["answers"]], "template": card.template()["name"]}

    def _reviewer_action(self, s: Services, method: str) -> bool:
        state = s.reviewer_get()
        if not state["active"]:
            return False
        getattr(s, method)(state["stateToken"])
        return True

    def a_guiStartCardTimer(self, s: Services, p: dict) -> bool:
        return self._reviewer_action(s, "reviewer_startTimer")

    def a_guiShowQuestion(self, s: Services, p: dict) -> bool:
        return self._reviewer_action(s, "reviewer_showQuestion")

    def a_guiShowAnswer(self, s: Services, p: dict) -> bool:
        return self._reviewer_action(s, "reviewer_showAnswer")

    def a_guiPlayAudio(self, s: Services, p: dict) -> bool:
        return self._reviewer_action(s, "reviewer_playAudio")

    def a_guiAnswerCard(self, s: Services, p: dict) -> bool:
        state = s.reviewer_get()
        ease = p["ease"]
        if not state["active"] or state["side"] != "answer" or type(ease) is not int or ease not in (1, 2, 3, 4):
            return False
        s.reviewer_answer(state["stateToken"], RATINGS[ease - 1])
        return True

    def a_guiUndo(self, s: Services, p: dict) -> bool:
        if s.col.undo_status().undo:
            if s.state.reviewer.get("active"):
                s.reviewer_undo()
            else:
                s.col.undo()
        return True

    def a_guiDeckOverview(self, s: Services, p: dict) -> bool:
        if not isinstance(p["name"], str) or not s.col.decks.by_name(p["name"]):
            return False
        s.application_navigate("deckOverview", {"name": p["name"]})
        return True

    def a_guiDeckBrowser(self, s: Services, p: dict) -> None:
        s.application_navigate("deckBrowser")

    def a_guiDeckReview(self, s: Services, p: dict) -> bool:
        if not isinstance(p["name"], str) or not s.col.decks.by_name(p["name"]):
            return False
        s.reviewer_start({"name": p["name"]})
        return True

    def a_guiImportFile(self, s: Services, p: dict) -> None:
        s.application_importFile(p["path"])

    def a_guiCheckDatabase(self, s: Services, p: dict) -> bool:
        s.collection_checkIntegrity()
        return True
