"""The headless reviewer, browser and Add dialog behind the gui* actions."""


def test_review_session(client, basic):
    assert client.legacy("guiReviewActive") is False
    assert client.legacy_error("guiCurrentCard") == "Gui review is not currently active."
    assert client.legacy("guiDeckReview", name="Nope") is False
    assert client.legacy("guiDeckReview", name="Test") is True
    assert client.legacy("guiReviewActive") is True
    current = client.legacy("guiCurrentCard")
    for key in ("cardId", "fields", "fieldOrder", "question", "answer", "modelName", "deckName", "css",
                "buttons", "nextReviews", "template"):
        assert key in current
    assert current["buttons"] == [1, 2, 3, 4] and current["deckName"] == "Test" and current["template"] == "Card 1"
    # Answering requires the answer side.
    assert client.legacy("guiAnswerCard", ease=3) is False
    assert client.legacy("guiShowAnswer") is True
    assert client.legacy("guiAnswerCard", ease=7) is False
    assert client.legacy("guiStartCardTimer") is True
    assert client.legacy("guiAnswerCard", ease=3) is True
    nxt = client.legacy("guiCurrentCard")
    assert nxt["cardId"] != current["cardId"]
    # Undo brings the answered card back.
    assert client.legacy("guiUndo") is True
    assert client.legacy("guiCurrentCard")["cardId"] == current["cardId"]
    # Finish the deck: three new cards, each answered Easy, then the reviewer closes.
    for _ in range(3):
        client.legacy("guiShowAnswer")
        assert client.legacy("guiAnswerCard", ease=4) is True
    assert client.legacy("guiReviewActive") is False
    assert client.legacy("guiShowAnswer") is False
    assert client.legacy("guiDeckOverview", name="Test") is True
    assert client.legacy("guiDeckBrowser") is None


def test_browser(client, basic):
    assert client.legacy("guiSelectCard", card=1) is False
    cards = client.legacy("guiBrowse", query="deck:Test")
    assert cards == sorted(client.legacy("findCards", query="deck:Test"))
    ordered = client.legacy("guiBrowse", query="deck:Test",
                            reorderCards={"order": "descending", "columnId": "noteCrt"})
    assert ordered == sorted(cards, reverse=True)
    assert client.legacy_error("guiBrowse", query="x", reorderCards={"order": "up", "columnId": "noteCrt"}) == \
        "invalid card order: up"
    assert client.legacy_error("guiBrowse", query="x", reorderCards={"order": "ascending", "columnId": "nope"}) == \
        "invalid columnId: nope"
    assert client.legacy("guiSelectCard", card=cards[0]) is True
    assert client.legacy("guiSelectedNotes") == [client.legacy("cardsToNotes", cards=[cards[0]])[0]]
    assert client.legacy("guiBrowse") == []


def test_add_dialog(client):
    assert client.legacy("guiAddNoteSetData", note={"fields": {"Front": "x"}}) == \
        {"error": "Add Note dialog is not open", "code": 1}
    assert client.legacy("guiAddCards", note={"deckName": "Default", "modelName": "Basic",
                                              "fields": {"Front": "draft"}, "tags": ["a"]}) == 0
    assert client.legacy("guiAddNoteSetData", note={"fields": {"Back": "more"}, "tags": ["b"]}, append=True) is True
    assert client.legacy_error("guiAddNoteSetData", note={"fields": {"Nope": "x"}}) == \
        'Field "Nope" not found in current note'
    drafts = client.rpc("editors.list")
    assert drafts[0]["fields"] == {"Front": "draft", "Back": "more"} and drafts[0]["tags"] == ["a", "b"]
    saved = client.rpc("editors.save", editorId=drafts[0]["id"])
    assert saved["noteId"] and client.legacy("findNotes", query="draft")


def test_misc_gui(client, basic, tmp_path):
    assert client.legacy("guiCheckDatabase") is True
    assert client.legacy("guiEditNote", note=basic[0]) is None
    path = tmp_path / "deck.apkg"
    assert client.legacy("exportPackage", deck="Test", path=str(path)) is True
    client.legacy("deleteDecks", decks=["Test"], cardsToo=True)
    assert client.legacy("guiImportFile", path=str(path)) is None
    assert "Test" in client.legacy("deckNames")
    assert client.legacy("reloadCollection") is None
    assert client.legacy("exportPackage", deck="Nope", path=str(path)) is False
    assert client.legacy("importPackage", path=str(path)) is True
    assert client.legacy_error("sync") == "sync: auth not configured"
