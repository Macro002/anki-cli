"""The browser: Anki search, a card table and a preview of the selected card."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Input, Static

from ..errors import ApiError
from .render import card_text, label

PAGE = 200
COLUMNS = [("noteFld", "Sort field", None), ("deck", "Deck", 22), ("cardDue", "Due", 14), ("noteTags", "Tags", 16)]
ROW_COLORS = {1: "#c9a7ff", 2: "#a39a6b", 3: "#e66767", 4: "#e6a23c", 5: "#3fb950", 6: "#5aa2ff", 7: "#e88ccf",
              8: "#3ec5c5", 9: "#9085e9", 10: "#7d8590"}
ROW_NAMES = {1: "marked", 2: "suspended", 3: "red flag", 4: "orange flag", 5: "green flag", 6: "blue flag",
             7: "pink flag", 8: "turquoise flag", 9: "purple flag", 10: "buried"}


class BrowseScreen(Screen):
    BINDINGS = [
        Binding("slash", "search", "Search"),
        Binding("enter", "edit", "Edit"),
        Binding("s", "suspend", "Suspend"),
        Binding("f", "flag", "Flag"),
        Binding("m", "move", "Move"),
        Binding("D", "delete", "Delete"),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, query: str = ""):
        super().__init__()
        self.query_text = query
        self.cursor: str | None = None
        self.total_loaded = 0
        self.row_colors: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Input(self.query_text, placeholder="Search — Anki syntax, e.g. deck:French is:due tag:verb",
                    id="search", compact=True)
        with Horizontal(id="browser"):
            yield DataTable(id="cards", cursor_type="row", zebra_stripes=True)
            with Vertical(id="preview-pane"):
                with VerticalScroll(id="preview-scroll"):
                    yield Static(id="preview")
                yield Static(id="preview-meta")
        yield Static(id="browse-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#cards", DataTable)
        for key, title, width in COLUMNS:
            table.add_column(title, key=key, width=width)
        self.run_search()
        table.focus()

    def on_screen_resume(self) -> None:
        self.reload_rows()

    # -- searching -------------------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_text = event.value.strip()
        self.run_search()
        self.query_one("#cards", DataTable).focus()

    def action_search(self) -> None:
        self.query_one("#search", Input).focus()

    def run_search(self) -> None:
        table = self.query_one("#cards", DataTable)
        table.clear()
        self.total_loaded = 0
        self.cursor = None
        self.load_page()

    def load_page(self) -> None:
        params = {"query": self.query_text, "limit": PAGE, "sort": {"column": "noteCrt", "direction": "descending"}}
        if self.cursor:
            params["cursor"] = self.cursor
        try:
            found = self.app.api("cards.search", **params)
        except ApiError:
            self.status("Search failed — check the syntax.", "#e66767")
            return
        self.cursor = found["nextCursor"]
        self.add_rows(found["ids"])
        self.total_loaded += len(found["ids"])
        more = " · scroll for more" if self.cursor else ""
        self.status(f"{self.total_loaded} card{'s' if self.total_loaded != 1 else ''}{more}")
        self.show_preview()

    def add_rows(self, ids: list[str]) -> None:
        if not ids:
            return
        rows = self.app.try_api("browser.rows", ids=ids, columns=[key for key, _, _ in COLUMNS]) or []
        table = self.query_one("#cards", DataTable)
        for row in rows:
            table.add_row(*self.cells(row), key=row["id"])

    def cells(self, row: dict) -> list[Text]:
        self.row_colors[row["id"]] = row["color"]
        style = ROW_COLORS.get(row["color"], "")
        cells = [Text(label(cell).replace("\n", " "), style=style, no_wrap=True, overflow="ellipsis")
                 for cell in row["cells"]]
        parts = cells[1].plain.strip().split("::")
        deck = " › ".join(parts[-2:])
        cells[1] = Text(("… › " if len(parts) > 2 else "") + deck, style=style or "#8a93a6", no_wrap=True,
                        overflow="ellipsis")
        return cells

    def reload_rows(self, ids: list[str] | None = None) -> None:
        """Refresh rows in place after a change."""
        table = self.query_one("#cards", DataTable)
        if ids is None:
            ids = [key.value for key in table.rows]
        rows = self.app.try_api("browser.rows", ids=ids, columns=[key for key, _, _ in COLUMNS]) or []
        found = {row["id"] for row in rows}
        for row in rows:
            for (key, _, _), cell in zip(COLUMNS, self.cells(row)):
                table.update_cell(row["id"], key, cell)
        for card_id in ids:
            if card_id not in found and card_id in table.rows:
                table.remove_row(card_id)
        self.show_preview()

    def status(self, message: str, style: str = "#8a93a6") -> None:
        self.query_one("#browse-status", Static).update(Text(" " + message, style=style))

    # -- selection -------------------------------------------------------------------------------

    def selected_id(self) -> str | None:
        table = self.query_one("#cards", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = self.query_one("#cards", DataTable)
        if self.cursor and event.cursor_row >= table.row_count - 5:
            self.load_page()
        self.show_preview()

    def on_data_table_row_selected(self, _event) -> None:
        self.action_edit()

    def show_preview(self) -> None:
        card_id = self.selected_id()
        preview = self.query_one("#preview", Static)
        meta = self.query_one("#preview-meta", Static)
        if card_id is None:
            preview.update(Text("No cards match this search.", style="#8a93a6"))
            meta.update("")
            return
        rendered = self.app.try_api("cards.render", id=card_id)
        card = self.app.try_api("cards.get", id=card_id)
        if rendered is None or card is None:
            return
        preview.update(card_text(rendered["answerHtml"]))
        sched = card["scheduling"]
        info = Text()
        info.append(f"{card['deck']['name'].replace('::', ' › ')}\n", style="#8a93a6")
        info.append(f"{sched['type']} ", style="bold #e6e9f2")
        if sched["intervalDays"]:
            info.append(f"· interval {sched['intervalDays']}d ", style="#8a93a6")
        info.append(f"· {sched['repetitions']} reviews · {sched['lapses']} lapses", style="#8a93a6")
        color = self.row_colors.get(card_id, 0)
        if color in ROW_NAMES:
            info.append(f" · {ROW_NAMES[color]}", style=ROW_COLORS[color])
        meta.update(info)

    # -- actions ---------------------------------------------------------------------------------

    def card(self) -> dict | None:
        card_id = self.selected_id()
        return self.app.try_api("cards.get", id=card_id) if card_id else None

    def action_edit(self) -> None:
        card = self.card()
        if card:
            from .editor import EditScreen
            self.app.push_screen(EditScreen(card["noteId"]))

    def action_suspend(self) -> None:
        card = self.card()
        if card:
            suspended = card["scheduling"]["queue"] == "suspended"
            self.app.try_api("cards.setSuspended", ids=[card["id"]], suspended=not suspended)
            self.reload_rows([card["id"]])

    def action_flag(self) -> None:
        card = self.card()
        if card:
            self.app.try_api("cards.setFlags", ids=[card["id"]], flag=(card["flags"] + 1) % 5)
            self.reload_rows([card["id"]])

    def action_move(self) -> None:
        card = self.card()
        if not card:
            return
        from .modals import PromptScreen

        def move(name: str | None) -> None:
            if name and name != card["deck"]["name"]:
                try:
                    self.app.client.call("decks.get", deck={"name": name})
                except ApiError:
                    if self.app.try_api("decks.create", name=name) is None:
                        return
                self.app.try_api("cards.move", ids=[card["id"]], deck={"name": name})
                self.reload_rows([card["id"]])
        self.app.push_screen(PromptScreen("Move card to deck", "Deck name (created if missing)",
                                          card["deck"]["name"]), move)

    def action_delete(self) -> None:
        card = self.card()
        if not card:
            return
        from .modals import ConfirmScreen

        def delete(yes: bool | None) -> None:
            if yes and self.app.try_api("notes.delete", ids=[card["noteId"]]) is not None:
                self.reload_rows()
                self.app.notify("Note deleted", timeout=2)
        self.app.push_screen(ConfirmScreen("Delete this note and all of its cards?", "Delete", danger=True), delete)

    def action_back(self) -> None:
        if self.focused is self.query_one("#search", Input):
            self.query_one("#cards", DataTable).focus()
            return
        self.app.pop_screen()
