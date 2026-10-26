from conftest import b64

NOTE = {"deckName": "Default", "modelName": "Basic", "fields": {"Front": "cat", "Back": "猫"}, "tags": ["vocab"]}


def test_add_note_and_info(client):
    nid = client.legacy("addNote", note=NOTE)
    assert isinstance(nid, int)
    info = client.legacy("notesInfo", notes=[nid, 1])
    assert info[1] == {}
    note = info[0]
    assert note["noteId"] == nid and note["modelName"] == "Basic" and note["tags"] == ["vocab"]
    assert note["fields"] == {"Front": {"value": "cat", "order": 0}, "Back": {"value": "猫", "order": 1}}
    assert note["profile"] == "User 1" and len(note["cards"]) == 1 and isinstance(note["mod"], int)
    assert client.legacy("notesInfo", query="cat")[0]["noteId"] == nid
    assert client.legacy_error("notesInfo") == 'Must provide either "notes" or a "query"'


def test_duplicate_and_empty_errors(client):
    client.legacy("addNote", note=NOTE)
    # Yomitan recognises existing notes by this exact wording.
    assert client.legacy_error("addNote", note=NOTE) == "cannot create note because it is a duplicate"
    empty = {**NOTE, "fields": {"Front": "", "Back": "x"}}
    assert client.legacy_error("addNote", note=empty) == "cannot create note because it is empty"
    assert client.legacy("canAddNoteWithErrorDetail", note=NOTE) == \
        {"canAdd": False, "error": "cannot create note because it is a duplicate"}
    assert client.legacy("canAddNote", note={**NOTE, "fields": {"Front": "dog"}}) is True
    # HTML and case of the first field: duplicates compare stripped HTML.
    assert client.legacy("canAddNote", note={**NOTE, "fields": {"Front": "<b>cat</b>"}}) is False
    # allowDuplicate
    assert client.legacy("addNote", note={**NOTE, "options": {"allowDuplicate": True}})


def test_missing_model_and_deck(client):
    assert client.legacy_error("addNote", note={**NOTE, "modelName": "Nope"}) == "model was not found: Nope"
    assert client.legacy_error("addNote", note={**NOTE, "deckName": "Nope"}) == "deck was not found: Nope"


def test_duplicate_scope_deck(client):
    client.legacy("createDeck", deck="A")
    client.legacy("createDeck", deck="B")
    client.legacy("createDeck", deck="A::Child")
    client.legacy("addNote", note={**NOTE, "deckName": "A::Child"})
    scoped = {**NOTE, "deckName": "B", "options": {"duplicateScope": "deck"}}
    assert client.legacy("canAddNote", note=scoped) is True
    in_a = {**NOTE, "deckName": "A", "options": {"duplicateScope": "deck",
                                                  "duplicateScopeOptions": {"checkChildren": True}}}
    assert client.legacy("canAddNote", note=in_a) is False
    no_children = {**NOTE, "deckName": "A", "options": {"duplicateScope": "deck"}}
    assert client.legacy("canAddNote", note=no_children) is True
    # Other note types only count with checkAllModels.
    other = {**NOTE, "modelName": "Basic (and reversed card)"}
    assert client.legacy("canAddNote", note=other) is True
    other_all = {**other, "options": {"duplicateScopeOptions": {"checkAllModels": "true"}}}
    assert client.legacy("canAddNote", note=other_all) is False


def test_field_matching_and_tags(client):
    nid = client.legacy("addNote", note={"deckName": "Default", "modelName": "Basic",
                                         "fields": {" front ": "x", "BACK": None, "Unknown": "ignored"},
                                         "tags": ["", "a b", None, "a"]})
    note = client.legacy("notesInfo", notes=[nid])[0]
    assert note["fields"]["Front"]["value"] == "x" and note["fields"]["Back"]["value"] == ""
    assert sorted(note["tags"]) == ["a", "b"]


def test_add_notes_atomic(client):
    good = {**NOTE, "fields": {"Front": "one"}}
    bad = {**NOTE, "modelName": "non_existent_model"}
    error = client.legacy_error("addNotes", notes=[good, bad])
    assert error == "['model was not found: non_existent_model']"
    assert client.legacy("findNotes", query="one") == []
    ids = client.legacy("addNotes", notes=[good, {**NOTE, "fields": {"Front": "two"}}])
    assert len(ids) == 2 and all(isinstance(i, int) for i in ids)
    # Duplicates inside one batch are rejected too.
    dupes = [{**NOTE, "fields": {"Front": "three"}}, {**NOTE, "fields": {"Front": "three"}}]
    assert "duplicate" in client.legacy_error("addNotes", notes=dupes)


