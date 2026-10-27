"""Anki's own web pages (Statistics, Deck Options, Card Info) served from an aqt wheel."""
from __future__ import annotations

import base64
import hashlib
import re
import zipfile

import pytest

from ankicli import pages
from conftest import Client, start, stop

PREFIX = "_aqt/data/web/sveltekit/"
INLINE = '\n\t\t\t\t{\n\t\t\t\t\t__sveltekit_x = {\n\t\t\t\t\t\tbase: ""\n\t\t\t\t\t};\n' \
         '\t\t\t\t\timport("/_app/immutable/entry/start.abc.mjs");\n\t\t\t\t}\n\t\t\t'
INDEX = f"""<!doctype html>
<html lang="en">
\t<head>
\t\t<meta charset="utf-8" />
\t\t<link rel="icon" href="/favicon.ico" />
\t\t<meta http-equiv="content-security-policy" content="script-src 'self' 'sha256-old='">
\t\t<link rel="preload" as="script" crossorigin="anonymous" href="/_app/immutable/entry/start.abc.mjs">
\t</head>
\t<body><div style="display: contents"><script>{INLINE}</script></div></body>
</html>"""


@pytest.fixture
def wheel(tmp_path, monkeypatch):
    """A stand-in for the aqt wheel with the same layout as the real one."""
    monkeypatch.setenv("ANKICLI_PAGES_DIR", str(tmp_path / "pages"))
    path = tmp_path / "aqt-0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(PREFIX + "index.html", INDEX)
        archive.writestr(PREFIX + "_app/immutable/entry/start.abc.mjs", 'import "../chunks/api.mjs";')
        archive.writestr(PREFIX + "_app/immutable/chunks/api.mjs",
                         "async function d(n){const l=`/_anki/${n}`;return fetch(l)}")
        archive.writestr(PREFIX + "_app/version.json", '{"version":"1"}')
        archive.writestr("aqt/__init__.py", "")
    pages.install(path)
    return path


@pytest.fixture
def keyed(tmp_path, wheel):
    app, server, url = start(tmp_path / "base", api_key="secret")
    yield Client(url, key="secret"), app
    stop(app, server)


def call(client: Client, method: str, message, profile: str | None = None, headers: dict | None = None):
    path = (f"/profiles/{profile}" if profile else "") + f"/pages/_anki/{method}"
    sent = {"Content-Type": "application/binary", "Authorization": "Bearer secret"}
    sent.update(headers or {})
    return client.raw(path, message.SerializeToString(), headers=sent)


def test_install_rejects_a_wheel_without_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("ANKICLI_PAGES_DIR", str(tmp_path / "pages"))
    path = tmp_path / "other.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("aqt/__init__.py", "")
    with pytest.raises(Exception, match="doesn't contain"):
        pages.install(path)
    assert not pages.installed()


def test_pages_need_the_key_and_trade_it_for_a_cookie(keyed):
    client, _ = keyed
    status, _, _ = client.raw("/pages/graphs", None, method="GET")
    assert status == 401
    status, body, headers = client.raw("/pages/graphs?key=secret", None, method="GET")
    assert status == 200 and body.startswith(b"<!doctype html>")
    cookie = headers["Set-Cookie"].split(";")[0]
    assert cookie == "ankicli_pages=secret"
    status, _, _ = client.raw("/pages/_app/version.json", None, method="GET", headers={"Cookie": cookie})
    assert status == 200
    status, _, _ = client.raw("/pages/_app/version.json", None, method="GET",
                              headers={"Cookie": "ankicli_pages=wrong"})
    assert status == 401


def test_index_is_rewritten_for_its_prefix(keyed):
    client, _ = keyed
    status, body, _ = client.raw("/profiles/User%201/pages/deck-options/1?key=secret", None, method="GET")
    assert status == 200
    html = body.decode()
    prefix = "/profiles/User%201/pages"
    assert f'href="{prefix}/_app/immutable/entry/start.abc.mjs"' in html
    assert f'import("{prefix}/_app/immutable/entry/start.abc.mjs")' in html
    assert f'base: "{prefix}"' in html
    assert f'<script src="{prefix}/_ankicli/bridge.js"></script>' in html
    assert "sha256-old=" not in html and "/favicon.ico" not in html
    # The new CSP allows exactly the rewritten inline script.
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert f"script-src 'self' 'sha256-{digest}'" in html
    # A reverse proxy can announce where it mounted the pages.
    status, body, _ = client.raw("/pages/graphs?key=secret", None, method="GET",
                                 headers={"X-Forwarded-Prefix": "/anki/pages/"})
    assert b'base: "/anki/pages"' in body
    status, body, _ = client.raw("/pages/graphs?key=secret", None, method="GET",
                                 headers={"X-Forwarded-Prefix": '/x"><script>'})
    assert b'base: "/pages"' in body


