"""Profiles: named collections in one base folder, each served by its own host.

Layout (compatible with Anki Desktop's data folder)::

    <base>/
      anki-cli.json           anki-cli settings: active profile, sync logins
      <profile>/collection.anki2
      <profile>/collection.media/
      <profile>/backups/

Point ``--base`` at Anki Desktop's folder (e.g. ``~/.local/share/Anki2``) to serve
its profiles while Desktop is closed, or use ``--collection`` for a single file.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

from .errors import ApiError
from .host import CollectionHost, HostOptions

SETTINGS_FILE = "anki-cli.json"
SKIP_DIRS = {"addons21", "logs", "crash", "backups", "__pycache__"}
INVALID_NAME = re.compile(r'[\\/:*?"<>|\0]|^\.|^$')


def default_base() -> Path:
    env = os.environ.get("ANKICLI_BASE")
    if env:
        return Path(env).expanduser()
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(data) / "anki-cli"


class Profiles:
    def __init__(self, base: str | os.PathLike | None = None, *, collection: str | os.PathLike | None = None,
                 options: HostOptions | None = None, create_default: bool = True):
        self.options = options or HostOptions()
        self._lock = threading.RLock()
        self._hosts: dict[str, CollectionHost] = {}
        self.single: Path | None = None
        if collection is not None:
            path = Path(collection).expanduser().absolute()
            if path.is_dir():
                path = path / "collection.anki2"
            self.single = path
            self.base = path.parent
            self._settings_path = path.parent / ("." + path.stem + ".anki-cli.json")
        else:
            self.base = Path(base).expanduser().absolute() if base else default_base()
            self.base.mkdir(parents=True, exist_ok=True)
            self._settings_path = self.base / SETTINGS_FILE
        self.settings = self._load_settings()
        if self.single is None and create_default and not self.names():
            self.create("User 1")
        if self.active is None or self.active not in self.names():
            names = self.names()
            self.settings["active"] = names[0] if names else None
            self._save_settings()

    # -- settings ----------------------------------------------------------------------

    def _load_settings(self) -> dict:
        try:
            with open(self._settings_path, encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        """Atomic write, readable only by the owner (it holds sync keys)."""
        with self._lock:
            directory = self._settings_path.parent
            directory.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".anki-cli.", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    json.dump(self.settings, file, indent=2, sort_keys=True)
                    file.flush()
                    os.fsync(file.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._settings_path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise

    def profile_settings(self, name: str) -> dict:
        with self._lock:
            return self.settings.setdefault("profiles", {}).setdefault(name, {})

    def update_profile_settings(self, name: str, **values: Any) -> None:
        with self._lock:
            entry = self.profile_settings(name)
            for key, value in values.items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
            self._save_settings()

    # -- profiles ----------------------------------------------------------------------

    def names(self) -> list[str]:
        if self.single is not None:
            return [self.single_name]
        names = []
        for entry in sorted(self.base.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir() and entry.name not in SKIP_DIRS and (entry / "collection.anki2").exists():
                names.append(entry.name)
        # Profiles created but not yet opened have no collection file yet.
        for name in self.settings.get("profiles", {}):
            if name not in names and (self.base / name).is_dir():
                names.append(name)
        return names

    @property
    def single_name(self) -> str:
        assert self.single is not None
        parent = self.single.parent.name
        return parent if self.single.name == "collection.anki2" and parent else self.single.stem

    @property
    def active(self) -> str | None:
        return self.settings.get("active")

    def path(self, name: str) -> Path:
        if self.single is not None:
            if name != self.single_name:
                raise ApiError("notFound", f"Profile not found: {name}")
            return self.single
        return self.base / name / "collection.anki2"

    def create(self, name: str) -> None:
        if self.single is not None:
            raise ApiError("unsupportedCapability", "Profiles cannot be created in single-collection mode.")
        name = name.strip()
        if INVALID_NAME.search(name) or name in SKIP_DIRS:
            raise ApiError("invalidParams", f"Invalid profile name: {name!r}")
        with self._lock:
            if name in self.names():
                raise ApiError("conflict", f"Profile already exists: {name}")
            (self.base / name).mkdir(parents=True, exist_ok=True)
            self.profile_settings(name)
            self._save_settings()

    def rename(self, old: str, new: str) -> None:
        if self.single is not None:
            raise ApiError("unsupportedCapability", "Profiles cannot be renamed in single-collection mode.")
        new = new.strip()
        if INVALID_NAME.search(new) or new in SKIP_DIRS:
            raise ApiError("invalidParams", f"Invalid profile name: {new!r}")
        with self._lock:
            if old not in self.names():
                raise ApiError("notFound", f"Profile not found: {old}")
            if new in self.names():
                raise ApiError("conflict", f"Profile already exists: {new}")
            self._release(old)
            (self.base / old).rename(self.base / new)
            profiles = self.settings.setdefault("profiles", {})
            profiles[new] = profiles.pop(old, {})
            if self.active == old:
                self.settings["active"] = new
            self._save_settings()

    def delete(self, name: str) -> None:
        import shutil
        if self.single is not None:
            raise ApiError("unsupportedCapability", "Profiles cannot be deleted in single-collection mode.")
        with self._lock:
            if name not in self.names():
                raise ApiError("notFound", f"Profile not found: {name}")
            if len(self.names()) == 1:
                raise ApiError("conflict", "The last profile cannot be deleted.")
            self._release(name)
            shutil.rmtree(self.base / name)
            self.settings.get("profiles", {}).pop(name, None)
            if self.active == name:
                self.settings["active"] = self.names()[0]
            self._save_settings()

    def switch(self, name: str) -> None:
        with self._lock:
            if name not in self.names():
                raise ApiError("notFound", f"Profile not found: {name}")
            self.settings["active"] = name
            self._save_settings()

    # -- hosts -------------------------------------------------------------------------

    def host(self, name: str | None = None) -> CollectionHost:
        """The host for a profile (default: the active one); opened on first use."""
        with self._lock:
            name = name or self.active
            if name is None:
                raise ApiError("collectionUnavailable", "No profile is active.")
            host = self._hosts.get(name)
            if host is None:
                if name not in self.names():
                    raise ApiError("notFound", f"Profile not found: {name}")
                host = CollectionHost(self.path(name), name, self.options)
                self._hosts[name] = host
            return host

    def open_hosts(self) -> list[CollectionHost]:
        with self._lock:
            return list(self._hosts.values())

    def _release(self, name: str) -> None:
        host = self._hosts.pop(name, None)
        if host is not None:
            host.close()

    def close(self) -> None:
        with self._lock:
            hosts, self._hosts = list(self._hosts.values()), {}
        for host in hosts:
            host.close()
