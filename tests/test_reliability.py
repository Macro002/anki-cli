"""Concurrency, crash durability and clean shutdown."""
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import Client

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX signals")


def test_concurrent_mixed_clients(client):
    """32 threads adding, reading and searching at once: nothing lost, nothing duplicated."""
    client.legacy("createDeck", deck="Load")
    errors: list = []

    def worker(index: int) -> list[int]:
        local = Client(client.url)
        ids = []
        try:
            for step in range(15):
                ids.append(local.legacy("addNote", note={"deckName": "Load", "modelName": "Basic",
                                                         "fields": {"Front": f"w{index}-{step}", "Back": "b"}}))
                local.legacy("findNotes", query="deck:Load")
                local.rpc("decks.getCounts", deck={"name": "Load"})
                local.legacy("notesInfo", notes=ids[-1:])
        except Exception as error:  # noqa: BLE001
            errors.append(error)
        return ids

    with ThreadPoolExecutor(32) as pool:
        created = [nid for ids in pool.map(worker, range(32)) for nid in ids]
    assert not errors
    assert len(created) == len(set(created)) == 32 * 15
    assert sorted(client.legacy("findNotes", query="deck:Load")) == sorted(created)
    assert client.operation("collection.checkIntegrity")["problems"] == []


def test_profiles_are_served_in_parallel(client):
    """Two collections in one process: calls to one don't wait for the other."""
    client.rpc("profiles.create", name="Other")
    errors: list = []

    def work(profile: str) -> None:
        local = Client(client.url)
        try:
            for i in range(40):
                local.rpc("notes.create", profile=profile, noteType={"name": "Basic"}, deck={"name": "Default"},
                          fields={"Front": f"{profile}-{i}"})
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work, args=(name,)) for name in ("User 1", "Other")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    for name in ("User 1", "Other"):
        ids = client.rpc("notes.search", profile=name, query="", limit=1000)["ids"]
        assert len(ids) == 40


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(base, port: int) -> subprocess.Popen:
    process = subprocess.Popen([sys.executable, "-m", "ankicli", "serve", "--base", str(base), "--port", str(port),
                                "--backup-minutes", "0", "--log-level", "warning"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1):
                return process
        except OSError:
            time.sleep(0.1)
    process.kill()
    raise RuntimeError(process.stderr.read().decode())


@POSIX
def test_kill_9_keeps_every_acknowledged_write(tmp_path):
    """SIGKILL in the middle of a write stream: every acknowledged note survives,
    and the database passes SQLite's integrity check."""
    base, port = tmp_path / "base", free_port()
    process = start_server(base, port)
    remote = Client(f"http://127.0.0.1:{port}")
    acknowledged: list[int] = []
    stop = threading.Event()

    def writer() -> None:
        local = Client(remote.url)
        index = 0
        while not stop.is_set():
            try:
                nid = local.legacy("addNote", note={"deckName": "Default", "modelName": "Basic",
                                                    "fields": {"Front": f"durable {index}", "Back": "x"}})
                acknowledged.append(nid)
                index += 1
            except Exception:  # noqa: BLE001 - the server is being killed
                return

    threads = [threading.Thread(target=writer) for _ in range(4)]
    for thread in threads:
        thread.start()
    time.sleep(2.0)
    os.kill(process.pid, signal.SIGKILL)
    process.wait(10)
    stop.set()
    for thread in threads:
        thread.join(10)
    assert len(acknowledged) > 50

    collection = base / "User 1" / "collection.anki2"
    con = sqlite3.connect(collection)
    # Anki's indexes use its "unicase" collation; register an equivalent to check them.
    con.create_collation("unicase", lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
    assert con.execute("pragma integrity_check").fetchone()[0] == "ok"
    con.close()

    process = start_server(base, port)
    try:
        stored = set(remote.legacy("findNotes", query="durable"))
        assert set(acknowledged) <= stored
        assert remote.operation("collection.checkIntegrity")["problems"] == []
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(30)


@POSIX
def test_sigterm_closes_cleanly(tmp_path):
    base, port = tmp_path / "base", free_port()
    process = start_server(base, port)
    remote = Client(f"http://127.0.0.1:{port}")
    remote.legacy("addNote", note={"deckName": "Default", "modelName": "Basic", "fields": {"Front": "bye"}})
    process.send_signal(signal.SIGTERM)
    assert process.wait(30) == 0
    collection = base / "User 1" / "collection.anki2"
    # Closed cleanly: no write-ahead log is left behind, and Anki opens it at once.
    assert not (collection.parent / "collection.anki2-wal").exists() or \
        (collection.parent / "collection.anki2-wal").stat().st_size == 0
    from anki.collection import Collection
    col = Collection(str(collection))
    try:
        assert col.find_notes("bye")
    finally:
        col.close()


def test_collection_locked_by_another_process(tmp_path):
    """A collection open elsewhere (Anki Desktop, another anki-cli) gives a clear error."""
    from anki.collection import Collection
    from conftest import start, stop
    path = tmp_path / "base" / "User 1"
    path.mkdir(parents=True)
    holder = subprocess.Popen([sys.executable, "-c",
                               "import sys, time\nfrom anki.collection import Collection\n"
                               f"c = Collection({str(path / 'collection.anki2')!r})\nprint('ready', flush=True)\n"
                               "time.sleep(30)"], stdout=subprocess.PIPE)
    assert holder.stdout.readline().strip() == b"ready"
    app, srv, url = start(tmp_path / "base")
    try:
        reply = Client(url).envelope("deckNames")
        assert "open in another program" in reply["error"]
    finally:
        holder.kill()
        holder.wait()
        stop(app, srv)


def test_large_batch_and_body_limits(client):
    notes = [{"deckName": "Default", "modelName": "Basic", "fields": {"Front": f"bulk {i}"}} for i in range(1000)]
    started = time.time()
    ids = client.legacy("addNotes", notes=notes)
    assert len(ids) == 1000 and time.time() - started < 30
    # An oversized body is refused from its Content-Length, before it is read.
    host, port = client.url.split("//")[1].split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(b"POST /api/v1 HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                     b"Content-Length: 17825792\r\n\r\n")
        assert sock.recv(1024).startswith(b"HTTP/1.1 413")
