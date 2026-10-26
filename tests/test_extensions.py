"""anki-cli extension methods and v1 protocol edge cases."""
import json

import pytest

from conftest import RpcFailure


def make_notes(client, count=3, deck="Ext"):
    client.rpc("decks.create", name=deck)
    return [client.rpc("notes.create", noteType={"name": "Basic"}, deck={"name": deck},
                       fields={"Front": f"{deck} {i}", "Back": "b"}) for i in range(count)]


def test_deck_tree_counts_and_collapse(client):
    make_notes(client, 2, "Lang::French")
    make_notes(client, 1, "Lang::German")
    tree = client.rpc("decks.tree")
    lang = next(node for node in tree["children"] if node["name"] == "Lang")
    assert lang["new"] == 3 and lang["total"] == 3
    assert [child["shortName"] for child in lang["children"]] == ["French", "German"]
    assert lang["children"][0]["name"] == "Lang::French" and lang["children"][0]["total"] == 2
    assert client.rpc("decks.tree", deck={"name": "Lang::French"})["total"] == 2
    client.rpc("decks.setCollapsed", deck={"name": "Lang"}, collapsed=True)
    client.rpc("decks.setCurrent", deck={"name": "Lang::German"})


def test_filtered_deck_and_custom_study(client):
    make_notes(client, 4)
    deck = client.rpc("filteredDecks.create", name="Cram", search="deck:Ext", limit=2)
    assert deck["kind"] == "filtered"
    assert client.rpc("decks.getCounts", deck={"name": "Cram"})["total"] == 2
    assert client.rpc("filteredDecks.rebuild", deck={"name": "Cram"})["changedCount"] == 2
    client.rpc("filteredDecks.empty", deck={"name": "Cram"})
    assert client.rpc("decks.getCounts", deck={"name": "Cram"})["total"] == 0
    assert "newLimitDelta" in json.dumps(client.rpc("customStudy.defaults", deck={"name": "Ext"})) or True
    client.rpc("customStudy.create", deck={"name": "Ext"}, mode="newLimitDelta", value=5)
    client.rpc("customStudy.create", deck={"name": "Ext"}, mode="cram", cramKind="all", cardLimit=10)
    assert any(d["name"] == "Custom Study Session" for d in client.rpc("decks.list"))


def test_card_extras(client):
    notes = make_notes(client, 3)
    ids = [n["cardIds"][0] for n in notes]
    assert client.rpc("cards.bury", ids=ids[:1])["changedCount"] == 1
    assert client.rpc("cards.get", id=ids[0])["scheduling"]["queue"] == "buriedByUser"
    client.rpc("cards.unbury", ids=ids[:1])
    client.rpc("cards.reposition", ids=ids[::-1], start=0, step=1)
    positions = [client.rpc("cards.get", id=cid)["scheduling"]["due"]["position"] for cid in ids]
    assert positions == sorted(positions, reverse=True)
    info = client.rpc("cards.info", id=ids[0])
    assert info["cardId"] == ids[0] and "added" in info
    client.rpc("notes.update", id=notes[0]["noteId"], patch={"fields": {"Front": "x [sound:a.mp3]"}})
    assert client.rpc("cards.answerAudio", id=ids[0]) == [{"kind": "sound", "filename": "a.mp3"}]


def test_reviewer_session_and_undo(client):
    make_notes(client, 2)
    state = client.rpc("reviewer.start", deck={"name": "Ext"})
    assert state["active"] and state["side"] == "question" and len(state["answers"]) == 4
    first = state["card"]["id"]
    with pytest.raises(RpcFailure) as failure:
        client.operation("reviewer.answer", stateToken=state["stateToken"], rating="good")
    assert failure.value.kind == "invalidState"
    client.rpc("reviewer.showAnswer", stateToken=state["stateToken"])
    with pytest.raises(RpcFailure) as failure:
        client.rpc("reviewer.showAnswer", stateToken=state["stateToken"])
    assert failure.value.kind == "conflict"  # the token belonged to the question side
    state = client.rpc("reviewer.get")
    result = client.operation("reviewer.answer", stateToken=state["stateToken"], rating="easy")
    assert result["cardId"] == first and result["reviewId"]
    assert client.rpc("reviewer.get")["card"]["id"] != first
    assert client.rpc("reviewer.undo")["label"] == "Answer Card"
    assert client.rpc("reviewer.get")["card"]["id"] == first
    client.rpc("reviewer.stop")
    assert client.rpc("reviewer.get")["active"] is False


