import json

from conftest import start, stop


def test_empty_body_reports_api_version(client):
    status, body, _ = client.raw("/", b"")
    assert status == 200 and json.loads(body) == {"apiVersion": "AnkiConnect v.6"}


def test_version_envelopes(client):
    assert client.request({"action": "deckNames", "version": 6}) == {"result": ["Default"], "error": None}
    # Omitting the version selects version 4: bare results.
    assert client.request({"action": "deckNames"}) == ["Default"]
    assert client.request({"action": "deckNames", "version": "6"})["result"] == ["Default"]
    # Errors keep the envelope at every version.
    assert client.request({"action": "nope"}) == {"result": None, "error": "unsupported action"}


def test_params_normalization(client):
    assert client.request({"action": "deckNames", "version": 6, "params": None})["result"] == ["Default"]
    assert client.request({"action": "deckNames", "version": 6, "params": []})["result"] == ["Default"]
    assert client.request({"action": "deckNames", "version": 6, "params": {"surplus": 1}})["result"] == ["Default"]
    assert client.request({"action": "deckNames", "version": 6, "params": "x"})["error"] == "params must be an object."


def test_missing_parameter_message(client):
    assert client.legacy_error("createDeck") == \
        "AnkiConnect.createDeck() missing 1 required positional argument: 'deck'"
    assert client.legacy_error("changeDeck") == \
        "AnkiConnect.changeDeck() missing 2 required positional arguments: 'cards' and 'deck'"


def test_get_with_json_body(client):
    status, body, _ = client.raw("/", json.dumps({"action": "version", "version": 6}).encode(), method="GET")
    assert status == 200 and json.loads(body) == {"result": 6, "error": None}


def test_multi_preserves_versions_and_errors(client):
    result = client.legacy("multi", actions=[
        {"action": "deckNames", "version": 6},
        {"action": "deckNames"},
        {"action": "missing", "version": 6},
        {"action": "multi", "version": 6, "params": {"actions": [{"action": "version", "version": 6}]}},
    ])
    assert result == [{"result": ["Default"], "error": None}, ["Default"],
                      {"result": None, "error": "unsupported action"},
                      {"result": [{"result": 6, "error": None}], "error": None}]


def test_multi_rejects_exit_before_last(client):
    error = client.legacy_error("multi", actions=[{"action": "guiExitAnki", "version": 6},
                                                  {"action": "deckNames", "version": 6}])
    assert error == "guiExitAnki must be the last executable multi action"


def test_multi_depth_limit(client):
    actions = [{"action": "version", "version": 6}]
    for _ in range(18):
        actions = [{"action": "multi", "version": 6, "params": {"actions": actions}}]
    assert client.legacy_error("multi", actions=actions) == "multi nesting limit exceeded"


def test_api_reflect(client):
    out = client.legacy("apiReflect", scopes=["actions", "invalidType"], actions=["apiReflect", "invalidMethod"])
    assert out == {"scopes": ["actions"], "actions": ["apiReflect"]}
    assert client.legacy("apiReflect") == {"scopes": []}
    assert len(client.legacy("apiReflect", scopes=["actions"])["actions"]) == 122


def test_api_key(tmp_path):
    app, srv, url = start(tmp_path / "keyed", api_key="secret")
    try:
        from conftest import Client
        anonymous = Client(url)
        assert anonymous.envelope("deckNames")["error"] == "valid api key must be provided"
        # Permission discovery is exempt and reports that a key is needed.
        assert anonymous.legacy("requestPermission") == {"permission": "granted", "requireApikey": True, "version": 6}
        assert Client(url, key="secret").legacy("deckNames") == ["Default"]
        assert anonymous.raw("/api/v1", b'{"jsonrpc":"2.0","id":1,"method":"decks.list"}')[0] == 401
    finally:
        stop(app, srv)


def test_origins(client):
    status, _, _ = client.raw("/", b'{"action":"version","version":6}', headers={"Origin": "https://evil.example"})
    assert status == 403
    status, body, headers = client.raw("/", b'{"action":"version","version":6}',
                                       headers={"Origin": "chrome-extension://abcdef"})
    assert status == 200 and headers["Access-Control-Allow-Origin"] == "chrome-extension://abcdef"
    status, body, _ = client.raw("/", b'{"action":"requestPermission","version":6}',
                                 headers={"Origin": "https://evil.example"})
    assert status == 200 and json.loads(body)["result"] == {"permission": "denied"}
    status, _, headers = client.raw("/", None, method="OPTIONS", headers={"Origin": "https://evil.example"})
    assert status == 200


def test_profiles(client):
    assert client.legacy("getProfiles") == ["User 1"]
    assert client.legacy("getActiveProfile") == "User 1"
    assert client.legacy("loadProfile", name="nobody") is False
    client.rpc("profiles.create", name="Second")
    assert client.legacy("loadProfile", name="Second") is True
    assert client.legacy("getActiveProfile") == "Second"
    client.legacy("createDeck", deck="OnlyInSecond")
    assert "OnlyInSecond" not in [d["name"] for d in client.rpc("decks.list", profile="User 1")] and \
        "OnlyInSecond" in [d["name"] for d in client.rpc("decks.list", profile="Second")]
