"""Collection media."""
from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import os
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from ..errors import ApiError
from .base import Base

MAX_MEDIA_BYTES = 64 * 1024 * 1024
ILLEGAL = re.compile(r'[][><:"/?*^\\|\0\r\n]')
DOWNLOAD_TIMEOUT = 30


def acquire(source: dict) -> bytes:
    """Read media bytes from ``{"data"}`` (base64), ``{"path"}`` or ``{"url"}``."""
    if source.get("data"):
        try:
            data = base64.b64decode("".join(source["data"].split()), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ApiError("invalidParams", "Media data is not valid base64.") from error
    elif source.get("path"):
        try:
            with open(source["path"], "rb") as file:
                data = file.read(MAX_MEDIA_BYTES + 1)
        except FileNotFoundError as error:
            raise ApiError("notFound", str(error)) from error
        except OSError as error:
            raise ApiError("ioError", str(error)) from error
    elif source.get("url"):
        url = source["url"]
        if not re.match(r"^https?://", url, re.I):
            raise ApiError("invalidParams", "Only http and https URLs are supported.")
        request = urllib.request.Request(url, headers={"User-Agent": "anki-cli"})
        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                data = response.read(MAX_MEDIA_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise ApiError("ioError", f"{url} download failed with return code {error.code}") from error
        except (urllib.error.URLError, OSError) as error:
            raise ApiError("ioError", str(error)) from error
    else:
        raise ApiError("invalidParams", 'You must provide a "data", "path", or "url" field.')
    if len(data) > MAX_MEDIA_BYTES:
        raise ApiError("invalidParams", "Media exceeds the size limit.")
    return data


class Media(Base):
    def media_dir(self) -> Path:
        return Path(self.col.media.dir())

    @staticmethod
    def media_filename(filename: str) -> str:
        if filename in (".", "..") or any(char in filename for char in ("/", "\\", "\0")):
            raise ApiError("invalidParams", "Expected a media file name, not a path.")
        return ILLEGAL.sub("", unicodedata.normalize("NFC", filename))

    def store_bytes(self, filename: str, data: bytes, collision: str = "rename",
                    skip: dict | None = None) -> dict:
        filename = self.media_filename(filename)
        if not filename:
            raise ApiError("invalidParams", "The file name is empty after removing illegal characters.")
        sha = hashlib.sha256(data).hexdigest()
        if skip and hashlib.new(skip["algorithm"], data).hexdigest() == skip["digest"].lower():
            return {"filename": None, "status": "skipped", "sha256": sha}
        path = self.media_dir() / filename
        original: bytes | None = None
        if path.exists():
            if collision == "error":
                raise ApiError("conflict", "A media file with this name exists.")
            if collision == "replace":
                original = path.read_bytes()
                if original == data:
                    return {"filename": filename, "status": "stored", "sha256": sha}
                self.col.media.trash_files([filename])
        try:
            actual = self.col.media.write_data(filename, data)
        except Exception as error:
            if original is not None:
                try:
                    self.col.media.write_data(filename, original)
                except Exception:  # pragma: no cover - best effort restore
                    pass
            raise ApiError("ioError", f"Writing {filename} failed: {error}") from error
        return {"filename": actual, "status": "stored", "sha256": sha}

    def media_store(self, filename: str, source: dict, collision: str = "rename",
                    skipIfHash: dict | None = None) -> dict:
        data = acquire(source)
        return self.store_bytes(filename, data, collision, skipIfHash)

    def media_get(self, filename: str) -> dict:
        filename = self.media_filename(filename)
        path = self.media_dir() / filename
        if not path.is_file():
            raise ApiError("notFound", f"Media file not found: {filename}")
        return {"filename": filename, "data": base64.b64encode(path.read_bytes()).decode("ascii")}

    def media_list(self, pattern: str = "*") -> list[str]:
        self.media_filename(pattern)
        with os.scandir(self.media_dir()) as entries:
            return sorted(entry.name for entry in entries
                          if entry.is_file() and fnmatch.fnmatchcase(entry.name, pattern))

    def media_delete(self, filename: str) -> dict:
        filename = self.media_filename(filename)
        if not (self.media_dir() / filename).is_file():
            raise ApiError("notFound", f"Media file not found: {filename}")
        self.col.media.trash_files([filename])
        return {"changed": True}

    def media_getDirectory(self) -> dict:
        return {"path": str(self.media_dir().absolute())}

    # -- extras ------------------------------------------------------------------------------

    def media_check(self) -> dict:
        """Anki's Check Media: unused files, missing references and renamed files."""
        output = self.col.media.check()
        return {"unused": list(output.unused), "missing": list(output.missing),
                "missingNoteIds": [str(nid) for nid in output.missing_media_notes],
                "haveTrash": output.have_trash, "report": output.report}

    def media_trashUnused(self) -> dict:
        output = self.col.media.check()
        if output.unused:
            self.col.media.trash_files(list(output.unused))
        return {"changedCount": len(output.unused)}

    def media_emptyTrash(self) -> dict:
        self.col.media.empty_trash()
        return {"changed": True}

    def media_restoreTrash(self) -> dict:
        self.col.media.restore_trash()
        return {"changed": True}