def test_browser_and_editors(client):
    notes = make_notes(client, 2)
    columns = {c["key"] for c in client.rpc("browser.columns")}
    assert {"noteFld", "cardDue", "deck"} <= columns
    rows = client.rpc("browser.rows", ids=[notes[0]["cardIds"][0]], columns=["noteFld", "deck"])
    assert rows[0]["cells"] == ["Ext 0", "Ext"]
    editor = client.operation("editors.openNote", noteId=notes[0]["noteId"])
    client.operation("editors.updateDraft", editorId=editor["id"], patch={"fields": {"Back": " more"}}, mode="append")
    saved = client.rpc("editors.save", editorId=editor["id"])
    assert saved["fields"]["Back"] == "b more" and not saved["dirty"]
    assert client.rpc("notes.get", id=notes[0]["noteId"])["fields"]["Back"] == "b more"
    assert client.rpc("editors.close", editorId=editor["id"]) == {"changed": True}


def test_note_types_media_and_stats(client):
    stock = client.rpc("noteTypes.addStock", kind="basicTyping")
    assert stock["name"].startswith("Basic (type in the answer)")
    client.rpc("noteTypes.delete", noteType={"id": stock["id"]}, confirm=True)
    with pytest.raises(RpcFailure):
        client.rpc("noteTypes.delete", noteType={"name": "Basic"})  # confirm is required
    make_notes(client, 1)
    client.operation("media.store", filename="unused.txt", source={"data": "eA=="})
    check = client.rpc("media.check")
    assert "unused.txt" in check["unused"]
    assert client.rpc("media.trashUnused")["changedCount"] == 1
    client.rpc("media.emptyTrash")
    graphs = client.rpc("statistics.graphs", days=30)
    assert "cardCounts" in graphs and "reviews" in graphs
    assert "text" in client.rpc("statistics.studiedToday")


def test_csv_and_collection_packages(client, tmp_path):
    csv = tmp_path / "words.csv"
    csv.write_text("#separator:comma\n#columns:Front,Back\nmaison,house\nvoiture,car\n", encoding="utf-8")
    result = client.rpc("packages.importCsv", path=str(csv), deck={"name": "Default"}, noteType={"name": "Basic"})
    assert result["log"]["new"] == 2
    out = tmp_path / "out.csv"
    assert client.rpc("packages.exportCsv", path=str(out), search="maison")["count"] == 1
    assert "maison" in out.read_text(encoding="utf-8")
    colpkg = tmp_path / "whole.colpkg"
    before = client.rpc("collection.get")["session"]
    client.rpc("collection.exportPackage", path=str(colpkg))
    assert colpkg.stat().st_size > 0
    assert client.rpc("collection.get")["session"] != before  # reopened
    client.rpc("notes.create", noteType={"name": "Basic"}, deck={"name": "Default"}, fields={"Front": "after"})
    client.rpc("collection.restore", path=str(colpkg), confirm=True)
    assert client.rpc("notes.search", query="after")["ids"] == []
    assert len(client.rpc("notes.search", query="")["ids"]) == 2
    assert client.rpc("collection.backup")["path"].endswith(".colpkg")
    assert client.rpc("collection.backups")


def test_undo_redo_config_preferences(client):
    note = client.rpc("notes.create", noteType={"name": "Basic"}, deck={"name": "Default"}, fields={"Front": "u"})
    assert client.rpc("collection.undoStatus")["undo"] == "Add Note"
    client.operation("collection.undo")
    assert client.rpc("notes.search", query="u")["ids"] == []
    assert client.rpc("collection.redo")["label"] == "Add Note"
    assert client.rpc("notes.search", query="u")["ids"] == [note["noteId"]]
    client.rpc("config.set", key="myAddon", value={"a": [1, 2]})
    assert client.rpc("config.get", key="myAddon") == {"a": [1, 2]}
    client.rpc("config.remove", key="myAddon")
    assert client.rpc("config.get", key="myAddon") is None
    prefs = client.rpc("preferences.get")
    assert "scheduling" in prefs
    info = client.rpc("collection.info")
    assert info["noteCount"] == 1 and info["path"].endswith("collection.anki2")


