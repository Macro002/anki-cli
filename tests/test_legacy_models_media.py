from conftest import b64


def test_model_queries(client):
    names = client.legacy("modelNames")
    assert "Basic" in names and "Cloze" in names
    ids = client.legacy("modelNamesAndIds")
    basic_id = ids["Basic"]
    assert client.legacy("modelNameFromId", modelId=basic_id) == "Basic"
    assert client.legacy_error("modelNameFromId", modelId=1) == "model was not found: 1"
    assert client.legacy("findModelsById", modelIds=[basic_id])[0]["name"] == "Basic"
    assert client.legacy("findModelsByName", modelNames=["Basic"])[0]["id"] == basic_id
    assert client.legacy_error("findModelsByName", modelNames=["Nope"]) == "model was not found: Nope"
    assert client.legacy("modelFieldNames", modelName="Basic") == ["Front", "Back"]
    assert client.legacy("modelFieldDescriptions", modelName="Basic") == ["", ""]
    assert client.legacy("modelFieldFonts", modelName="Basic")["Front"] == {"font": "Arial", "size": 20}
    assert client.legacy("modelFieldsOnTemplates", modelName="Basic (and reversed card)") == {
        "Card 1": [["Front"], ["Back"]], "Card 2": [["Back"], ["Front"]]}
    templates = client.legacy("modelTemplates", modelName="Basic")
    assert templates == {"Card 1": {"Front": "{{Front}}", "Back": "{{FrontSide}}\n\n<hr id=answer>\n\n{{Back}}"}}
    assert "card" in client.legacy("modelStyling", modelName="Basic")["css"]


def test_create_and_edit_model(client):
    model = client.legacy("createModel", modelName="Vocab", inOrderFields=["Word", "Meaning", "Example"],
                          css=".card{color:red}", cardTemplates=[{"Name": "Recognise", "Front": "{{Word}}",
                                                                  "Back": "{{FrontSide}}<hr>{{Meaning}}"}])
    assert model["name"] == "Vocab" and [f["name"] for f in model["flds"]] == ["Word", "Meaning", "Example"]
    assert client.legacy_error("createModel", modelName="Vocab", inOrderFields=["a"],
                               cardTemplates=[{"Front": "{{a}}", "Back": "{{a}}"}]) == "Model name already exists"
    assert client.legacy_error("createModel", modelName="X", inOrderFields=[], cardTemplates=[]) == \
        "Must provide at least one field for inOrderFields"
    client.legacy("updateModelTemplates", model={"name": "Vocab", "templates": {"Recognise": {"Front": "<b>{{Word}}</b>"}}})
    assert client.legacy("modelTemplates", modelName="Vocab")["Recognise"]["Front"] == "<b>{{Word}}</b>"
    client.legacy("updateModelStyling", model={"name": "Vocab", "css": "p{}"})
    assert client.legacy("modelStyling", modelName="Vocab") == {"css": "p{}"}
    assert client.legacy("findAndReplaceInModels", modelName="Vocab", findText="Word", replaceText="Word",
                         front=True, back=False, css=False) == 0
    assert client.legacy("findAndReplaceInModels", modelName="Vocab", findText="<b>", replaceText="<i>",
                         front=True, back=False, css=False) == 1
    client.legacy("modelTemplateAdd", modelName="Vocab", template={"Name": "Recall", "Front": "{{Meaning}}",
                                                                    "Back": "{{Word}}"})
    client.legacy("modelTemplateRename", modelName="Vocab", oldTemplateName="Recall", newTemplateName="Produce")
    client.legacy("modelTemplateReposition", modelName="Vocab", templateName="Produce", index=0)
    assert list(client.legacy("modelTemplates", modelName="Vocab")) == ["Produce", "Recognise"]
    client.legacy("modelTemplateRemove", modelName="Vocab", templateName="Produce")
    client.legacy("modelFieldAdd", modelName="Vocab", fieldName="Audio", index=1)
    client.legacy("modelFieldRename", modelName="Vocab", oldFieldName="Example", newFieldName="Sentence")
    client.legacy("modelFieldReposition", modelName="Vocab", fieldName="Sentence", index=0)
    assert client.legacy("modelFieldNames", modelName="Vocab") == ["Sentence", "Word", "Audio", "Meaning"]
    client.legacy("modelFieldRemove", modelName="Vocab", fieldName="Audio")
    client.legacy("modelFieldSetFont", modelName="Vocab", fieldName="Word", font="Georgia")
    client.legacy("modelFieldSetFontSize", modelName="Vocab", fieldName="Word", fontSize=30)
    assert client.legacy("modelFieldSetDescription", modelName="Vocab", fieldName="Word",
                         description="the word") is True
    assert client.legacy("modelFieldFonts", modelName="Vocab")["Word"] == {"font": "Georgia", "size": 30}
    assert client.legacy("modelFieldDescriptions", modelName="Vocab")[1] == "the word"
    assert client.legacy_error("modelFieldRemove", modelName="Vocab", fieldName="Nope") == \
        "field was not found in Vocab: Nope"
    assert client.legacy_error("modelFieldSetFontSize", modelName="Vocab", fieldName="Word",
                               fontSize="big") == "fontSize should be an integer: big"


