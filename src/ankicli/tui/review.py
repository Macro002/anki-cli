"""The reviewer: Anki's scheduler, in the terminal."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from ..errors import ApiError
from .decks import DUE, LEARN, NEW
from .render import card_text, label

RATINGS = [("again", "Again", "#e66767"), ("hard", "Hard", "#9085e9"), ("good", "Good", "#3fb950"),
           ("easy", "Easy", "#5aa2ff")]
FLAGS = {0: ("", ""), 1: ("● red", "#e66767"), 2: ("● orange", "#e6a23c"), 3: ("● green", "#3fb950"),
         4: ("● blue", "#5aa2ff"), 5: ("● pink", "#e88ccf"), 6: ("● turquoise", "#3ec5c5"),
         7: ("● purple", "#9085e9")}


class ReviewScreen(Screen):
    BINDINGS = [
        Binding("space", "primary", "Show / Good", priority=True),
        Binding("enter", "primary", show=False, priority=True),
        Binding("1", "rate(1)", "Again", show=False),
        Binding("2", "rate(2)", "Hard", show=False),
        Binding("3", "rate(3)", "Good", show=False),
        Binding("4", "rate(4)", "Easy", show=False),
        Binding("u", "undo", "Undo"),
        Binding("e", "edit", "Edit"),
        Binding("f", "flag", "Flag"),
        Binding("s", "suspend", "Suspend"),
        Binding("b", "bury", "Bury"),
        Binding("r", "replay", "Replay"),
        Binding("escape,q", "back", "Decks"),
    ]

    def __init__(self, deck_id: str, deck_name: str):
        super().__init__()
        self.deck_id = deck_id
        self.deck_name = deck_name
        self.state: dict | None = None
        self.reviewed = 0
        self.played_for: tuple | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="review-bar")
        with VerticalScroll(id="card-scroll"):
            yield Static(id="card")
        yield Static(id="card-meta")
        with Center(id="answer-bar"):
            yield Button("Show answer   ␣", id="show", variant="primary")
            with Horizontal(id="ratings"):
                for index, (rating, name, _) in enumerate(RATINGS, 1):
                    yield Button(name, id=f"rate-{index}", classes=f"rating rating-{rating}")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.state = self.app.api("reviewer.start", deck={"id": self.deck_id})
        except ApiError:
            self.app.pop_screen()
            return
        self.render_state()

    def on_screen_resume(self) -> None:
        if self.state is not None:
            self.reload()

    def on_unmount(self) -> None:
        if self.app.audio:
            self.app.audio.stop()
        self.app.try_api("reviewer.stop")

    # -- rendering -------------------------------------------------------------------------------

    def reload(self) -> None:
        state = self.app.try_api("reviewer.get")
        if state is not None:
            self.state = state
            self.render_state()

    def render_state(self) -> None:
        state = self.state or {"active": False}
        queue = self.app.try_api("scheduling.getQueue") or {"newCount": 0, "learningCount": 0, "reviewCount": 0}
        bar = Text.assemble((" ‹ esc  ", "#8a93a6"), (self.deck_name.replace("::", " › "), "bold"))
        card_id = state["card"]["id"] if state["active"] else None
        current = next((item["queue"] for item in queue.get("cards", []) if item["cardId"] == card_id), None)
        current = {"learning": "learn"}.get(current, current)

        def part(count: int, color: str, queue_name: str) -> tuple[str, str]:
            return str(count), f"bold {color}" + (" underline" if queue_name == current else "")
        counts = Text.assemble(part(queue["newCount"], NEW, "new"), "  ",
                               part(queue["learningCount"], LEARN, "learn"), "  ",
                               part(queue["reviewCount"], DUE, "review"), " ")
        width = max(1, self.size.width - bar.cell_len - counts.cell_len)
        self.query_one("#review-bar", Static).update(Text.assemble(bar, " " * width, counts))
        card = self.query_one("#card", Static)
        meta = self.query_one("#card-meta", Static)
        show, ratings = self.query_one("#show", Button), self.query_one("#ratings")
        if not state["active"]:
            card.update(Text.assemble(("\n🎉  Congratulations!\n\n", "bold #3fb950"),
                                      ("You have finished this deck for now.\n", "#e6e9f2"),
                                      (f"Reviewed {self.reviewed} card{'s' if self.reviewed != 1 else ''} "
                                       "in this session.\n\n", "#8a93a6"),
                                      ("esc  back to decks", "#2b8cff")))
            meta.update("")
            show.display = False
            ratings.display = False
            return
        revealed = state["side"] == "answer"
        html = state["rendered"]["answerHtml" if revealed else "questionHtml"]
        body = card_text(html)
        card.update(body if body.plain.strip() else Text("(empty card)", style="#8a93a6"))
        self.query_one("#card-scroll").scroll_home(animate=False)
        record = state["card"]
        flag, color = FLAGS.get(record["flags"], ("", ""))
        meta.update(Text.assemble((record["deck"]["name"].replace("::", " › "), "#4b5565"),
                                  ("   " + flag, color) if flag else ""))
        show.display = not revealed
        ratings.display = revealed
        if revealed:
            for index, answer in enumerate(state["answers"], 1):
                name = RATINGS[index - 1][1]
                self.query_one(f"#rate-{index}", Button).label = f"{name}  {label(answer['label'])}"
            self.query_one("#rate-3", Button).focus()
        else:
            show.focus()
        self.autoplay(record["id"], state["side"])

    def autoplay(self, card_id: str, side: str) -> None:
        if not (self.app.autoplay and self.app.audio and self.app.audio.available):
            return
        if self.played_for == (card_id, side):
            return
        self.played_for = (card_id, side)
        self.play(card_id, side)

    def play(self, card_id: str, side: str) -> None:
        tags = self.app.try_api("cards.answerAudio", id=card_id, side=side) or []
        self.app.audio.play([tag["filename"] for tag in tags if tag["kind"] == "sound"])

    # -- actions ---------------------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "show":
            self.action_primary()
        elif event.button.id and event.button.id.startswith("rate-"):
            self.action_rate(int(event.button.id[-1]))

    def active(self) -> bool:
        return bool(self.state and self.state["active"])

    def action_primary(self) -> None:
        if not self.active():
            return
        if self.state["side"] == "answer":
            self.action_rate(3)
            return
        try:
            self.app.api("reviewer.showAnswer", stateToken=self.state["stateToken"])
        except ApiError:
            self.reload()
            return
        self.reload()

    def action_rate(self, ease: int) -> None:
        if not self.active() or self.state["side"] != "answer":
            return
        try:
            self.app.api("reviewer.answer", stateToken=self.state["stateToken"], rating=RATINGS[ease - 1][0])
        except ApiError:
            self.reload()
            return
        self.reviewed += 1
        self.reload()

    def action_undo(self) -> None:
        try:
            result = self.app.api("reviewer.undo")
        except ApiError:
            return
        self.reviewed = max(0, self.reviewed - 1)
        self.app.notify(f"Undid: {result['label']}", timeout=2)
        self.played_for = None
        self.reload()

    def action_edit(self) -> None:
        if not self.active():
            return
        from .editor import EditScreen
        self.app.push_screen(EditScreen(self.state["card"]["noteId"]))

    def action_flag(self) -> None:
        if not self.active():
            return
        flag = (self.state["card"]["flags"] + 1) % 5
        self.app.try_api("cards.setFlags", ids=[self.state["card"]["id"]], flag=flag)
        self.reload()

    def action_suspend(self) -> None:
        if not self.active():
            return
        self.app.try_api("cards.setSuspended", ids=[self.state["card"]["id"]], suspended=True)
        self.app.notify("Card suspended", timeout=2)
        self.reload()

    def action_bury(self) -> None:
        if not self.active():
            return
        self.app.try_api("cards.bury", ids=[self.state["card"]["id"]])
        self.app.notify("Card buried until tomorrow", timeout=2)
        self.reload()

    def action_replay(self) -> None:
        if not self.active():
            return
        if not (self.app.audio and self.app.audio.available):
            self.app.notify("No audio player found (install mpv or ffmpeg)", severity="warning", timeout=3)
            return
        self.play(self.state["card"]["id"], self.state["side"])

    def action_back(self) -> None:
        self.app.pop_screen()
