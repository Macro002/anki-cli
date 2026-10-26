"""AnkiWeb (or self-hosted server) sync."""
from __future__ import annotations

import time

from ..errors import ApiError, from_exception
from .base import Base

REQUIRED = {0: "noChanges", 1: "normalSync", 2: "fullSync", 3: "fullDownload", 4: "fullUpload"}


class Sync(Base):
    def _settings(self) -> dict:
        return self.app.profiles.profile_settings(self.profile)

    def sync_auth(self):
        from anki.sync import SyncAuth
        settings = self._settings()
        if not settings.get("syncKey"):
            raise ApiError("authenticationRequired", "sync: auth not configured")
        return SyncAuth(hkey=settings["syncKey"], endpoint=settings.get("syncEndpoint") or None,
                        io_timeout_secs=settings.get("syncTimeout") or 60)

    def sync_login(self, username: str, password: str, endpoint: str | None = None) -> dict:
        """Log in to AnkiWeb (or a self-hosted server via ``endpoint``) and remember the key."""
        try:
            auth = self.col.sync_login(username=username, password=password, endpoint=endpoint)
        except Exception as error:
            mapped = from_exception(error)
            if mapped.kind in ("authenticationRequired", "ioError"):
                raise mapped
            raise ApiError("authenticationRequired", str(error)) from error
        self.app.profiles.update_profile_settings(self.profile, syncKey=auth.hkey, syncUser=username,
                                                  syncEndpoint=endpoint or auth.endpoint or None)
        return {"username": username, "endpoint": endpoint or auth.endpoint or None}

    def sync_logout(self) -> dict:
        self.app.profiles.update_profile_settings(self.profile, syncKey=None, syncUser=None, syncEndpoint=None)
        return {"changed": True}

    def sync_account(self) -> dict:
        settings = self._settings()
        return {"loggedIn": bool(settings.get("syncKey")), "username": settings.get("syncUser"),
                "endpoint": settings.get("syncEndpoint"), "syncMedia": settings.get("syncMedia", True),
                "lastSync": settings.get("lastSync")}

    def sync_setOptions(self, syncMedia: bool | None = None, timeoutSeconds: int | None = None) -> dict:
        values = {}
        if syncMedia is not None:
            values["syncMedia"] = syncMedia
        if timeoutSeconds is not None:
            values["syncTimeout"] = timeoutSeconds
        self.app.profiles.update_profile_settings(self.profile, **values)
        return self.sync_account()

    def sync_status(self) -> dict:
        auth = self.sync_auth()
        status = self.col.sync_status(auth)
        return {"required": REQUIRED.get(status.required, "normalSync")}

    def _remember_endpoint(self, endpoint: str) -> None:
        if endpoint:
            self.app.profiles.update_profile_settings(self.profile, syncEndpoint=endpoint)

    def wait_media(self, timeout: float = 600) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.col.media_sync_status()
            if not status.active:
                return True
            time.sleep(0.2)
        return False

    def sync_run(self, mode: str = "auto", includeMedia: bool | None = None) -> dict:
        """Sync the collection.

        ``mode``: ``auto`` (a normal sync; when the collection can't be merged it
        reports ``outcome="fullSyncRequired"`` instead of choosing a side), ``upload``
        (full sync keeping this collection) or ``download`` (full sync keeping the
        server's). A first sync with an empty side picks the only safe direction.
        """
        auth = self.sync_auth()
        media = self._settings().get("syncMedia", True) if includeMedia is None else includeMedia
        if mode not in ("auto", "upload", "download"):
            raise ApiError("invalidParams", "mode must be auto, upload or download")
        result = {"outcome": "synced", "fullSync": None, "serverMessage": "", "collectionComplete": False,
                  "mediaComplete": not media}
        server_usn = None
        if mode == "auto":
            output = self.col.sync_collection(auth, False)
            self._remember_endpoint(output.new_endpoint)
            server_usn = output.server_media_usn
            result["serverMessage"] = output.server_message
            required = REQUIRED.get(output.required, "noChanges")
            if required == "fullSync":
                # Both sides changed in ways that can't be merged: never choose silently.
                result.update(outcome="fullSyncRequired", fullSync="either")
                return result
            if required in ("fullDownload", "fullUpload"):
                mode = "download" if required == "fullDownload" else "upload"
            else:
                result["collectionComplete"] = True
        if mode in ("upload", "download"):
            self.col.close_for_full_sync()
            try:
                self.col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=mode == "upload")
            finally:
                self.col.reopen(after_full_sync=True)
            self.after_reopen()  # type: ignore[attr-defined]
            result.update(collectionComplete=True, outcome="uploaded" if mode == "upload" else "downloaded")
        if media:
            try:
                self.col.sync_media(auth)
                result["mediaComplete"] = self.wait_media()
            except Exception as error:  # noqa: BLE001 - the collection sync already succeeded
                result["mediaError"] = str(error)
        self.app.profiles.update_profile_settings(self.profile, lastSync=self.stamp(None))
        return result

    def sync_media(self) -> dict:
        auth = self.sync_auth()
        self.col.sync_media(auth)
        return {"mediaComplete": self.wait_media()}

    def collection_sync(self, includeMedia: bool = True) -> dict:
        """v1 ``collection.sync``: a normal sync; full syncs need ``sync.run`` with a mode."""
        result = self.sync_run("auto", includeMedia)
        if result.get("fullSync"):
            raise ApiError("invalidState", "A full sync is required; call sync.run with mode=upload or "
                                           "mode=download to choose which side to keep.")
        return {"collectionComplete": result["collectionComplete"], "mediaComplete": result["mediaComplete"]}
