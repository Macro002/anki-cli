"""Registry of API methods: parameters, scope, effects, completion and undo behaviour.

The first block is the Anki-Connect v1 contract. The second block lists anki-cli
extensions, which use the same conventions (references, string IDs, items).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import params as P
from .params import MISSING, OPTIONAL


@dataclass(frozen=True)
class Method:
    name: str
    validate: Callable
    scope: str = "collection"          # collection | application
    effect: str = "read"               # read | write | media | filesystem | gui | lifecycle | ...
    completion: str = "completed"      # completed | operation
    undo: str = "none"                 # none | single | perItem | grouped | ...
    summary: str = ""
    extension: bool = False
    tags: tuple = field(default_factory=tuple)


def spec(**properties) -> Callable:
    """Shorthand: ``name=(validator, default)``; ``session`` is accepted everywhere."""
    properties.setdefault("session", (P.string(1), OPTIONAL))
    return P.obj(properties)


def app_spec(**properties) -> Callable:
    return P.obj(properties)


def opt(validator, default=OPTIONAL):
    return (validator, default)


def req(validator):
    return (validator, MISSING)


B = P.boolean()
LIMIT = opt(P.LIMIT, 100)
CURSOR = opt(P.TEXT)
SORT = opt(P.SORT)

METHODS: dict[str, Method] = {}


def register(name: str, validate: Callable, **meta) -> None:
    METHODS[name] = Method(name, validate, **meta)


W = dict(effect="write", undo="single")

# -- Anki-Connect API v1 ---------------------------------------------------------------------

register("api.describe", app_spec(), scope="application", summary="Methods, limits and runtime capabilities.")
register("api.execute", app_spec(commands=req(P.array(P.COMMAND, 0, 100))), scope="application",
         effect="batch", completion="operation", undo="perCommand", summary="Run commands in order.")
register("access.requestPermission", app_spec(), scope="application", effect="permission")
register("profiles.list", app_spec(), scope="application")
register("profiles.getActive", app_spec(), scope="application")
register("profiles.switch", app_spec(name=req(P.TEXT)), scope="application", effect="lifecycle",
         completion="operation")
register("collection.get", spec())
register("collection.sync", spec(includeMedia=opt(B, True)), effect="lifecycle", completion="operation")
register("collection.refresh", spec(target=opt(P.enum("windows", "cachesAndWindows"), "windows")), effect="refresh")
register("collection.checkIntegrity", spec(), effect="write", completion="operation", undo="clears")
register("collection.undo", spec(), effect="write", completion="operation", undo="undo")

register("notes.get", spec(id=req(P.ID)))
register("notes.getMany", spec(ids=req(P.IDS)))
register("notes.search", spec(query=req(P.string()), limit=LIMIT, cursor=CURSOR, sort=SORT))
register("notes.validate", spec(note=req(P.NOTE_INPUT)))
register("notes.validateMany", spec(notes=req(P.array(P.NOTE_INPUT))))
register("notes.create", spec(noteType=req(P.REFERENCE), deck=req(P.REFERENCE), fields=req(P.FIELDS),
                              tags=opt(P.TAGS, list), duplicates=opt(P.DUPLICATES),
                              rejectEmptyQuestions=opt(B, True)), **W)
register("notes.createMany", spec(notes=req(P.array(P.NOTE_INPUT)), atomic=opt(B, False)),
         effect="write", undo="perItemOrAtomic")
register("notes.update", spec(id=req(P.ID), patch=req(P.NOTE_PATCH)), **W)
register("notes.delete", spec(ids=req(P.IDS)), effect="write", undo="perItem")
register("notes.planConversion", spec(source=req(P.REFERENCE), target=req(P.REFERENCE)))
register("notes.convert", spec(ids=req(P.IDS), target=req(P.REFERENCE),
                               fields=req(P.array(P.CONVERSION_MAPPING)),
                               templates=req(P.array(P.CONVERSION_MAPPING)), planToken=req(P.TEXT)), **W)
register("notes.findEmpty", spec(criterion=req(P.enum("allFieldsEmpty", "noCards", "allQuestionsEmpty")),
                                 query=opt(P.string(), ""), limit=LIMIT, cursor=CURSOR))

register("tags.list", spec())
register("tags.add", spec(noteIds=req(P.IDS), tags=req(P.TAGS)), effect="write", undo="perItem")
register("tags.remove", spec(noteIds=req(P.IDS), tags=req(P.TAGS)), effect="write", undo="perItem")
register("tags.replace", P.obj({"from": req(P.TEXT), "to": req(P.TEXT), "noteIds": opt(P.IDS),
                                "allNotes": opt(B, False), "session": opt(P.string(1))},
                               check=lambda v, p: _tags_replace_check(v, p)), **W)
register("tags.deleteUnused", spec(), **W)

register("cards.get", spec(id=req(P.ID)))
register("cards.getMany", spec(ids=req(P.IDS)))
register("cards.search", spec(query=req(P.string()), limit=LIMIT, cursor=CURSOR, sort=SORT))
register("cards.render", spec(id=req(P.ID)))
register("cards.move", spec(ids=req(P.IDS), deck=req(P.REFERENCE)), effect="write", undo="perItem")
register("cards.setSuspended", spec(ids=req(P.IDS), suspended=req(B)), effect="write", undo="perItem")
register("cards.setFlags", spec(ids=req(P.IDS), flag=req(P.integer(0, 7))), effect="write", undo="perItem")

register("scheduling.get", spec(cardId=req(P.ID)))
register("scheduling.getQueue", spec(fetchLimit=opt(P.integer(1, 1000), 1)))
register("scheduling.predict", spec(cardId=req(P.ID)))
register("scheduling.getDue", spec(cardId=req(P.ID), includeLearnAhead=opt(B, False)))
register("scheduling.answer", spec(cardId=req(P.ID), rating=req(P.RATING), stateToken=req(P.TEXT),
                                   elapsedMs=opt(P.integer(0), 0)), **W)
register("scheduling.answerMany", spec(answers=req(P.array(P.ANSWER))), effect="write", undo="perItem")
register("scheduling.reset", spec(cardIds=req(P.IDS), restorePosition=opt(B, True), resetCounts=opt(B, False),
                                  log=opt(B, True)), effect="write", undo="perItem")
register("scheduling.setDueDate", spec(cardIds=req(P.IDS), days=req(P.TEXT)), effect="write", undo="perItem")

register("decks.list", spec())
register("decks.get", spec(deck=req(P.REFERENCE)))
register("decks.create", spec(name=req(P.TEXT)), **W)
register("decks.update", spec(deck=req(P.REFERENCE), name=req(P.TEXT)), **W)
register("decks.delete", spec(decks=req(P.REFERENCES), deleteCards=req(P.const(True))), effect="write",
         undo="perItem")
register("decks.getCounts", spec(deck=req(P.REFERENCE), includeChildren=opt(B, True)))

register("deckPresets.list", spec())
register("deckPresets.get", spec(preset=req(P.REFERENCE)))
register("deckPresets.create", spec(name=req(P.TEXT), cloneFrom=opt(P.REFERENCE)), **W)
register("deckPresets.update", P.obj({"preset": req(P.REFERENCE), "name": opt(P.TEXT), "settings": opt(P.PRESET_PATCH),
                                     "rescheduleFsrs": opt(B, False), "session": opt(P.string(1))},
                                    check=lambda v, p: _needs_any(v, p, "name", "settings")),
         completion="operation", **W)
register("deckPresets.assign", spec(decks=req(P.REFERENCES), preset=req(P.REFERENCE),
                                    rescheduleFsrs=opt(B, False)), effect="write", completion="operation",
         undo="perItem")
register("deckPresets.delete", spec(preset=req(P.REFERENCE), replacement=opt(P.REFERENCE)), effect="write",
         completion="operation", undo="grouped")

register("noteTypes.list", spec())
register("noteTypes.get", spec(noteType=req(P.REFERENCE)))
register("noteTypes.create", spec(name=req(P.TEXT), kind=opt(P.enum("normal", "cloze"), "normal"),
                                  fields=req(P.array(P.FIELD_CONFIG, 1)), templates=req(P.array(P.TEMPLATE_CONFIG, 1)),
                                  css=opt(P.string(), ""), sortField=opt(P.TEXT), latexHeader=opt(P.string(), ""),
                                  latexFooter=opt(P.string(), ""), latexSvg=opt(B, False)), **W)
register("noteTypes.update", spec(noteType=req(P.REFERENCE), patch=req(P.NOTE_TYPE_PATCH)), **W)
register("noteTypes.editStructure", spec(noteType=req(P.REFERENCE), edits=req(P.array(P.STRUCTURE_EDIT, 1))), **W)
register("noteTypes.getTemplateUsage", spec(noteType=req(P.REFERENCE)))
register("noteTypes.replaceText", P.obj({
    "find": req(P.TEXT), "replace": req(P.string()), "noteTypes": opt(P.REFERENCES), "allNoteTypes": opt(B, False),
    "targets": opt(P.array(P.enum("question", "answer", "css"), 1), lambda: ["question", "answer", "css"]),
    "session": opt(P.string(1))}, check=lambda v, p: _one_of_selector(v, p, "noteTypes", "allNoteTypes")),
    effect="write", undo="grouped")
register("noteTypes.deleteUnused", spec(noteTypes=req(P.REFERENCES)), effect="write", undo="perItem")

register("media.store", spec(filename=req(P.FILENAME), source=req(P.MEDIA_SOURCE),
                             collision=opt(P.enum("rename", "replace", "error"), "rename"),
                             skipIfHash=opt(P.MEDIA_SKIP)), effect="media", completion="operation")
register("media.get", spec(filename=req(P.FILENAME)))
register("media.list", spec(pattern=opt(P.FILENAME, "*")))
register("media.delete", spec(filename=req(P.FILENAME)), effect="media")
register("media.getDirectory", spec())

register("reviews.list", spec(cardIds=opt(P.IDS), deck=opt(P.REFERENCE), includeChildren=opt(B, False),
                              membership=opt(P.enum("current", "home"), "current"), afterId=opt(P.ID),
                              includeManual=opt(B, True), limit=LIMIT, cursor=CURSOR))
register("reviews.getLatestId", spec(deck=opt(P.REFERENCE), cardIds=opt(P.IDS),
                                     membership=opt(P.enum("current", "home"), "current")))
register("statistics.getToday", spec())
register("statistics.getReviewDays", spec())
register("statistics.getSummary", spec(deck=opt(P.REFERENCE)))
register("statistics.getHtml", spec(deck=opt(P.REFERENCE)))

register("packages.import", spec(path=req(P.TEXT)), effect="write", completion="operation", undo="clears")
register("packages.export", spec(deck=req(P.REFERENCE), path=req(P.TEXT), includeScheduling=opt(B, False)),
         effect="filesystem", completion="operation")

register("browser.open", spec(query=opt(P.string()), sort=SORT), effect="gui", completion="operation")
register("browser.getSelection", spec())
register("browser.select", P.obj({"cardIds": opt(P.IDS), "noteIds": opt(P.IDS), "session": opt(P.string(1))},
                                 check=P.exactly_one("cardIds", "noteIds")), effect="gui", completion="operation")
register("editors.openNote", spec(noteId=req(P.ID)), effect="gui", completion="operation")
register("editors.openAdd", spec(note=opt(P.DRAFT_INPUT)), effect="gui", completion="operation")
register("editors.updateDraft", spec(editorId=req(P.TEXT), patch=req(P.EDITOR_PATCH),
                                     mode=opt(P.enum("replace", "append"), "replace")),
         effect="gui", completion="operation")

TOKEN = req(P.TEXT)
register("reviewer.get", spec())
register("reviewer.startTimer", spec(stateToken=TOKEN), effect="gui")
register("reviewer.showQuestion", spec(stateToken=TOKEN), effect="gui")
register("reviewer.showAnswer", spec(stateToken=TOKEN), effect="gui")
register("reviewer.answer", spec(stateToken=TOKEN, rating=req(P.RATING)), effect="write",
         completion="operation", undo="single")
register("reviewer.playAudio", spec(stateToken=TOKEN), effect="gui")

register("application.navigate", P.obj({
    "view": req(P.enum("deckBrowser", "deckOverview", "review")), "deck": opt(P.REFERENCE),
    "session": opt(P.string(1))}, check=lambda v, p: _navigate_check(v, p)), effect="gui", completion="operation")
register("application.importFile", spec(path=opt(P.TEXT)), effect="write", completion="operation", undo="clears")
register("application.exit", app_spec(), scope="application", effect="lifecycle")

register("advanced.cards.update", spec(cardId=req(P.ID), patch=req(P.RAW_CARD_PATCH)), effect="advancedWrite",
         undo="single")
register("advanced.reviews.import", spec(reviews=req(P.array(P.REVIEW_IMPORT))), effect="advancedWrite",
         completion="operation", undo="clears")
register("operations.get", app_spec(operationId=req(P.TEXT)), scope="application")
register("operations.cancel", app_spec(operationId=req(P.TEXT)), scope="application", effect="lifecycle")


def _tags_replace_check(value: dict, path: str) -> None:
    _one_of_selector(value, path, "noteIds", "allNotes")


def _one_of_selector(value: dict, path: str, ids: str, everything: str) -> None:
    has_ids = ids in value
    has_all = bool(value.get(everything))
    if has_ids == has_all:
        raise P.fail(path, f"requires exactly one of {ids} or {everything}=true")


def _needs_any(value: dict, path: str, *names: str) -> None:
    if not any(name in value for name in names):
        raise P.fail(path, "requires at least one of " + ", ".join(names))


def _navigate_check(value: dict, path: str) -> None:
    if value["view"] == "deckBrowser" and "deck" in value:
        raise P.fail(f"{path}/deck", "is not allowed for deckBrowser")
    if value["view"] != "deckBrowser" and "deck" not in value:
        raise P.fail(f"{path}/deck", "is required")


# -- anki-cli extensions -------------------------------------------------------------------------

X = dict(extension=True)
XW = dict(extension=True, effect="write", undo="single")

register("profiles.create", app_spec(name=req(P.TEXT)), scope="application", effect="lifecycle", **X)
register("profiles.rename", app_spec(name=req(P.TEXT), newName=req(P.TEXT)), scope="application",
         effect="lifecycle", **X)
register("profiles.delete", app_spec(name=req(P.TEXT), confirm=req(P.const(True))), scope="application",
         effect="lifecycle", **X)
register("server.info", app_spec(), scope="application", summary="Version, uptime and open collections.", **X)

register("collection.info", spec(), **X)
register("collection.redo", spec(), effect="write", undo="undo", **X)
register("collection.undoStatus", spec(), **X)
register("collection.backup", spec(), effect="filesystem", **X)
register("collection.backups", spec(), **X)
register("collection.exportPackage", spec(path=req(P.TEXT), includeMedia=opt(B, True), legacy=opt(B, False)),
         effect="filesystem", **X)
register("collection.restore", spec(path=req(P.TEXT), confirm=req(P.const(True))), effect="lifecycle",
         undo="clears", **X)
register("collection.optimize", spec(), effect="write", **X)
register("collection.emptyCards", spec(), **X)
register("collection.deleteEmptyCards", spec(keepNotes=opt(B, True)), **XW)

register("decks.tree", spec(deck=opt(P.REFERENCE)), **X)
register("decks.setCollapsed", spec(deck=req(P.REFERENCE), collapsed=req(B),
                                    scope=opt(P.enum("browser", "reviewer"), "browser")), **XW)
register("decks.setCurrent", spec(deck=req(P.REFERENCE)), **XW)
register("filteredDecks.create", spec(name=req(P.TEXT), search=req(P.string()), limit=opt(P.integer(1), 100),
                                      order=opt(P.integer(0), 0), reschedule=opt(B, True),
                                      secondSearch=opt(P.string()), secondLimit=opt(P.integer(1), 20),
                                      secondOrder=opt(P.integer(0), 0)), **XW)
register("filteredDecks.rebuild", spec(deck=req(P.REFERENCE)), **XW)
register("filteredDecks.empty", spec(deck=req(P.REFERENCE)), **XW)
register("customStudy.defaults", spec(deck=req(P.REFERENCE)), **X)
register("customStudy.create", spec(
    deck=req(P.REFERENCE),
    mode=req(P.enum("newLimitDelta", "reviewLimitDelta", "forgotDays", "reviewAheadDays", "previewDays", "cram")),
    value=opt(P.integer()), cramKind=opt(P.enum("new", "due", "review", "all"), "new"),
    cardLimit=opt(P.integer(1), 100), tagsToInclude=opt(P.TAGS), tagsToExclude=opt(P.TAGS)), **XW)

register("cards.bury", spec(ids=req(P.IDS), manual=opt(B, True)), **XW)
register("cards.unbury", spec(ids=req(P.IDS)), **XW)
register("cards.reposition", spec(ids=req(P.IDS), start=opt(P.integer(0), 0), step=opt(P.integer(1), 1),
                                  randomize=opt(B, False), shiftExisting=opt(B, False)), **XW)
register("cards.info", spec(id=req(P.ID)), **X)
register("cards.answerAudio", spec(id=req(P.ID), side=opt(P.enum("question", "answer"), "question")), **X)

register("noteTypes.delete", spec(noteType=req(P.REFERENCE), confirm=req(P.const(True))), **XW)
register("noteTypes.addStock", spec(kind=req(P.TEXT)), **XW)

register("media.check", spec(), **X)
register("media.trashUnused", spec(), effect="media", **X)
register("media.emptyTrash", spec(), effect="media", **X)
register("media.restoreTrash", spec(), effect="media", **X)

register("statistics.graphs", spec(search=opt(P.string(), ""), days=opt(P.integer(0), 365)), **X)
register("statistics.studiedToday", spec(), **X)

COND = P.enum("ifNewer", "always", "never")
register("packages.importAnki", spec(path=req(P.TEXT), mergeNoteTypes=opt(B, True), withScheduling=opt(B, True),
                                     withDeckConfigs=opt(B, True), updateNotes=opt(COND, "ifNewer"),
                                     updateNoteTypes=opt(COND, "ifNewer")), effect="write", undo="clears", **X)
register("packages.importCsv", spec(path=req(P.TEXT), deck=opt(P.REFERENCE), noteType=opt(P.REFERENCE),
                                    delimiter=opt(P.enum(",", "\t", ";", ":", "|", " ")), isHtml=opt(B),
                                    duplicates=opt(P.enum("update", "preserve", "duplicate"), "update"),
                                    matchScope=opt(P.enum("noteType", "noteTypeAndDeck"), "noteType"),
                                    tags=opt(P.TAGS)), effect="write", undo="clears", **X)
register("packages.exportCsv", spec(path=req(P.TEXT), search=opt(P.string(), ""),
                                    kind=opt(P.enum("notes", "cards"), "notes"), withHtml=opt(B, True),
                                    withTags=opt(B, True), withDeck=opt(B, True), withNoteType=opt(B, True),
                                    withGuid=opt(B, False)), effect="filesystem", **X)

register("config.get", spec(key=req(P.TEXT)), **X)
register("config.set", spec(key=req(P.TEXT), value=req(P.any_())), **XW)
register("config.remove", spec(key=req(P.TEXT)), **XW)
register("preferences.get", spec(), **X)
register("preferences.set", spec(preferences=req(P.mapping(P.any_()))), **XW)

register("fsrs.optimize", spec(preset=req(P.REFERENCE), search=opt(P.string())), **X)
register("fsrs.simulate", spec(preset=req(P.REFERENCE), desiredRetention=opt(P.number(exclusive_min=0, exclusive_max=1)),
                               daysToSimulate=opt(P.integer(1, 36500), 365)), **X)

register("reviewer.start", spec(deck=opt(P.REFERENCE)), effect="gui", **X)
register("reviewer.stop", spec(), effect="gui", **X)
register("reviewer.undo", spec(), effect="write", undo="undo", **X)
register("browser.close", spec(), effect="gui", **X)
register("browser.columns", spec(), **X)
register("browser.rows", spec(ids=req(P.IDS), columns=req(P.array(P.TEXT, 1)),
                              mode=opt(P.enum("cards", "notes"), "cards")), **X)
register("editors.save", spec(editorId=req(P.TEXT)), **XW)
register("editors.close", spec(editorId=req(P.TEXT)), effect="gui", **X)
register("editors.list", spec(), **X)

register("sync.login", spec(username=req(P.TEXT), password=req(P.TEXT), endpoint=opt(P.string(1, r"^https?://"))),
         effect="lifecycle", **X)
register("sync.logout", spec(), effect="lifecycle", **X)
register("sync.account", spec(), **X)
register("sync.setOptions", spec(syncMedia=opt(B), timeoutSeconds=opt(P.integer(5, 3600))), effect="lifecycle", **X)
register("sync.status", spec(), **X)
register("sync.run", spec(mode=opt(P.enum("auto", "upload", "download"), "auto"), includeMedia=opt(B)),
         effect="lifecycle", **X)
register("sync.media", spec(), effect="lifecycle", **X)

#: Methods implemented by the application rather than a collection service.
APPLICATION_METHODS = {name for name, method in METHODS.items() if method.scope == "application"}


SUMMARIES = {
    "access.requestPermission": "Ask for access from a browser origin (the origin comes from the request).",
    "profiles.list": "All profiles.", "profiles.getActive": "The active profile.",
    "profiles.switch": "Make another profile active.", "collection.get": "Profile, session and scheduler of the collection.",
    "collection.refresh": "Clear caches (nothing to redraw without a GUI).",
    "collection.checkIntegrity": "Check and repair the database (Tools › Check Database).",
    "collection.undo": "Undo the last change.", "notes.get": "One note.", "notes.getMany": "Several notes, one item each.",
    "notes.search": "Note IDs for an Anki search, paginated.", "notes.validate": "Check whether a note can be created.",
    "notes.validateMany": "Check several notes.", "notes.create": "Create a note; returns its generated cards.",
    "notes.createMany": "Create notes, independently or atomically.", "notes.update": "Change fields and/or tags.",
    "notes.delete": "Delete notes and their cards.", "notes.planConversion": "Plan a note-type change (field/template mapping).",
    "notes.convert": "Change notes to another note type using a plan.", "notes.findEmpty": "Notes with no cards or only empty content.",
    "tags.list": "All tags.", "tags.add": "Add tags to notes.", "tags.remove": "Remove tags from notes.",
    "tags.replace": "Rename a tag on some or all notes.", "tags.deleteUnused": "Remove tags no note uses.",
    "cards.get": "One card with its scheduling state.", "cards.getMany": "Several cards.",
    "cards.search": "Card IDs for an Anki search, paginated.", "cards.render": "Question and answer HTML plus CSS.",
    "cards.move": "Move cards to a deck.", "cards.setSuspended": "Suspend or unsuspend cards.",
    "cards.setFlags": "Set the flag (0–7) of cards.", "scheduling.get": "Scheduling state of a card.",
    "scheduling.getQueue": "The head of today's study queue and its counts.",
    "scheduling.predict": "Next intervals per rating and a state token for answering.",
    "scheduling.getDue": "Whether a card is due now.", "scheduling.answer": "Answer a card with a prediction's token.",
    "scheduling.answerMany": "Answer several cards.", "scheduling.reset": "Forget cards (make them new).",
    "scheduling.setDueDate": "Set due dates with Anki's day syntax (0, 1!, 3-7).", "decks.list": "All decks.",
    "decks.get": "One deck.", "decks.create": "Create a deck (or return the existing one).", "decks.update": "Rename a deck.",
    "decks.delete": "Delete decks with their cards.", "decks.getCounts": "New/learning/review counts with daily limits.",
    "deckPresets.list": "All deck option presets.", "deckPresets.get": "A preset with every setting.",
    "deckPresets.create": "Create a preset, optionally cloning another.", "deckPresets.update": "Rename or change settings of a preset.",
    "deckPresets.assign": "Use a preset for decks.", "deckPresets.delete": "Delete a preset (with a replacement if in use).",
    "noteTypes.list": "All note types.", "noteTypes.get": "A note type with fields, templates and CSS.",
    "noteTypes.create": "Create a note type.", "noteTypes.update": "Rename, restyle or change the sort field.",
    "noteTypes.editStructure": "Add, rename, move or remove fields and templates.",
    "noteTypes.getTemplateUsage": "Fields used on each template side.", "noteTypes.replaceText": "Find and replace in templates/CSS.",
    "noteTypes.deleteUnused": "Delete note types that have no notes.", "media.store": "Store a media file from data, a path or a URL.",
    "media.get": "A media file as base64.", "media.list": "Media file names matching a pattern.",
    "media.delete": "Move a media file to the trash.", "media.getDirectory": "The media folder path.",
    "reviews.list": "Review history, paginated.", "reviews.getLatestId": "Newest review ID matching a filter.",
    "statistics.getToday": "Reviews today.", "statistics.getReviewDays": "Reviews per day.",
    "statistics.getSummary": "Card, note and review totals.", "statistics.getHtml": "Anki's legacy statistics report.",
    "packages.import": "Import an .apkg/.colpkg.", "packages.export": "Export a deck as .apkg.",
    "browser.open": "Search in the (headless) browser.", "browser.getSelection": "Selected notes and cards.",
    "browser.select": "Select cards or notes in the browser.", "editors.openNote": "Open an editor for a note.",
    "editors.openAdd": "Open an Add draft.", "editors.updateDraft": "Change a draft's fields, tags, deck or type.",
    "reviewer.get": "The reviewer's card, side, answers and state token.", "reviewer.startTimer": "Restart the answer timer.",
    "reviewer.showQuestion": "Show the question side.", "reviewer.showAnswer": "Show the answer side.",
    "reviewer.answer": "Answer the shown card.", "reviewer.playAudio": "No-op headless; play cards.answerAudio yourself.",
    "application.navigate": "Deck browser, deck overview or start reviewing.", "application.importFile": "Import a file by path.",
    "application.exit": "Stop the server (needs --allow-exit).", "advanced.cards.update": "Set validated card metadata.",
    "advanced.reviews.import": "Import historical review rows.", "operations.get": "An operation's state and result.",
    "operations.cancel": "Request cancellation (operations finish before replying).",
    "collection.sync": "A normal sync with the stored login (full syncs: sync.run).",
    "profiles.create": "Create a profile.", "profiles.rename": "Rename a profile.", "profiles.delete": "Delete a profile and its data.",
    "collection.redo": "Redo the last undone change.", "collection.undoStatus": "Labels of the next undo/redo.",
    "collection.backup": "Create a backup now.", "collection.backups": "Backups of this profile.",
    "collection.exportPackage": "Write the whole collection to a .colpkg.",
    "collection.restore": "Replace the collection with a .colpkg (backed up first).",
    "collection.optimize": "Vacuum and analyze the database.", "collection.emptyCards": "Cards whose templates render empty.",
    "collection.deleteEmptyCards": "Delete empty cards.", "collection.info": "Paths and counts.",
    "decks.tree": "Deck tree with due counts in one call.", "decks.setCollapsed": "Collapse/expand a deck.",
    "decks.setCurrent": "Select the current deck.", "filteredDecks.create": "Create a filtered deck from a search.",
    "filteredDecks.rebuild": "Rebuild a filtered deck.", "filteredDecks.empty": "Return a filtered deck's cards home.",
    "customStudy.defaults": "Custom Study options for a deck.", "customStudy.create": "Anki's Custom Study session.",
    "cards.bury": "Bury cards.", "cards.unbury": "Unbury cards.", "cards.reposition": "Reposition new cards.",
    "cards.info": "Anki's card info: history, ease, stability, retrievability.",
    "cards.answerAudio": "Sound and TTS tags of a card side.", "noteTypes.delete": "Delete a note type and its notes.",
    "noteTypes.addStock": "Add one of Anki's built-in note types.", "media.check": "Unused and missing media.",
    "media.trashUnused": "Trash unused media.", "media.emptyTrash": "Empty the media trash.",
    "media.restoreTrash": "Restore trashed media.", "statistics.graphs": "Everything behind Anki's statistics screen.",
    "statistics.studiedToday": "Anki's 'studied today' sentence.", "packages.importAnki": "Import with options; returns the log.",
    "packages.importCsv": "Import CSV/TSV with Anki's importer.", "packages.exportCsv": "Export notes or cards as text.",
    "config.get": "A collection config value.", "config.set": "Set a collection config value.",
    "config.remove": "Remove a config value.", "preferences.get": "Collection preferences.", "preferences.set": "Change preferences.",
    "fsrs.optimize": "Optimal FSRS parameters from review history.", "fsrs.simulate": "FSRS workload simulation.",
    "reviewer.start": "Open a deck in the reviewer.", "reviewer.stop": "Close the reviewer.",
    "reviewer.undo": "Undo the last answer and show that card again.", "browser.close": "Close the browser.",
    "browser.columns": "Browser columns usable for sorting.", "browser.rows": "Rendered browser rows.",
    "editors.save": "Save a draft (adds or updates the note).", "editors.close": "Discard an editor.",
    "editors.list": "Open editors.", "sync.login": "Log in to AnkiWeb or a self-hosted server.",
    "sync.logout": "Forget the sync login.", "sync.account": "Sync login and options.",
    "sync.setOptions": "Media sync on/off, timeout.", "sync.status": "Whether a sync is needed.",
    "sync.run": "Sync; full syncs only with an explicit upload/download.", "sync.media": "Sync media only.",
}
for _name, _summary in SUMMARIES.items():
    if _name in METHODS and not METHODS[_name].summary:
        METHODS[_name] = Method(**{**METHODS[_name].__dict__, "summary": _summary})