def test_can_add_notes(client):
    client.legacy("addNote", note=NOTE)
    notes = [NOTE, {**NOTE, "fields": {"Front": "new"}}]
    assert client.legacy("canAddNotes", notes=notes) == [False, True]
    assert client.legacy("canAddNotesWithErrorDetail", notes=notes) == [
        {"canAdd": False, "error": "cannot create note because it is a duplicate"}, {"canAdd": True}]


def test_inline_media(client, tmp_path):
    path = tmp_path / "pic.png"
    path.write_bytes(b"\x89PNG fake")
    note = {**NOTE, "audio": [{"filename": "cat.mp3", "data": b64(b"xyz"), "fields": ["Back"]}],
            "picture": {"filename": "pic.png", "path": str(path), "fields": "front"}}
    nid = client.legacy("addNote", note=note)
    fields = client.legacy("notesInfo", notes=[nid])[0]["fields"]
    assert fields["Back"]["value"] == "猫[sound:cat.mp3]"
    assert fields["Front"]["value"] == 'cat<img src="pic.png">'
    assert client.legacy("retrieveMediaFile", filename="cat.mp3") == b64(b"xyz")
    # A failed download is written into the field, like Anki-Connect.
    broken = {**NOTE, "fields": {"Front": "broken"},
              "audio": [{"filename": "x.mp3", "path": "/nonexistent/x.mp3", "fields": ["Back"]}]}
    nid = client.legacy("addNote", note=broken)
    assert "No such file or directory" in client.legacy("notesInfo", notes=[nid])[0]["fields"]["Back"]["value"]


def test_update_note_fields_and_tags(client):
    nid = client.legacy("addNote", note=NOTE)
    assert client.legacy("updateNoteFields", note={"id": nid, "fields": {"back": "chat"}}) is None
    client.legacy("updateNote", note={"id": str(nid), "fields": {"Front": None}, "tags": " one two "})
    note = client.legacy("notesInfo", notes=[nid])[0]
    assert note["fields"]["Front"]["value"] == "" and note["fields"]["Back"]["value"] == "chat"
    assert sorted(note["tags"]) == ["one", "two"]
    client.legacy("updateNoteTags", note=nid, tags=["x"])
    assert client.legacy("getNoteTags", note=nid) == ["x"]
    assert client.legacy_error("updateNote", note={"id": nid}) == 'Must provide a "fields" or "tags" property.'
    assert client.legacy_error("updateNoteFields", note={"id": 1, "fields": {}}) == "Note was not found: 1"


def test_tags(client, basic):
    client.legacy("addTags", notes=basic[:2], tags="french  verbs")
    assert sorted(client.legacy("getNoteTags", note=basic[0])) == ["french", "t", "verbs"]
    client.legacy("removeTags", notes=basic, tags="verbs")
    client.legacy("addTags", notes=[basic[2]], tags="t", add=False)
    assert client.legacy("getNoteTags", note=basic[2]) == []
    client.legacy("replaceTags", notes=basic, tag_to_replace="french", replace_with_tag="fr")
    assert "fr" in client.legacy("getTags")
    client.legacy("replaceTagsInAllNotes", tag_to_replace="t", replace_with_tag="tt")
    assert client.legacy("findNotes", query="tag:tt") == sorted(basic[:2])
    client.legacy("clearUnusedTags")
    assert "french" not in client.legacy("getTags")


def test_find_delete_and_mod_times(client, basic):
    assert client.legacy("findNotes", query="deck:Test") == sorted(basic)
    assert client.legacy("findNotes") == []
    mods = client.legacy("notesModTime", notes=[basic[0], 1])
    assert mods[0]["noteId"] == basic[0] and mods[1] == {}
    cards = client.legacy("findCards", query="deck:Test")
    assert sorted(client.legacy("cardsToNotes", cards=cards + [1])) == sorted(basic)
    client.legacy("deleteNotes", notes=[basic[0], 1])
    assert client.legacy("findNotes", query="deck:Test") == sorted(basic[1:])
    assert "notes.findEmpty" in client.legacy_error("removeEmptyNotes")


def test_update_note_model(client):
    nid = client.legacy("addNote", note=NOTE)
    client.legacy("updateNoteModel", note={"id": nid, "modelName": "Basic (and reversed card)",
                                           "fields": {"Front": "cat2", "Back": "猫2"}, "tags": ["moved"]})
    note = client.legacy("notesInfo", notes=[nid])[0]
    assert note["modelName"] == "Basic (and reversed card)" and len(note["cards"]) == 2
    assert note["fields"]["Front"]["value"] == "cat2" and note["tags"] == ["moved"]
    assert client.legacy_error("updateNoteModel", note={"id": nid, "modelName": "Nope", "fields": {"a": "b"}}) \
        == "Model 'Nope' not found"


def test_invalid_ids(client):
    assert "64-bit" in client.legacy_error("notesInfo", notes=["abc"])
    assert client.legacy("notesInfo", notes=["1"]) == [{}]
