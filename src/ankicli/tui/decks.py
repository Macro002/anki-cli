"""Home: the deck tree with Anki's due counts."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Static

from ..errors import ApiError
from .render import logo_text, scaled_logo

NEW, LEARN, DUE = "#5aa2ff", "#ff7b72", "#3fb950"


def count(value: int, color: str) -> Text:
    return Text(str(value), style=color if value else "#4b5565", justify="right")


class TopBar(Static):
    def update_bar(self, profile: str, mode: str, today: int | None) -> None:
        left = Text.assemble((" ▶_ ", "bold #2b8cff"), ("anki-cli", "bold"), ("  ·  ", "#4b5565"),
                             (profile, "bold #e6e9f2"), ("  ·  ", "#4b5565"), (mode, "#8a93a6"))
        right = Text(f"studied today: {today}" if today is not None else "", style="#8a93a6")
        width = max(0, self.size.width - left.cell_len - right.cell_len - 1)
        self.update(Text.assemble(left, " " * width, right))


class DecksScreen(Screen):
    BINDINGS = [
        Binding("enter", "study", "Study"),
        Binding("space", "toggle", "Expand"),
        Binding("a", "add", "Add"),
        Binding("b", "browse", "Browse"),
        Binding("t", "stats", "Stats"),
        Binding("y", "sync", "Sync"),
        Binding("p", "profiles", "Profiles"),
        Binding("n", "new_deck", "New deck"),
        Binding("R", "rename", "Rename", show=False),
        Binding("D", "delete", "Delete", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.nodes: dict[str, dict] = {}
        self.collapsed: set[str] = set()

    def compose(self) -> ComposeResult:
        yield TopBar(id="topbar")
        with Horizontal(id="home"):
            with Vertical(id="deck-column"):
                yield Static(" Decks", classes="section-title")
                yield DataTable(id="decks", cursor_type="row", zebra_stripes=False)
            with Vertical(id="side"):
                yield Static(logo_text(scaled_logo(3, 3)), id="side-logo")
                yield Static(id="deck-info")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#decks", DataTable)
        table.add_column("Deck", key="deck")
        table.add_column(Text("New", justify="right"), key="new", width=6)
        table.add_column(Text("Learn", justify="right"), key="learn", width=6)
        table.add_column(Text("Due", justify="right"), key="due", width=6)
        self.refresh_decks()
        table.focus()

    def on_screen_resume(self) -> None:
        self.refresh_decks()

    def on_resize(self) -> None:
        self.query_one("#side-logo").display = self.size.width >= 100 and self.size.height >= 34
        self.query_one("#side").display = self.size.width >= 80
        self.update_topbar()

    # -- data ------------------------------------------------------------------------------------

    def update_topbar(self) -> None:
        profile = (self.app.try_api("profiles.getActive") or {}).get("name", "")
        mode = "remote" if self.app.remote else "local"
        today = (self.app.try_api("statistics.getToday") or {}).get("count")
        self.query_one(TopBar).update_bar(profile, mode, today)

    def refresh_decks(self) -> None:
        tree = self.app.try_api("decks.tree")
        if tree is None:
            return
        table = self.query_one("#decks", DataTable)
        selected = self.selected_id()
        self.nodes = {}
        table.clear()

        def add(nodes: list, depth: int) -> None:
            for node in nodes:
                self.nodes[node["id"]] = node
                if node["children"]:
                    marker = "▸ " if node["id"] in self.collapsed else "▾ "
                else:
                    marker = "  "
                name = Text("  " * depth + marker, style="#4b5565") + Text(node["shortName"], style="#e6e9f2")
                if node["filtered"]:
                    name.stylize("italic #9cc8ff", len("  " * depth + marker))
                table.add_row(name, count(node["new"], NEW), count(node["learning"], LEARN),
                              count(node["review"], DUE), key=node["id"])
                if node["children"] and node["id"] not in self.collapsed:
                    add(node["children"], depth + 1)
        add(tree["children"], 0)
        if selected in self.nodes:
            table.move_cursor(row=table.get_row_index(selected))
        self.update_topbar()
        self.show_info()

    def selected_id(self) -> str | None:
        table = self.query_one("#decks", DataTable)
        if not table.row_count:
            return None
        try:
            return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:  # noqa: BLE001
            return None

    def selected(self) -> dict | None:
        deck_id = self.selected_id()
        return self.nodes.get(deck_id) if deck_id else None

    def on_data_table_row_highlighted(self, _event) -> None:
        self.show_info()

    def on_data_table_row_selected(self, _event) -> None:
        self.action_study()

    def show_info(self) -> None:
        node = self.selected()
        info = self.query_one("#deck-info", Static)
        if node is None:
            info.update(Text("No decks yet — press n to create one, or a to add a note.", style="#8a93a6"))
            return
        due = node["new"] + node["learning"] + node["review"]
        text = Text.assemble(
            (node["name"].replace("::", " › "), "bold #e6e9f2"), "\n\n",
            ("  new  ", "#8a93a6"), (f"{node['new']:>5}\n", f"bold {NEW}"),
            ("  learn", "#8a93a6"), (f"{node['learning']:>5}\n", f"bold {LEARN}"),
            ("  due  ", "#8a93a6"), (f"{node['review']:>5}\n", f"bold {DUE}"), "\n",
            (f"  {node['total']} card{'s' if node['total'] != 1 else ''} in total\n\n", "#8a93a6"),
            ("  ⏎ study now" if due else "  Nothing due — well done!", "bold #2b8cff" if due else "#3fb950"),
        )
        info.update(text)

    # -- actions ---------------------------------------------------------------------------------

    def action_study(self) -> None:
        node = self.selected()
        if node is None:
            return
        from .review import ReviewScreen
        self.app.push_screen(ReviewScreen(node["id"], node["name"]))

    def action_toggle(self) -> None:
        node = self.selected()
        if node is None or not node["children"]:
            return
        if node["id"] in self.collapsed:
            self.collapsed.discard(node["id"])
        else:
            self.collapsed.add(node["id"])
        self.refresh_decks()

    def action_refresh(self) -> None:
        self.refresh_decks()

    def action_add(self) -> None:
        from .editor import AddScreen
        node = self.selected()
        self.app.push_screen(AddScreen(deck=node["name"] if node else None))

    def action_browse(self) -> None:
        from .browse import BrowseScreen
        node = self.selected()
        self.app.push_screen(BrowseScreen(query=f'"deck:{node["name"]}"' if node else ""))

    def action_stats(self) -> None:
        from .stats import StatsScreen
        node = self.selected()
        self.app.push_screen(StatsScreen(deck=node["name"] if node else None))

    def action_sync(self) -> None:
        from .modals import SyncScreen
        self.app.push_screen(SyncScreen(), lambda _: self.refresh_decks())

    def action_profiles(self) -> None:
        from .modals import ProfilesScreen

        def switched(changed: bool | None) -> None:
            if changed:
                self.nodes = {}
                self.refresh_decks()
        self.app.push_screen(ProfilesScreen(), switched)

    def action_new_deck(self) -> None:
        from .modals import PromptScreen
        node = self.selected()
        prefix = f"{node['name']}::" if node else ""

        def create(name: str | None) -> None:
            if name:
                try:
                    created = self.app.api("decks.create", name=name)
                except ApiError:
                    return
                self.refresh_decks()
                table = self.query_one("#decks", DataTable)
                if created["id"] in self.nodes:
                    table.move_cursor(row=table.get_row_index(created["id"]))
        self.app.push_screen(PromptScreen("New deck", "Name (use :: for subdecks)", prefix), create)

    def action_rename(self) -> None:
        from .modals import PromptScreen
        node = self.selected()
        if node is None:
            return

        def rename(name: str | None) -> None:
            if name and name != node["name"]:
                self.app.try_api("decks.update", deck={"id": node["id"]}, name=name)
                self.refresh_decks()
        self.app.push_screen(PromptScreen("Rename deck", "New name", node["name"]), rename)

    def action_delete(self) -> None:
        from .modals import ConfirmScreen
        node = self.selected()
        if node is None:
            return

        def delete(yes: bool | None) -> None:
            if yes:
                self.app.try_api("decks.delete", decks=[{"id": node["id"]}], deleteCards=True)
                self.refresh_decks()
        self.app.push_screen(ConfirmScreen(f"Delete “{node['name']}” and its {node['total']} card(s)?",
                                           "Delete", danger=True), delete)
