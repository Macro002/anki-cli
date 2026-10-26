"""Latency, throughput and memory of an anki-cli server.

    python bench/bench.py [--notes 5000]

Starts a server on a fresh collection, fills it, and times common calls over HTTP
(keep-alive, like a real client). Prints a Markdown table.
"""
from __future__ import annotations

import argparse
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from ankicli.client import Client  # noqa: E402


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def rss_mb(pid: int) -> float:
    with open(f"/proc/{pid}/status") as file:
        for line in file:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def timed(fn, repeat: int) -> tuple[float, float]:
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return statistics.median(samples), samples[int(len(samples) * 0.95) - 1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=int, default=5000)
    parser.add_argument("--repeat", type=int, default=200)
    args = parser.parse_args()
    base = tempfile.mkdtemp(prefix="ankicli-bench-")
    port = free_port()
    server = subprocess.Popen([sys.executable, "-m", "ankicli", "serve", "--base", base, "--port", str(port),
                               "--backup-minutes", "0", "--log-level", "warning"])
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                break
            except OSError:
                time.sleep(0.1)
        anki = Client(f"http://127.0.0.1:{port}")
        anki.legacy("createDeck", deck="Bench")
        started = time.perf_counter()
        for chunk in range(0, args.notes, 500):
            anki.legacy("addNotes", notes=[{"deckName": "Bench", "modelName": "Basic",
                                            "fields": {"Front": f"word {i}", "Back": f"meaning {i}"}}
                                           for i in range(chunk, min(args.notes, chunk + 500))])
        fill = time.perf_counter() - started
        cards = anki.legacy("findCards", query="deck:Bench")
        note_ids = anki.legacy("findNotes", query="deck:Bench")[:100]
        anki.legacy("saveDeckConfig", config={"id": 1, "new": {"perDay": 9999}, "rev": {"perDay": 9999}})
        anki.legacy("guiDeckReview", name="Bench")

        def review_step() -> None:
            anki.legacy("guiCurrentCard")
            anki.legacy("guiShowAnswer")
            anki.legacy("guiAnswerCard", ease=4)

        rows = []
        cases = [
            ("version (round trip)", lambda: anki.legacy("version")),
            ("deckNames", lambda: anki.legacy("deckNames")),
            ("getDeckStats", lambda: anki.legacy("getDeckStats", decks=["Bench"])),
            ("findCards (5k matches)", lambda: anki.legacy("findCards", query="deck:Bench")),
            ("cardsInfo (1 card)", lambda: anki.legacy("cardsInfo", cards=cards[:1])),
            ("cardsInfo (50 cards)", lambda: anki.legacy("cardsInfo", cards=cards[:50])),
            ("notesInfo (100 notes)", lambda: anki.legacy("notesInfo", notes=note_ids)),
            ("addNote", lambda: anki.legacy("addNote", note={"deckName": "Bench", "modelName": "Basic",
                                                             "fields": {"Front": f"x{time.perf_counter_ns()}"}})),
            ("canAddNotes (10)", lambda: anki.legacy("canAddNotes", notes=[
                {"deckName": "Bench", "modelName": "Basic", "fields": {"Front": f"word {i}"}} for i in range(10)])),
            ("review step (current+show+answer)", review_step),
            ("decks.tree (v1)", lambda: anki.call("decks.tree")),
        ]
        for name, fn in cases:
            median, p95 = timed(fn, args.repeat if "50" not in name else max(20, args.repeat // 4))
            rows.append((name, median, p95))

        def hammer(_: int) -> int:
            local = Client(f"http://127.0.0.1:{port}")
            count = 0
            deadline = time.perf_counter() + 3
            while time.perf_counter() < deadline:
                local.legacy("getDeckStats", decks=["Bench"])
                count += 1
            return count
        with ThreadPoolExecutor(8) as pool:
            total = sum(pool.map(hammer, range(8)))
        print(f"\nanki-cli benchmark — {args.notes} notes, Python {sys.version.split()[0]}, "
              f"{os.cpu_count()} CPUs\n")
        print("| Call | median | p95 |\n|---|---:|---:|")
        for name, median, p95 in rows:
            print(f"| {name} | {median:.2f} ms | {p95:.2f} ms |")
        print(f"\n* Filling {args.notes} notes with addNotes (500 per call): {fill:.2f} s")
        print(f"* Throughput, 8 concurrent clients (getDeckStats): {total / 3:.0f} requests/s")
        print(f"* Server memory (RSS) with the collection open: {rss_mb(server.pid):.0f} MB")
    finally:
        server.terminate()
        server.wait(30)


if __name__ == "__main__":
    main()
