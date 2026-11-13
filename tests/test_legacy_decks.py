def test_deck_names_create_and_lookup(client):
    did = client.legacy("createDeck", deck="Japanese::Tokyo")
    assert client.legacy("createDeck", deck="Japanese::Tokyo") == did
    assert set(client.legacy("deckNames")) == {"Default", "Japanese", "Japanese::Tokyo"}
    assert client.legacy("deckNamesAndIds")["Japanese::Tokyo"] == did
    assert client.legacy("deckNameFromId", deckId=did) == "Japanese::Tokyo"
    assert client.legacy_error("deckNameFromId", deckId=999) == "deck was not found: 999"


def test_change_get_and_delete_decks(client, basic):
    cards = client.legacy("findCards", query="deck:Test")
    client.legacy("changeDeck", cards=cards[:2], deck="Moved::Here")
    assert client.legacy("getDecks", cards=cards) == {"Moved::Here": cards[:2], "Test": cards[2:]}
    assert client.legacy_error("getDecks", cards=[1]) == "Card was not found: 1"
    assert "not possible" in client.legacy_error("deleteDecks", decks=["Test"])
    client.legacy("deleteDecks", decks=["Test", "Missing"], cardsToo=True)
    assert "Test" not in client.legacy("deckNames")
    assert client.legacy("findCards", query="deck:Test") == []


def test_deck_stats(client, basic):
    stats = client.legacy("getDeckStats", decks=["Test", "Created By Stats"])
    by_name = {value["name"]: (key, value) for key, value in stats.items()}
    key, test = by_name["Test"]
    assert key == str(test["deck_id"]) and test["new_count"] == 3 and test["total_in_deck"] == 3
    assert set(test) == {"deck_id", "name", "new_count", "learn_count", "review_count", "total_in_deck"}
    assert "Created By Stats" in client.legacy("deckNames")


def test_deck_stats_for_the_hidden_empty_default_deck(client, basic):
    # Anki hides an empty Default deck from its due tree; it still has (zero) counts.
    stats = client.legacy("getDeckStats", decks=["Default", "Test"])
    assert stats["1"]["new_count"] == 0 and stats["1"]["total_in_deck"] == 0
    assert any(entry["name"] == "Test" and entry["new_count"] == 3 for entry in stats.values())
    assert client.rpc("decks.getCounts", deck={"name": "Default"})["new"] == 0


def test_deck_stats_match_per_deck_counts(client):
    # getDeckStats counts every deck in one pass; it must agree with decks.getCounts deck by deck,
    # with subdecks, studied cards and a filtered deck (whose cards also count for their home deck).
    names = ["A", "A::B", "A::B::C", "E"]
    for name in names:
        client.legacy("createDeck", deck=name)
    client.legacy("addNotes", notes=[{"deckName": names[i % 4], "modelName": "Basic",
                                      "fields": {"Front": f"q{i}", "Back": "a"}} for i in range(40)])
    cards = client.legacy("findCards", query="deck:A")
    client.legacy("answerCards", answers=[{"cardId": card, "ease": 3} for card in cards[:6]])
    client.legacy("setDueDate", cards=cards[6:9], days="0")
    client.rpc("filteredDecks.create", name="E::Filtered", search="deck:A::B", limit=5)
    stats = client.legacy("getDeckStats", decks=list(client.legacy("deckNamesAndIds")))
    assert len(stats) == 6
    for entry in stats.values():
        counts = client.rpc("decks.getCounts", deck={"name": entry["name"]})
        assert (entry["new_count"], entry["learn_count"], entry["review_count"], entry["total_in_deck"]) == \
            (counts["new"], counts["learning"], counts["review"], counts["total"]), entry["name"]


def test_deck_config(client):
    config = client.legacy("getDeckConfig", deck="Default")
    assert config["id"] == 1 and config["new"]["perDay"] == 20
    assert client.legacy("getDeckConfig", deck="Nope") is False
    assert client.legacy("saveDeckConfig", config={"id": 1, "new": {"perDay": 33}, "rev": {"perDay": 150}}) is True
    config = client.legacy("getDeckConfig", deck="Default")
    assert config["new"]["perDay"] == 33 and config["rev"]["perDay"] == 150
    assert client.legacy("saveDeckConfig", config={"id": 424242}) is False
    new_id = client.legacy("cloneDeckConfigId", name="Copy of Default", cloneFrom=1)
    assert isinstance(new_id, int)
    assert client.legacy("cloneDeckConfigId", name="x", cloneFrom=999) is False
    client.legacy("createDeck", deck="Other")
    assert client.legacy("setDeckConfigId", decks=["Other"], configId=new_id) is True
    assert client.legacy("getDeckConfig", deck="Other")["id"] == new_id
    assert client.legacy("setDeckConfigId", decks=["Missing"], configId=new_id) is False
    assert client.legacy("removeDeckConfigId", configId=1) is False
    assert client.legacy("removeDeckConfigId", configId=new_id) is True
    assert client.legacy("getDeckConfig", deck="Other")["id"] == 1
