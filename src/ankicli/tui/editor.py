"""Add and edit notes: one form built from the note type's fields."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Label, Select, Static, TextArea

from ..errors import ApiError


class FieldArea(TextArea):
    """A field: grows with its text, tab moves on."""

    def __init__(self, name: str, text: str = ""):
        super().__init__(text, soft_wrap=True, tab_behavior="focus", show_line_numbers=False,
                         highlight_cursor_line=False, compact=True, classes="field")
        self.field_name = name


class NoteForm(Screen):
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("escape", "close", "Close"),
    ]
    heading = ""
    save_label = "Save"

    def __init__(self) -> None:
        super().__init__()
        self.note_type: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="form-bar")
        with VerticalScroll(id="form"):
            with Horizontal(id="form-pickers"):
                yield Select([], prompt="Note type", id="note-type", compact=True)
                yield Select([], prompt="Deck", id="deck", compact=True)
            yield VerticalScroll(id="fields")
            yield Label("Tags", classes="field-label")
            yield Input(placeholder="space-separated", id="tags", compact=True)
            yield Static(id="form-status")
        yield Footer()

    def bar(self, title: str) -> None:
        self.query_one("#form-bar", Static).update(Text.assemble((" ‹ esc  ", "#8a93a6"), (title, "bold"),
                                                                 ("   ctrl+s ", "#4b5565"),
                                                                 (self.save_label.lower(), "#8a93a6")))

    def status(self, message: str, style: str = "#8a93a6") -> None:
        self.query_one("#form-status", Static).update(Text(message, style=style))

    async def build_fields(self, values: dict[str, str]) -> None:
        container = self.query_one("#fields")
        await container.remove_children()
        widgets = []
        for field in self.note_type["fields"]:
            widgets.append(Label(field["name"], classes="field-label"))
            widgets.append(FieldArea(field["name"], values.get(field["name"], "")))
        await container.mount_all(widgets)
        areas = list(self.query(FieldArea))
        if areas:
            areas[0].focus()

    def values(self) -> dict[str, str]:
        return {area.field_name: area.text for area in self.query(FieldArea)}

    def tags(self) -> list[str]:
        return self.query_one("#tags", Input).value.split()

    def action_close(self) -> None:
        self.app.pop_screen()


class AddScreen(NoteForm):
    save_label = "Add"

    def __init__(self, deck: str | None = None):
        super().__init__()
        self.initial_deck = deck
        self.added = 0
        self.ready = False

    async def on_mount(self) -> None:
        self.bar("Add note")
        types = self.app.try_api("noteTypes.list") or []
        decks = [deck for deck in self.app.try_api("decks.list") or [] if deck.get("kind") != "filtered"]
        current = self.app.try_api("config.get", key="curModel") if types else None
        type_select = self.query_one("#note-type", Select)
        type_select.set_options([(item["name"], item["name"]) for item in types])
        names = [item["name"] for item in types]
        chosen = next((item["name"] for item in types if str(item["id"]) == str(current)), None)
        if names:
            type_select.value = chosen or ("Basic" if "Basic" in names else names[0])
        deck_select = self.query_one("#deck", Select)
        deck_select.set_options([(deck["name"], deck["name"]) for deck in sorted(decks, key=lambda d: d["name"])])
        deck_names = [deck["name"] for deck in decks]
        if deck_names:
            deck_select.value = self.initial_deck if self.initial_deck in deck_names else deck_names[0]
        await self.load_type()
        self.ready = True

    async def load_type(self, keep: dict[str, str] | None = None) -> None:
        name = self.query_one("#note-type", Select).value
        if not isinstance(name, str):
            return
        try:
            self.note_type = self.app.api("noteTypes.get", noteType={"name": name})
        except ApiError:
            return
        await self.build_fields(keep or {})
        self.status("")

    async def on_select_changed(self, event: Select.Changed) -> None:
        if self.ready and event.select.id == "note-type":
            await self.load_type(self.values())

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        areas = list(self.query(FieldArea))
        if self.ready and areas and event.text_area is areas[0]:
            self.check_duplicate()

    def note(self) -> dict:
        return {"noteType": {"name": self.query_one("#note-type", Select).value},
                "deck": {"name": self.query_one("#deck", Select).value},
                "fields": self.values(), "tags": self.tags()}

    def check_duplicate(self) -> None:
        if not self.values().get(self.note_type["fields"][0]["name"], "").strip():
            self.status("")
            return
        try:
            result = self.app.client.call("notes.validate", note=self.note())
        except ApiError:
            result = None
        if result and any(issue["type"] == "duplicate" for issue in result["issues"]):
            self.status("⚠ A note with this first field already exists.", "#e6a23c")
        else:
            self.status("")

    async def action_save(self) -> None:
        if self.note_type is None:
            return
        note = self.note()
        if not isinstance(note["deck"]["name"], str):
            self.status("Pick a deck first.", "#e6a23c")
            return
        try:
            self.app.api("notes.create", **note, duplicates={"allow": True})
        except ApiError as error:
            self.status(str(error), "#e66767")
            return
        self.added += 1
        sticky = {field["name"]: self.values()[field["name"]] for field in self.note_type["fields"] if field["sticky"]}
        await self.build_fields(sticky)
        self.status(f"✓ Added. {self.added} note{'s' if self.added != 1 else ''} this time.", "#3fb950")


class EditScreen(NoteForm):
    def __init__(self, note_id: str):
        super().__init__()
        self.note_id = note_id
        self.note: dict | None = None

    async def on_mount(self) -> None:
        self.bar("Edit note")
        try:
            self.note = self.app.api("notes.get", id=self.note_id)
            self.note_type = self.app.api("noteTypes.get", noteType={"id": self.note["noteType"]["id"]})
        except ApiError:
            self.app.pop_screen()
            return
        type_select = self.query_one("#note-type", Select)
        type_select.set_options([(self.note_type["name"], self.note_type["name"])])
        type_select.disabled = True
        cards = self.app.try_api("cards.getMany", ids=self.note["cardIds"]) or {"items": []}
        decks = sorted({item["result"]["deck"]["name"] for item in cards["items"] if item.get("result")})
        deck_select = self.query_one("#deck", Select)
        deck_select.set_options([(", ".join(decks) or "—", "current")])
        deck_select.disabled = True
        self.query_one("#tags", Input).value = " ".join(self.note["tags"])
        await self.build_fields(self.note["fields"])

    async def action_save(self) -> None:
        if self.note is None:
            return
        patch = {"fields": self.values(), "tags": self.tags()}
        try:
            self.app.api("notes.update", id=self.note_id, patch=patch)
        except ApiError as error:
            self.status(str(error), "#e66767")
            return
        self.app.notify("Note saved", timeout=2)
        self.app.pop_screen()