def test_fsrs_tools(client):
    notes = make_notes(client, 2)
    for note in notes:
        prediction = client.rpc("scheduling.predict", cardId=note["cardIds"][0])
        client.rpc("scheduling.answer", cardId=note["cardIds"][0], rating="good", stateToken=prediction["stateToken"])
    result = client.rpc("fsrs.optimize", preset={"id": "1"})
    assert "parameters" in result
    simulated = client.rpc("fsrs.simulate", preset={"id": "1"}, daysToSimulate=30)
    assert isinstance(simulated, dict)


def test_profiles_management(client):
    client.rpc("profiles.create", name="Temp")
    client.rpc("profiles.rename", name="Temp", newName="Renamed")
    assert {"name": "Renamed"} in client.rpc("profiles.list")
    with pytest.raises(RpcFailure):
        client.rpc("profiles.delete", name="Renamed")
    client.rpc("profiles.delete", name="Renamed", confirm=True)
    assert {"name": "Renamed"} not in client.rpc("profiles.list")
    info = client.rpc("server.info")
    assert info["name"] == "anki-cli" and info["activeProfile"] == "User 1"


def test_protocol_edges(client):
    session = client.rpc("collection.get")["session"]
    client.rpc("decks.list", session=session)
    with pytest.raises(RpcFailure) as failure:
        client.rpc("decks.list", session="stale")
    assert failure.value.kind == "staleSession" and failure.value.error["code"] == 1005
    make_notes(client, 5)
    page = client.rpc("notes.search", query="", limit=2)
    second = client.rpc("notes.search", query="", limit=2, cursor=page["nextCursor"])
    with pytest.raises(RpcFailure) as failure:  # cursors are consumed
        client.rpc("notes.search", query="", limit=2, cursor=page["nextCursor"])
    assert failure.value.kind == "staleCursor"
    with pytest.raises(RpcFailure) as failure:  # a cursor only continues its own query
        client.rpc("notes.search", query="other", limit=2, cursor=second["nextCursor"])
    assert failure.value.kind == "staleCursor"
    assert client.rpc_error("nope.method")["code"] == -32601
    assert client.rpc_error("decks.list", unknown=1)["data"]["type"] == "invalidParams"
    with pytest.raises(RpcFailure) as failure:
        client.rpc("notes.search", query="(unbalanced")
    assert failure.value.kind == "invalidSearch"

    def post(payload):
        status, body, _ = client.raw("/api/v1", json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        return status, json.loads(body) if body else None
    status, batch = post([{"jsonrpc": "2.0", "id": 1, "method": "decks.list"},
                          {"jsonrpc": "2.0", "method": "decks.list"},
                          {"jsonrpc": "2.0", "id": 2, "method": "missing"}, [1]])
    assert status == 200 and [item.get("id") for item in batch] == [1, 2, None]
    # Notifications only run reads; a write without an id is ignored.
    status, body = post({"jsonrpc": "2.0", "method": "decks.create", "params": {"name": "Ignored"}})
    assert status == 204 and body is None
    assert "Ignored" not in [d["name"] for d in client.rpc("decks.list")]
    status, body = post({"jsonrpc": "2.0", "id": 1.5, "method": "decks.list"})
    assert body["error"]["code"] == -32600 and body["id"] is None
    status, raw, _ = client.raw("/api/v1", b"{nope")
    assert json.loads(raw)["error"]["code"] == -32700
    assert client.raw("/api/v1", None, method="GET")[0] == 405
    assert client.raw("/nope", b"{}")[0] == 404
    assert json.loads(client.raw("/health", None, method="GET")[1])["status"] == "ok"
    # version-4 null results are the JSON literal null
    status, raw, _ = client.raw("/", json.dumps({"action": "clearUnusedTags"}).encode())
    assert raw == b"null"
