"""The terminal app, driven headlessly against a real collection."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, Static  # noqa: E402

from ankicli.client import LocalClient  # noqa: E402
from ankicli.tui.app import AnkiTUI  # noqa: E402
from ankicli.tui.render import card_text, logo_lines, scaled_logo  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    client = LocalClient(base=str(tmp_path / "base"))
    client.call("decks.create", name="French::Animals")
    for front, back in [("le chat", "the cat"), ("le chien", "the dog")]:
        client.call("notes.create", noteType={"name": "Basic"}, deck={"name": "French::Animals"},
                    fields={"Front": front, "Back": back}, tags=["animals"])
    yield client
    client.close()


def run(client, scenario, size=(120, 40)):
    async def main():
        app = AnkiTUI(client, remote=False, splash=False)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
    asyncio.run(main())


def deck_rows(app) -> list[str]:
    table = app.screen.query_one("#decks", DataTable)
    return [table.get_row_at(index)[0].plain.strip(" ▸▾") for index in range(table.row_count)]


def select_deck(app, name: str) -> None:
    table = app.screen.query_one("#decks", DataTable)
    table.move_cursor(row=deck_rows(app).index(name))


def test_render_helpers():
    assert max(len(line) for line in logo_lines()) > 100
    assert max(len(line) for line in scaled_logo(3, 3)) < 45
    text = card_text('<style>.card{}</style><b>le chat</b><hr id=answer><ruby>猫<rt>ねこ</rt></ruby>'
                     '[sound:cat.mp3] <img src="cat.png"><script>alert(1)</script>')
    assert "le chat" in text.plain and "猫(ねこ)" in text.plain
    assert "cat.mp3" in text.plain and "[image: cat.png]" in text.plain
    assert ".card" not in text.plain and "alert" not in text.plain


def test_decks_and_collapse(client):
    async def scenario(app, pilot):
        assert deck_rows(app) == ["French", "Animals"]  # Anki hides an empty Default deck
        select_deck(app, "French")
        await pilot.press("space")
        assert deck_rows(app) == ["French"]
        await pilot.press("space")
        assert "Animals" in deck_rows(app)
    run(client, scenario)


def test_study_answers_with_the_scheduler(client):
    async def scenario(app, pilot):
        select_deck(app, "Animals")
        await pilot.press("enter")
        await pilot.pause()
        assert type(app.screen).__name__ == "ReviewScreen"
        assert "le chat" in app.screen.query_one("#card", Static).render().plain
        await pilot.press("space")
        assert app.screen.state["side"] == "answer"
        assert app.screen.query_one("#rate-3").label.plain.startswith("Good")
        await pilot.press("3")                      # Good
        await pilot.press("space", "1")             # second card: show, Again
        await pilot.pause()
        assert app.screen.reviewed == 2
        await pilot.press("u")                      # undo the Again
        await pilot.pause()
        assert app.screen.reviewed == 1 and app.screen.state["side"] == "question"
        await pilot.press("escape")
    run(client, scenario)
    assert client.call("statistics.getToday")["count"] == 1


def test_add_note(client):
    async def scenario(app, pilot):
        select_deck(app, "Animals")
        await pilot.press("a")
        await pilot.pause()
        await pilot.press(*"le cheval")
        await pilot.press("tab", *"the horse")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.screen.added == 1
        assert "Added" in app.screen.query_one("#form-status", Static).render().plain
        await pilot.press(*"le chat")             # a duplicate first field warns
        await pilot.pause()
        assert "already exists" in app.screen.query_one("#form-status", Static).render().plain
    run(client, scenario)
    found = client.call("notes.search", query='"deck:French::Animals" front:"le cheval"')["ids"]
    assert len(found) == 1
    assert client.call("notes.get", id=found[0])["fields"]["Back"] == "the horse"


def test_browse_search_edit_and_suspend(client):
    async def scenario(app, pilot):
        await pilot.press("b")
        await pilot.pause()
        search = app.screen.query_one("#search", Input)
        search.value = "chien"
        await pilot.press("slash", "enter")
        await pilot.pause()
        table = app.screen.query_one("#cards", DataTable)
        assert table.row_count == 1
        assert "the dog" in app.screen.query_one("#preview", Static).render().plain
        await pilot.press("s")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert type(app.screen).__name__ == "EditScreen"
        areas = list(app.screen.query("FieldArea"))
        areas[1].text = "the dog (m.)"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert type(app.screen).__name__ == "BrowseScreen"
    run(client, scenario)
    note_id = client.call("notes.search", query="chien")["ids"][0]
    assert client.call("notes.get", id=note_id)["fields"]["Back"] == "the dog (m.)"
    card_id = client.call("cards.search", query="chien")["ids"][0]
    assert client.call("cards.get", id=card_id)["scheduling"]["queue"] == "suspended"


def test_new_deck_stats_help_and_profiles(client):
    async def scenario(app, pilot):
        select_deck(app, "Animals")
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.query_one(Input).value == "French::Animals::"
        app.screen.query_one(Input).value = "Spanish"
        await pilot.press("enter")
        await pilot.pause()
        assert "Spanish" in deck_rows(app)
        await pilot.press("t")
        await pilot.pause()
        assert "Forecast" in app.screen.query_one("#stats-forecast", Static).render().plain
        await pilot.press("escape", "question_mark")
        await pilot.pause()
        assert type(app.screen).__name__ == "HelpScreen"
        await pilot.press("escape", "p")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        app.screen.query_one(Input).value = "Second"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("down", "enter")       # switch to the new profile
        await pilot.pause()
        assert deck_rows(app) == ["Default"]
    run(client, scenario)
    assert client.call("profiles.getActive")["name"] == "Second"


def test_small_terminal(client):
    async def scenario(app, pilot):
        assert not app.screen.query_one("#side").display
        select_deck(app, "Animals")
        await pilot.press("enter", "space")
        await pilot.pause()
        assert app.screen.state["side"] == "answer"
    run(client, scenario, size=(60, 20))


def test_remote_server(tmp_path):
    """The same app over HTTP, with audio fetched through media.get."""
    import base64
    import os

    from ankicli.client import Client
    from ankicli.tui.audio import Audio
    from conftest import start, stop

    app_, server, url = start(tmp_path / "remote")
    remote = Client(url)
    try:
        remote.call("decks.create", name="Remote")
        remote.call("notes.create", noteType={"name": "Basic"}, deck={"name": "Remote"},
                    fields={"Front": "hola [sound:hola.mp3]", "Back": "hello"})
        remote.call("media.store", filename="hola.mp3", source={"data": base64.b64encode(b"ID3fake").decode()})

        async def scenario(app, pilot):
            assert app.remote and app.audio.media_dir is None
            assert deck_rows(app) == ["Remote"]
            await pilot.press("enter", "space", "4")
            await pilot.pause()
            assert app.screen.reviewed == 1

        async def main():
            app = AnkiTUI(remote, remote=True, splash=False)
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                await scenario(app, pilot)
        asyncio.run(main())
        assert remote.call("statistics.getToday")["count"] == 1
        audio = Audio(remote.call, None)
        path = audio.path("hola.mp3")
        assert path and open(path, "rb").read() == b"ID3fake"
        assert audio.path("missing.mp3") is None
        assert os.path.dirname(path) == audio.cache
    finally:
        remote.close()
        stop(app_, server)
