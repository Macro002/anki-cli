"""Every v1 method on anki-cli, with results validated against Anki-Connect's JSON schema."""
import base64

import pytest
from jsonschema import Draft202012Validator

from plugin.contract import SCHEMA
from tests_api.test_runtime import admitted, call, native  # noqa: F401


def rpc(service, method, **params):
    """A raw JSON-RPC round trip, validating the full response envelope."""
    from ankicli.rpc import Rpc
    response = Rpc(service.app).handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    meta = SCHEMA["x-methods"][method]
    Draft202012Validator({**SCHEMA, "oneOf": [meta["response"]]}).validate(response)
    return response


def test_every_v1_method_is_registered():
    from ankicli.methods import METHODS
    assert set(SCHEMA["x-methods"]) <= set(METHODS)


def test_v1_walkthrough_matches_schema(native, tmp_path):
    owner, service = native
    c = lambda method, **params: call(service, method, **params)  # noqa: E731
    assert c("api.describe")["apiMajor"] == 1
    assert c("profiles.list") and c("profiles.getActive")
    session = c("collection.get")["session"]
    deck = c("decks.create", name="Japanese::Kanji")
    assert c("decks.get", deck={"name": "Japanese::Kanji"}) == deck
    assert any(d["name"] == "Japanese" for d in c("decks.list"))
    c("decks.update", deck={"id": deck["id"]}, name="Japanese::漢字")
    note = c("notes.create", noteType={"name": "Basic"}, deck={"name": "Japanese::漢字"},
             fields={"Front": "猫", "Back": "cat"}, tags=["animal"], session=session)
    assert c("notes.validate", note={"noteType": {"name": "Basic"}, "deck": {"name": "Default"},
                                    "fields": {"Front": "猫"}})["issues"][0]["type"] == "duplicate"
    c("notes.validateMany", notes=[{"noteType": {"name": "Basic"}, "deck": {"name": "Default"},
                                    "fields": {"Front": ""}}])
    batch = c("notes.createMany", atomic=True, notes=[
        {"noteType": {"name": "Basic"}, "deck": {"name": "Default"}, "fields": {"Front": f"n{i}"}} for i in range(3)])
    c("notes.createMany", notes=[{"noteType": {"name": "Nope"}, "deck": {"name": "Default"}, "fields": {}}])
    nid = note["noteId"]
    cid = note["cardIds"][0]
    c("notes.get", id=nid)
    c("notes.getMany", ids=[nid, "999"])
    page = c("notes.search", query="", limit=2)
    assert page["nextCursor"]
    c("notes.search", query="", limit=2, cursor=page["nextCursor"])
    c("notes.search", query="", sort={"column": "noteFld", "direction": "descending"})
    c("notes.update", id=nid, patch={"fields": {"Back": "neko"}, "tags": ["animal", "jlpt"]})
    plan = c("notes.planConversion", source={"name": "Basic"}, target={"name": "Basic (and reversed card)"})
    c("notes.convert", ids=[batch["items"][0]["result"]["noteId"]], target={"name": "Basic (and reversed card)"},
      fields=plan["fields"], templates=plan["templates"], planToken=plan["token"])
    c("notes.findEmpty", criterion="noCards")
    c("tags.list")
    c("tags.add", noteIds=[nid], tags=["extra"])
    c("tags.remove", noteIds=[nid], tags=["extra"])
    c("tags.replace", **{"from": "jlpt", "to": "jlpt5", "allNotes": True})
    c("tags.deleteUnused")
    c("cards.get", id=cid)
    c("cards.getMany", ids=[cid, "999"])
    c("cards.search", query="deck:Japanese")
    c("cards.render", id=cid)
    c("cards.setFlags", ids=[cid], flag=3)
    c("cards.setSuspended", ids=[cid], suspended=True)
    c("cards.setSuspended", ids=[cid], suspended=False)
    c("scheduling.get", cardId=cid)
    c("scheduling.getQueue", fetchLimit=5)
    c("scheduling.getDue", cardId=cid)
    prediction = c("scheduling.predict", cardId=cid)
    c("scheduling.answer", cardId=cid, rating="good", stateToken=prediction["stateToken"], elapsedMs=1500)
    other = batch["items"][1]["result"]["cardIds"][0]
    p2 = c("scheduling.predict", cardId=other)
    c("scheduling.answerMany", answers=[{"cardId": other, "rating": "easy", "stateToken": p2["stateToken"]}])
    c("scheduling.setDueDate", cardIds=[other], days="1")
    c("scheduling.reset", cardIds=[other])
    c("decks.getCounts", deck={"name": "Japanese"})
    c("cards.move", ids=[cid], deck={"name": "Default"})
    c("deckPresets.list")
    preset = c("deckPresets.create", name="Intense")
    c("deckPresets.get", preset={"name": "Intense"})
    c("deckPresets.update", preset={"id": preset["id"]}, settings={"newPerDay": 50, "reviewOrder": "random",
                                                                   "learnStepsMinutes": [1, 10]})
    c("deckPresets.assign", decks=[{"name": "Japanese"}], preset={"id": preset["id"]})
    c("deckPresets.delete", preset={"id": preset["id"]}, replacement={"id": "1"})
    c("noteTypes.list")
    c("noteTypes.get", noteType={"name": "Basic"})
    model = c("noteTypes.create", name="Vocab", fields=[{"name": "Word"}, {"name": "Meaning"}],
              templates=[{"name": "Card", "questionHtml": "{{Word}}", "answerHtml": "{{Meaning}}"}])
    c("noteTypes.update", noteType={"id": model["id"]}, patch={"css": ".card{}"})
    c("noteTypes.editStructure", noteType={"name": "Vocab"}, edits=[
        {"op": "addField", "field": {"name": "Audio"}}, {"op": "moveField", "name": "Audio", "index": 0}])
    c("noteTypes.getTemplateUsage", noteType={"name": "Vocab"})
    c("noteTypes.replaceText", find="{{Word}}", replace="<b>{{Word}}</b>", allNoteTypes=True)
    c("noteTypes.deleteUnused", noteTypes=[{"name": "Vocab"}])
    data = base64.b64encode(b"hello").decode()
    stored = c("media.store", filename="hello.txt", source={"data": data})
    c("media.store", filename="hello.txt", source={"data": data}, collision="replace",
      skipIfHash={"algorithm": "sha256", "digest": stored["sha256"]})
    c("media.get", filename="hello.txt")
    c("media.list", pattern="*.txt")
    c("media.getDirectory")
    c("media.delete", filename="hello.txt")
    c("reviews.list", deck={"name": "Default"})
    c("reviews.getLatestId", cardIds=[cid])
    c("statistics.getToday")
    c("statistics.getReviewDays")
    c("statistics.getSummary")
    c("statistics.getHtml", deck={"name": "Default"})
    path = str(tmp_path / "deck.apkg")
    c("packages.export", deck={"name": "Japanese"}, path=path, includeScheduling=True)
    c("packages.import", path=path)
    c("browser.open", query="deck:Default")
    c("browser.select", cardIds=[cid])
    c("browser.getSelection")
    editor = c("editors.openAdd", note={"noteType": {"name": "Basic"}, "deck": {"name": "Default"}})
    c("editors.updateDraft", editorId=editor["id"], patch={"fields": {"Front": "draft"}})
    c("editors.openNote", noteId=nid)
    c("application.navigate", view="review", deck={"name": "Default"})
    state = c("reviewer.get")
    if state["active"]:
        c("reviewer.startTimer", stateToken=state["stateToken"])
        c("reviewer.showAnswer", stateToken=state["stateToken"])
        state = c("reviewer.get")
        c("reviewer.playAudio", stateToken=state["stateToken"])
        c("reviewer.answer", stateToken=state["stateToken"], rating="good")
    c("application.navigate", view="deckBrowser")
    c("collection.refresh")
    c("collection.undo")
    c("collection.checkIntegrity")
    c("advanced.cards.update", cardId=cid, patch={"sm2EasePermille": 2600, "customData": '{"a":1}'})
    c("advanced.reviews.import", reviews=[{
        "id": "1594194095746", "cardId": cid, "rating": "good", "interval": {"value": 4, "unit": "days"},
        "previousInterval": {"value": 60, "unit": "seconds"}, "factor": {"encoding": "unknown", "value": 2500},
        "elapsedMs": 6157, "kind": "review"}])
    c("decks.delete", decks=[{"name": "Japanese"}], deleteCards=True)
    c("notes.delete", ids=[nid])
    batch = c("api.execute", commands=[{"method": "decks.list"}, {"method": "notes.get", "params": {"id": "999"}}])
    assert batch["items"][1]["error"]["data"]["type"] == "notFound"
    handle = service.app.call("api.execute", {"commands": [{"method": "decks.list"}]})
    assert c("operations.get", operationId=handle["operationId"])["state"] == "succeeded"
    assert c("operations.cancel", operationId=handle["operationId"]) == {"requested": False}
    c("access.requestPermission")


@pytest.mark.parametrize("example", SCHEMA["x-invalidExamples"], ids=lambda e: e.get("method", "?"))
def test_invalid_examples_are_rejected(native, example):
    """Anki-Connect's catalogue of invalid v1 inputs must fail validation without side effects."""
    owner, service = native
    from ankicli.rpc import Rpc
    before = service.col.note_count(), len(service.col.decks.all_names_and_ids())
    response = Rpc(service.app).handle({"jsonrpc": "2.0", "id": 1, "method": example["method"],
                                        "params": example["params"]})
    assert response.get("error", {}).get("data", {}).get("type") == "invalidParams", (example, response)
    assert (service.col.note_count(), len(service.col.decks.all_names_and_ids())) == before
