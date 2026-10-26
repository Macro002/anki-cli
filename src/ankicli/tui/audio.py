"""Card audio through a system player (mpv, ffplay, afplay or paplay)."""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import threading
from typing import Callable

PLAYERS = [
    ("mpv", ["mpv", "--no-video", "--really-quiet"]),
    ("ffplay", ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ("afplay", ["afplay"]),
    ("paplay", ["paplay"]),
]


def find_player() -> list[str] | None:
    for binary, command in PLAYERS:
        if shutil.which(binary):
            return command
    return None


class Audio:
    def __init__(self, call: Callable, local_media_dir: str | None):
        self.call = call
        self.media_dir = local_media_dir
        self.command = find_player()
        self.cache = tempfile.mkdtemp(prefix="ankicli-audio-")
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self.command is not None

    def path(self, filename: str) -> str | None:
        if self.media_dir:
            local = os.path.join(self.media_dir, filename)
            return local if os.path.isfile(local) else None
        cached = os.path.join(self.cache, filename)
        if not os.path.exists(cached):
            try:
                data = self.call("media.get", filename=filename)["data"]
            except Exception:  # noqa: BLE001 - a missing file just isn't played
                return None
            with open(cached, "wb") as file:
                file.write(base64.b64decode(data))
        return cached

    def stop(self) -> None:
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self.process = None

    def play(self, filenames: list[str]) -> None:
        """Play files one after another in the background (replacing what's playing)."""
        if not self.command or not filenames:
            return
        self.stop()

        def run() -> None:
            for name in filenames:
                path = self.path(name)
                if path is None:
                    continue
                with self.lock:
                    self.process = subprocess.Popen(self.command + [path], stdout=subprocess.DEVNULL,
                                                    stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                    process = self.process
                process.wait()
                with self.lock:
                    if self.process is not process:  # stopped or replaced
                        return
        threading.Thread(target=run, daemon=True).start()
