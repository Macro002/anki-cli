"""Dialogs: prompt, confirm, help, profiles, sync."""
from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from ..errors import ApiError


class Dialog(ModalScreen):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def action_cancel(self) -> None:
        self.dismiss(None)


class PromptScreen(Dialog):
    def __init__(self, title: str, placeholder: str, value: str = "", *, password: bool = False):
        super().__init__()
        self.title_text, self.placeholder, self.value, self.password = title, placeholder, value, password

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            yield Input(self.value, placeholder=self.placeholder, password=self.password, id="prompt")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", id="ok", variant="primary")

    def on_mount(self) -> None:
        field = self.query_one(Input)
        field.focus()
        field.cursor_position = len(self.value)

    def on_input_submitted(self) -> None:
        self.dismiss(self.query_one(Input).value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self.query_one(Input).value.strip() if event.button.id == "ok" else None)


class ConfirmScreen(Dialog):
    BINDINGS = [Binding("escape,n", "cancel", show=False), Binding("y", "yes", show=False)]

    def __init__(self, message: str, action: str = "OK", *, danger: bool = False):
        super().__init__()
        self.message, self.action, self.danger = message, action, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, classes="dialog-title")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.action, id="ok", variant="error" if self.danger else "primary")

    def on_mount(self) -> None:
        self.query_one("#cancel" if self.danger else "#ok", Button).focus()

    def action_yes(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")


HELP = [
    ("Decks", [("↑↓ / j k", "move"), ("enter", "study the deck"), ("space", "expand / collapse"),
               ("a", "add a note"), ("b", "browse"), ("t", "statistics"), ("y", "sync"), ("p", "profiles"),
               ("n", "new deck"), ("R", "rename deck"), ("D", "delete deck"), ("q", "quit")]),
    ("Studying", [("space / enter", "show answer, then Good"), ("1 2 3 4", "Again · Hard · Good · Easy"),
                  ("u", "undo"), ("e", "edit the note"), ("f", "cycle flag"), ("s", "suspend"),
                  ("b", "bury"), ("r", "replay audio"), ("esc", "back to decks")]),
    ("Browse", [("/", "search (Anki syntax)"), ("enter", "edit the note"), ("s", "suspend / unsuspend"),
                ("f", "cycle flag"), ("m", "move to deck"), ("D", "delete note"), ("esc", "back")]),
    ("Editing", [("tab / shift+tab", "next / previous field"), ("ctrl+s", "save"), ("esc", "close")]),
]


class HelpScreen(Dialog):
    BINDINGS = [Binding("escape,q,question_mark", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        text = Text()
        for index, (section, keys) in enumerate(HELP):
            if index:
                text.append("\n")
            text.append(f"{section}\n", style="bold #2b8cff")
            for key, what in keys:
                text.append(f"  {key:<16}", style="bold #e6e9f2")
                text.append(f"{what}\n", style="#8a93a6")
        with Vertical(classes="dialog wide"):
            yield Label("Keyboard shortcuts", classes="dialog-title")
            yield Static(text)
            yield Label("ctrl+q quits from anywhere · esc closes", classes="dialog-hint")


class ProfilesScreen(Dialog):
    """Switch, create, rename or delete profiles. Dismisses True when the active one changed."""

    BINDINGS = [Binding("escape", "cancel", show=False), Binding("n", "create", "New"),
                Binding("R", "rename", "Rename"), Binding("D", "delete", "Delete")]

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Profiles", classes="dialog-title")
            yield OptionList(id="profiles")
            yield Label("enter switch · n new · R rename · D delete · esc close", classes="dialog-hint")

    def on_mount(self) -> None:
        self.reload()
        self.query_one(OptionList).focus()

    def reload(self) -> None:
        profiles = self.app.try_api("profiles.list") or []
        active = (self.app.try_api("profiles.getActive") or {}).get("name")
        options = self.query_one(OptionList)
        options.clear_options()
        for profile in profiles:
            name = profile["name"]
            prompt = Text.assemble(("● " if name == active else "  ", "#2b8cff"), name)
            options.add_option(Option(prompt, id=name))
        names = [profile["name"] for profile in profiles]
        if active in names:
            options.highlighted = names.index(active)

    def highlighted(self) -> str | None:
        options = self.query_one(OptionList)
        if options.highlighted is None:
            return None
        return options.get_option_at_index(options.highlighted).id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        active = (self.app.try_api("profiles.getActive") or {}).get("name")
        if event.option.id == active:
            self.dismiss(False)
            return
        try:
            self.app.api("profiles.switch", name=event.option.id)
        except ApiError:
            return
        if getattr(self.app.client, "profile", None):
            self.app.client.profile = event.option.id
        self.app.connect_audio()
        self.app.notify(f"Switched to {event.option.id}", timeout=2)
        self.dismiss(True)

    def action_create(self) -> None:
        def create(name: str | None) -> None:
            if name and self.app.try_api("profiles.create", name=name) is not None:
                self.reload()
        self.app.push_screen(PromptScreen("New profile", "Name"), create)

    def action_rename(self) -> None:
        current = self.highlighted()
        if not current:
            return

        def rename(name: str | None) -> None:
            if name and name != current and self.app.try_api("profiles.rename", name=current,
                                                             newName=name) is not None:
                self.reload()
        self.app.push_screen(PromptScreen("Rename profile", "New name", current), rename)

    def action_delete(self) -> None:
        current = self.highlighted()
        if not current:
            return

        def delete(yes: bool | None) -> None:
            if yes and self.app.try_api("profiles.delete", name=current, confirm=True) is not None:
                self.reload()
        self.app.push_screen(ConfirmScreen(f"Delete the profile “{current}” and its collection?", "Delete",
                                           danger=True), delete)


class SyncScreen(Dialog):
    """Sync with AnkiWeb or a self-hosted server; log in first if needed."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label("Sync", classes="dialog-title")
            yield Static(id="sync-status")
            with Vertical(id="sync-login"):
                yield Input(placeholder="AnkiWeb email or username", id="username")
                yield Input(placeholder="Password", password=True, id="password")
                yield Input(placeholder="Server (optional, for a self-hosted sync server)", id="endpoint")
            with Horizontal(classes="dialog-buttons", id="sync-buttons"):
                yield Button("Close", id="cancel")
                yield Button("Log in", id="login", variant="primary")
                yield Button("Upload", id="upload", variant="warning")
                yield Button("Download", id="download", variant="warning")
                yield Button("Sync now", id="sync", variant="primary")

    def on_mount(self) -> None:
        self.show_account()

    def status(self, message: str, style: str = "#8a93a6") -> None:
        self.query_one("#sync-status", Static).update(Text(message, style=style))

    def buttons(self, *visible: str) -> None:
        for button in self.query("#sync-buttons Button"):
            button.display = button.id in visible or button.id == "cancel"

    def show_account(self) -> None:
        account = self.app.try_api("sync.account") or {"loggedIn": False}
        login = self.query_one("#sync-login")
        if not account["loggedIn"]:
            login.display = True
            self.status("Log in to sync this profile.")
            self.buttons("login")
            self.query_one("#username", Input).focus()
            return
        login.display = False
        where = f" on {account['endpoint']}" if account.get("endpoint") else ""
        last = account.get("lastSync") or "never"
        self.status(f"Logged in as {account['username']}{where}.\nLast sync: {last}")
        self.buttons("sync")
        self.query_one("#sync", Button).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "username":
            self.query_one("#password", Input).focus()
        else:
            self.login()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "login":
            self.login()
        elif event.button.id in ("sync", "upload", "download"):
            self.run_sync({"sync": "auto", "upload": "upload", "download": "download"}[event.button.id])

    def login(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        endpoint = self.query_one("#endpoint", Input).value.strip()
        if not username or not password:
            self.status("Enter your username and password.", "#e6a23c")
            return
        params = {"username": username, "password": password}
        if endpoint:
            params["endpoint"] = endpoint
        self.status("Logging in…")
        self.buttons()
        self.call_login(params)

    @work(thread=True, exclusive=True)
    def call_login(self, params: dict) -> None:
        try:
            self.app.client.call("sync.login", **params)
        except ApiError as error:
            self.app.call_from_thread(self.failed, error)
            return
        self.app.call_from_thread(self.show_account)

    def failed(self, error: ApiError) -> None:
        self.status(str(error), "#e66767")
        self.buttons("login" if self.query_one("#sync-login").display else "sync")

    def run_sync(self, mode: str) -> None:
        self.status({"auto": "Syncing…", "upload": "Uploading the whole collection…",
                     "download": "Downloading the whole collection…"}[mode])
        self.buttons()
        self.call_sync(mode)

    @work(thread=True, exclusive=True)
    def call_sync(self, mode: str) -> None:
        try:
            result = self.app.client.call("sync.run", mode=mode)
        except ApiError as error:
            self.app.call_from_thread(self.failed, error)
            return
        self.app.call_from_thread(self.synced, result)

    def synced(self, result: dict) -> None:
        outcome = result.get("outcome")
        if outcome == "fullSyncRequired":
            self.status("The collections have diverged, so one side has to replace the other.\n"
                        "Upload keeps this collection; Download keeps the server's.", "#e6a23c")
            self.buttons("upload", "download")
            return
        messages = {"noChanges": "Already up to date.", "synced": "Synced.", "uploaded": "Uploaded.",
                    "downloaded": "Downloaded."}
        self.status(messages.get(outcome, f"Done ({outcome})."), "#3fb950")
        self.buttons("sync")
        self.app.notify(messages.get(outcome, "Sync finished"), timeout=2)
