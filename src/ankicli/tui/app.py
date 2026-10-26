"""The anki-cli terminal app."""
from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import Static

from .. import __version__
from ..errors import ApiError
from .audio import Audio
from .render import logo_lines, logo_text, scaled_logo

THEME = Theme(
    name="anki-cli",
    primary="#2b8cff",
    secondary="#0b4ec4",
    accent="#2b8cff",
    warning="#e6a23c",
    error="#e66767",
    success="#3fb950",
    foreground="#e6e9f2",
    background="#0d1117",
    surface="#151b26",
    panel="#1b2433",
    dark=True,
)


class Splash(Screen):
    """The logo, briefly, while the collection opens."""

    BINDINGS = [Binding("escape,enter,space", "skip", show=False)]

    def compose(self) -> ComposeResult:
        lines = logo_lines()
        width = self.app.size.width
        if width < max(len(line) for line in lines) + 4:
            lines = scaled_logo()
        with Middle(), Center():
            yield Static(logo_text(lines), id="splash-logo")
        with Center():
            yield Static(f"[b]anki-cli[/b] [dim]{__version__} · Anki's engine in your terminal[/dim]",
                         id="splash-title")

    def on_mount(self) -> None:
        self.set_timer(1.2, self.action_skip)

    def action_skip(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()


class AnkiTUI(App):
    CSS_PATH = "app.tcss"
    TITLE = "anki-cli"
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=False, priority=True),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, client: Any, *, remote: bool, splash: bool = True):
        super().__init__()
        self.client = client
        self.remote = remote
        self.splash = splash
        self.audio: Audio | None = None
        self.autoplay = True

    # -- API -------------------------------------------------------------------------------------

    def api(self, method: str, **params: Any) -> Any:
        """Call the API; errors are shown as notifications and re-raised as ApiError."""
        try:
            return self.client.call(method, **params)
        except ApiError as error:
            self.notify(str(error), title="anki-cli", severity="error", timeout=6)
            raise

    def try_api(self, method: str, **params: Any) -> Any:
        try:
            return self.api(method, **params)
        except ApiError:
            return None

    # -- lifecycle -------------------------------------------------------------------------------

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = "anki-cli"
        from .decks import DecksScreen
        self.connect_audio()
        self.push_screen(DecksScreen())
        if self.splash:
            self.push_screen(Splash())

    def connect_audio(self) -> None:
        """Play local media straight from the profile's folder; remote media via media.get."""
        if self.audio:
            self.audio.stop()
        media = None if self.remote else (self.try_api("collection.info") or {}).get("mediaDir")
        self.audio = Audio(self.client.call, media)

    def on_unmount(self) -> None:
        if self.audio:
            self.audio.stop()

    def action_help(self) -> None:
        from .modals import HelpScreen
        self.push_screen(HelpScreen())


def run(client: Any, *, remote: bool, splash: bool = True) -> None:
    AnkiTUI(client, remote=remote, splash=splash).run()
