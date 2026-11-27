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
    log = open(os.path.join(os.path.dirname(str(base)) or ".", f"server-{port}.log"), "wb")
    process = subprocess.Popen([sys.executable, "-m", "ankicli", "serve", "--base", str(base), "--port", str(port),
                                "--backup-minutes", "0", "--log-level", "info"],
                               stdout=log, stderr=subprocess.STDOUT)
    process.log_path = log.name
    started = time.time()
    while time.time() - started < 120:
        if process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2):
                return process
        except OSError:
            time.sleep(0.2)
    alive = process.poll() is None
    process.kill()
    process.wait(10)
    log.close()
    with open(process.log_path, encoding="utf-8", errors="replace") as file:
        output = file.read()
    raise RuntimeError(f"server not reachable after {time.time() - started:.1f}s "
                       f"(alive={alive}, exit={process.returncode}):\n{output}")


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


def test_idle_exit_waits_for_the_request_in_flight(tmp_path, monkeypatch):
    """Idle exit never cuts a running request (a long sync, say); the idle clock starts when it ends."""
    from ankicli.app import App
    from ankicli.host import HostOptions
    from ankicli.legacy import Legacy
    from ankicli.profiles import Profiles
    from ankicli.server import serve

    handle = Legacy.handle

    def slow(self, request, profile=None):
        time.sleep(1.5)
        return handle(self, request, profile=profile)

    monkeypatch.setattr(Legacy, "handle", slow)
    app = App(Profiles(tmp_path / "base", options=HostOptions(backup_minutes=0)))
    listener = socket.create_server(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    ready = threading.Event()
    server = threading.Thread(target=serve, args=(app,), kwargs={"ready": ready, "idle_exit": 0.5,
                                                                 "sock": listener})
    server.start()
    assert ready.wait(10)
    started = time.monotonic()
    assert Client(url).legacy("deckNames") == ["Default"]
    replied = time.monotonic()
    assert replied - started >= 1.5 and server.is_alive()
    server.join(10)
    assert not server.is_alive() and time.monotonic() - replied >= 0.5


LAUNCHER = """import os, sys
os.dup2(int(sys.argv[1]), 3)
os.environ.update(LISTEN_FDS="1", LISTEN_PID=str(os.getpid()))
os.execv(sys.executable, [sys.executable, "-m", "ankicli", *sys.argv[2:]])
"""


@POSIX
def test_socket_activation_and_idle_exit(tmp_path):
    """Like systemd: the server takes the listening socket on fd 3, serves it and exits when idle;
    connections made after the exit wait in the socket's backlog for the next instance."""
    listener = socket.create_server(("127.0.0.1", 0))
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"

    def activate() -> subprocess.Popen:
        # --port 1 can't be bound: answering at all proves the passed socket is used.
        return subprocess.Popen([sys.executable, "-c", LAUNCHER, str(listener.fileno()), "serve",
                                 "--base", str(tmp_path / "base"), "--port", "1", "--backup-minutes", "0",
                                 "--idle-exit", "2"], pass_fds=(listener.fileno(),))

    processes = [activate()]
    try:
        assert Client(url).legacy("deckNames") == ["Default"]
        assert Client(url).legacy("deckNames") == ["Default"]
        assert processes[0].wait(30) == 0
        pending = ThreadPoolExecutor(1).submit(Client(url).legacy, "deckNames")
        time.sleep(0.5)
        assert not pending.done()
        processes.append(activate())
        assert pending.result(60) == ["Default"]
        assert processes[1].wait(30) == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()


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