def test_cloze_model(client):
    client.legacy("createModel", modelName="MyCloze", inOrderFields=["Text"], isCloze=True,
                  cardTemplates=[{"Front": "{{cloze:Text}}", "Back": "{{cloze:Text}}"}])
    nid = client.legacy("addNote", note={"deckName": "Default", "modelName": "MyCloze",
                                         "fields": {"Text": "{{c1::a}} {{c2::b}}"}})
    assert len(client.legacy("notesInfo", notes=[nid])[0]["cards"]) == 2


def test_media(client, tmp_path):
    assert client.legacy("storeMediaFile", filename="hello.txt", data=b64(b"Hello!")) == "hello.txt"
    assert client.legacy("retrieveMediaFile", filename="hello.txt") == b64(b"Hello!")
    assert client.legacy("retrieveMediaFile", filename="missing.txt") is False
    # Same name, new bytes: replaced by default; renamed when deleteExisting is false.
    assert client.legacy("storeMediaFile", filename="hello.txt", data=b64(b"Hi")) == "hello.txt"
    assert client.legacy("retrieveMediaFile", filename="hello.txt") == b64(b"Hi")
    renamed = client.legacy("storeMediaFile", filename="hello.txt", data=b64(b"Other"), deleteExisting=False)
    assert renamed != "hello.txt" and renamed.startswith("hello")
    # Full paths are reduced to their basename (GSM sends paths).
    assert client.legacy("storeMediaFile", filename="/tmp/dir/pic.png", data=b64(b"p")) == "pic.png"
    import hashlib
    digest = hashlib.md5(b"skip me").hexdigest()
    assert client.legacy("storeMediaFile", filename="skip.txt", data=b64(b"skip me"), skipHash=digest) is None
    source = tmp_path / "from_path.txt"
    source.write_text("path")
    assert client.legacy("storeMediaFile", filename="from_path.txt", path=str(source)) == "from_path.txt"
    names = client.legacy("getMediaFilesNames", pattern="hello*")
    assert "hello.txt" in names and renamed in names
    assert client.legacy("getMediaDirPath").endswith("collection.media")
    assert client.legacy("deleteMediaFile", filename="hello.txt") is None
    assert client.legacy("deleteMediaFile", filename="hello.txt") is None
    assert client.legacy("retrieveMediaFile", filename="hello.txt") is False
    assert "data" in client.legacy_error("storeMediaFile", filename="x.txt")


def test_media_http(client):
    client.legacy("storeMediaFile", filename="clip.mp3", data=b64(bytes(range(256)) * 4))
    status, body, headers = client.raw("/media/clip.mp3", None, method="GET")
    assert status == 200 and len(body) == 1024 and headers["Content-Type"] == "audio/mpeg"
    status, body, headers = client.raw("/media/clip.mp3", None, method="GET", headers={"Range": "bytes=10-19"})
    assert status == 206 and body == bytes(range(10, 20)) and headers["Content-Range"] == "bytes 10-19/1024"
    assert client.raw("/media/missing.mp3", None, method="GET")[0] == 404
    assert client.raw("/media/..%2Fcollection.anki2", None, method="GET")[0] == 404
