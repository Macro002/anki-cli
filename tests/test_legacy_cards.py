def cards_of(client, query="deck:Test"):
    return client.legacy("findCards", query=query)


def test_cards_info_full_and_filtered(client, basic):
    cid = cards_of(client)[0]
    info = client.legacy("cardsInfo", cards=[cid, 1])
    assert info[1] == {}
    card = info[0]
    for key in ("cardId", "fields", "fieldOrder", "question", "answer", "modelName", "ord", "deckName", "css",
                "factor", "interval", "note", "type", "queue", "due", "reps", "lapses", "left", "mod",
                "nextReviews", "flags"):
        assert key in card, key
    assert card["deckName"] == "Test" and card["modelName"] == "Basic" and len(card["nextReviews"]) == 4
    assert client.legacy("cardsInfo", cards=[cid], fields=["cardId", "queue"]) == [{"cardId": cid, "queue": 0}]
    assert client.legacy("cardsInfo", cards=[cid], fields=[]) == [{}]
    assert client.legacy("cardsModTime", cards=[cid])[0]["cardId"] == cid


def test_suspend(client, basic):
    cards = cards_of(client)
    assert client.legacy("suspend", cards=cards[:2]) is True
    assert client.legacy("suspend", cards=cards[:2]) is False
    assert client.legacy("suspended", card=cards[0]) is True
    assert client.legacy("areSuspended", cards=[cards[0], cards[2], 1]) == [True, False, None]
    assert client.legacy("unsuspend", cards=cards[:1]) is None
    assert client.legacy("areSuspended", cards=cards[:2]) == [False, True]
    assert client.legacy_error("suspend", cards=[1]) == "Card was not found: 1"


def test_ease_and_specific_values(client, basic):
    cid = cards_of(client)[0]
    assert client.legacy("setEaseFactors", cards=[cid, 1], easeFactors=[3100, 2000]) == [True, False]
    assert client.legacy("getEaseFactors", cards=[cid, 1]) == [3100, None]
    assert client.legacy("setSpecificValueOfCard", card=cid, keys=["flags"], newValues=["1"]) == [True]
    assert client.legacy("cardsInfo", cards=[cid], fields=["flags"])[0]["flags"] == 1
    assert client.legacy("setSpecificValueOfCard", card=cid, keys=["ivl"], newValues=[3]) is False
    assert client.legacy("setSpecificValueOfCard", card=cid, keys=["ivl"], newValues=[3], warning_check=True) == [True]
    assert "native scheduling" in client.legacy_error("setSpecificValueOfCard", card=cid, keys=["queue"],
                                                       newValues=[2], warning_check=True)


def test_answer_forget_relearn_and_due(client, basic):
    cards = cards_of(client)
    assert client.legacy("answerCards", answers=[{"cardId": cards[0], "ease": 3},
                                                 {"cardId": "1", "ease": 3}]) == [True, False]
    info = client.legacy("cardsInfo", cards=[cards[0]], fields=["reps", "queue"])[0]
    assert info["reps"] == 1 and info["queue"] == 1
    assert client.legacy_error("answerCards", answers=[{"cardId": cards[0], "ease": 5}]) == "Invalid ease."
    assert client.legacy("getIntervals", cards=[cards[0], cards[1]]) == [-600, 0]
    assert client.legacy("getIntervals", cards=[cards[0]], complete=True) == [[-600]]
    assert client.legacy("areDue", cards=[cards[1]]) == [True]
    assert client.legacy("setDueDate", cards=[cards[1]], days="3-7") is True
    due = client.legacy("cardsInfo", cards=[cards[1]], fields=["queue", "type"])[0]
    assert due == {"queue": 2, "type": 2}
    assert client.legacy("relearnCards", cards=[cards[1]]) is None
    assert client.legacy("cardsInfo", cards=[cards[1]], fields=["lapses"])[0]["lapses"] == 1
    assert "review card" in client.legacy_error("relearnCards", cards=[cards[2]])
    client.legacy("forgetCards", cards=[cards[1]])
    assert client.legacy("cardsInfo", cards=[cards[1]], fields=["type"])[0]["type"] == 0
    reviews = client.legacy("getReviewsOfCards", cards=[cards[0], cards[2]])
    assert len(reviews[str(cards[0])]) == 1 and reviews[str(cards[2])] == []
    assert set(reviews[str(cards[0])][0]) == {"id", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type"}


def test_review_history(client, basic):
    cards = cards_of(client)
    client.legacy("answerCards", answers=[{"cardId": cid, "ease": 3} for cid in cards])
    rows = client.legacy("cardReviews", deck="Test", startID=0)
    assert len(rows) == 3 and all(len(row) == 9 for row in rows)
    latest = client.legacy("getLatestReviewID", deck="Test")
    assert latest == rows[-1][0]
    assert client.legacy("cardReviews", deck="Test", startID=latest) == []
    assert client.legacy("getLatestReviewID", deck="Brand new") == 0
    client.legacy("insertReviews", reviews=[[1594194095746, cards[0], -1, 3, 4, -60, 2500, 6157, 0]])
    assert len(client.legacy("getReviewsOfCards", cards=[cards[0]])[str(cards[0])]) == 2
    assert client.legacy("getNumCardsReviewedToday") == 3
    by_day = client.legacy("getNumCardsReviewedByDay")
    assert by_day[0][1] == 3 and isinstance(by_day[0][0], str)
    assert "<" in client.legacy("getCollectionStatsHTML")