def test_assets(keyed):
    client, _ = keyed
    auth = {"Authorization": "Bearer secret"}
    status, body, headers = client.raw("/pages/_app/immutable/entry/start.abc.mjs", None, method="GET", headers=auth)
    assert status == 200 and headers["Content-Type"] == "text/javascript"
    assert "immutable" in headers["Cache-Control"]
    status, body, _ = client.raw("/profiles/p/pages/_app/immutable/chunks/api.mjs", None, method="GET", headers=auth)
    assert body == b"async function d(n){const l=`/profiles/p/pages/_anki/${n}`;return fetch(l)}"
    status, body, _ = client.raw("/pages/_ankicli/bridge.js", None, method="GET", headers=auth)
    assert b"bridgeCommand" in body and b"deckOptionsSaved" in body
    for path in ("/pages/_app/../../../etc/passwd", "/pages/_app/%2e%2e/%2e%2e/index.html", "/pages/other",
                 "/pages/_app/missing.mjs"):
        status, _, _ = client.raw(path, None, method="GET", headers=auth)
        assert status == 404, path


def test_backend_calls(keyed):
    from anki import deck_config_pb2, decks_pb2, stats_pb2

    client, _ = keyed
    client.rpc("decks.create", name="French")
    status, body, _ = call(client, "graphs", stats_pb2.GraphsRequest(search="", days=30))
    assert status == 200
    stats_pb2.GraphsResponse.FromString(body)
    status, body, _ = call(client, "getDeckConfigsForUpdate", decks_pb2.DeckId(did=1))
    assert status == 200
    configs = deck_config_pb2.DeckConfigsForUpdate.FromString(body)
    assert configs.all_config[0].config.name == "Default"
    # Window plumbing is acknowledged with no content; unknown methods aren't exposed.
    status, body, _ = call(client, "deckOptionsReady", decks_pb2.DeckId())
    assert status == 204
    status, _, _ = call(client, "closeAddCards", decks_pb2.DeckId())
    assert status == 404
    status, _, _ = call(client, "graphs", stats_pb2.GraphsRequest(), headers={"Content-Type": "text/plain"})
    assert status == 403


def test_cookie_calls_must_be_same_origin(keyed):
    from anki import stats_pb2

    client, _ = keyed
    host = client.url.split("//", 1)[1]
    cookie = {"Authorization": "", "Cookie": "ankicli_pages=secret"}
    status, _, _ = call(client, "graphs", stats_pb2.GraphsRequest(), headers={**cookie, "Origin": f"http://{host}"})
    assert status == 200
    status, _, _ = call(client, "graphs", stats_pb2.GraphsRequest(), headers={**cookie, "Origin": "https://evil.example"})
    assert status == 401


def test_settings_and_deck_selection(keyed):
    from anki import frontend_pb2, generic_pb2

    client, _ = keyed
    deck = client.rpc("decks.create", name="Spanish")
    status, _, _ = client.raw(f"/pages/graphs?key=secret&deck={deck['id']}", None, method="GET")
    assert status == 200
    assert client.rpc("config.get", key="curDeck") == int(deck["id"])
    status, _, _ = client.raw("/pages/graphs?key=secret&deck=999", None, method="GET")
    assert status == 404
    status, _, _ = call(client, "setConfigJson", frontend_pb2.SetSettingJsonRequest(key="ankicliTest", value_json=b"[1]"))
    assert status == 204
    status, body, _ = call(client, "getConfigJson", generic_pb2.String(val="ankicliTest"))
    assert generic_pb2.Json.FromString(body).json == b"[1]"
    # Desktop profile settings have nowhere to live; they're remembered per server run.
    status, body, _ = call(client, "getProfileConfigJson", generic_pb2.String(val="anything"))
    assert generic_pb2.Json.FromString(body).json == b"null"
