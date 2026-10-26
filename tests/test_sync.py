"""End-to-end sync against Anki's official self-hosted sync server (same protocol as AnkiWeb)."""
import os
import socket
import subprocess
import sys
import time

import pytest

from conftest import RpcFailure, b64


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def sync_server(tmp_path):
    port = free_port()
    env = {**os.environ, "SYNC_USER1": "learner:secret-pass", "SYNC_BASE": str(tmp_path / "sync"),
           "SYNC_HOST": "127.0.0.1", "SYNC_PORT": str(port), "RUST_LOG": "error"}
    process = subprocess.Popen([sys.executable, "-m", "anki.syncserver"], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        raise RuntimeError(process.stderr.read().decode())
    yield f"http://127.0.0.1:{port}/"
    process.terminate()
    process.wait(10)


def test_full_and_incremental_sync_between_two_profiles(client, sync_server):
    client.rpc("profiles.create", name="Laptop")
    login = {"username": "learner", "password": "secret-pass", "endpoint": sync_server}
    with pytest.raises(RpcFailure) as failure:
        client.rpc("sync.login", **{**login, "password": "wrong"})
    assert failure.value.kind == "authenticationRequired"
    for profile in ("User 1", "Laptop"):
        assert client.rpc("sync.login", profile=profile, **login)["username"] == "learner"
        assert client.rpc("sync.account", profile=profile)["loggedIn"] is True

    # Desktop: some notes and a media file, then the first sync uploads everything.
    client.rpc("decks.create", name="Synced")
    note = client.rpc("notes.create", noteType={"name": "Basic"}, deck={"name": "Synced"},
                      fields={"Front": "sync me", "Back": '<img src="pic.png">'})
    client.operation("media.store", filename="pic.png", source={"data": b64(b"picture bytes")})
    first = client.rpc("sync.run")
    assert first["collectionComplete"] and first["outcome"] == "uploaded" and first["mediaComplete"]

    # Laptop is empty: its first sync downloads the collection and media.
    laptop = client.rpc("sync.run", profile="Laptop")
    assert laptop["outcome"] == "downloaded" and laptop["mediaComplete"]
    assert client.rpc("notes.search", profile="Laptop", query="sync me")["ids"] == [note["noteId"]]
    assert client.rpc("media.get", profile="Laptop", filename="pic.png")["data"] == b64(b"picture bytes")

    # Changes on the laptop come back with a normal (incremental) sync.
    client.rpc("notes.update", profile="Laptop", id=note["noteId"], patch={"fields": {"Front": "edited on laptop"}})
    added = client.rpc("notes.create", profile="Laptop", noteType={"name": "Basic"}, deck={"name": "Synced"},
                       fields={"Front": "laptop note"})
    assert client.rpc("sync.run", profile="Laptop")["outcome"] == "synced"
    assert client.rpc("sync.run")["outcome"] == "synced"
    assert client.rpc("notes.get", id=note["noteId"])["fields"]["Front"] == "edited on laptop"
    assert client.rpc("notes.get", id=added["noteId"])
    assert client.rpc("sync.run")["outcome"] == "synced"

    # A schema change (new field) needs a full sync; anki-cli never picks a side silently.
    client.rpc("noteTypes.editStructure", noteType={"name": "Basic"},
               edits=[{"op": "addField", "field": {"name": "Notes"}}])
    pending = client.rpc("sync.run")
    assert pending["outcome"] == "fullSyncRequired" and not pending["collectionComplete"]
    assert client.rpc("sync.run", mode="upload")["collectionComplete"]
    assert client.rpc("sync.run", profile="Laptop", mode="download")["collectionComplete"]
    fields = [f["name"] for f in client.rpc("noteTypes.get", profile="Laptop", noteType={"name": "Basic"})["fields"]]
    assert fields == ["Front", "Back", "Notes"]

    # The legacy action uses the stored login too.
    assert client.legacy("sync") is None
    client.rpc("sync.logout")
    assert client.legacy_error("sync") == "sync: auth not configured"
