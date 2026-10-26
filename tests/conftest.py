import base64
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from ankicli.app import App
from ankicli.host import HostOptions
from ankicli.profiles import Profiles
from ankicli.server import Server


class Client:
    def __init__(self, url: str, key: str | None = None):
        self.url = url
        self.key = key

    def raw(self, path: str, body: bytes | None, method: str = "POST", headers: dict | None = None):
        request = urllib.request.Request(self.url + path, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code, error.read(), dict(error.headers)

    def request(self, payload, path: str = "/") -> dict:
        status, body, _ = self.raw(path, json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        assert status == 200, (status, body)
        return json.loads(body)

    def envelope(self, action: str, version: int = 6, **params):
        body = {"action": action, "version": version, "params": params}
        if self.key is not None:
            body["key"] = self.key
        return self.request(body)

    def legacy(self, action: str, **params):
        reply = self.envelope(action, **params)
        if reply["error"] is not None:
            raise LegacyFailure(reply["error"])
        return reply["result"]

    def legacy_error(self, action: str, **params) -> str:
        reply = self.envelope(action, **params)
        assert reply["error"] is not None, f"expected {action} to fail, got {reply['result']!r}"
        return reply["error"]

    def rpc_raw(self, method: str, profile: str | None = None, **params) -> dict:
        path = f"/profiles/{urllib.parse.quote(profile)}/api/v1" if profile else "/api/v1"
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        status, body, _ = self.raw(path, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                     "params": params}).encode(), headers=headers)
        assert status == 200, (status, body)
        return json.loads(body)

    def rpc(self, method: str, profile: str | None = None, **params):
        reply = self.rpc_raw(method, profile, **params)
        if "error" in reply:
            raise RpcFailure(reply["error"])
        return reply["result"]

    def rpc_error(self, method: str, **params) -> dict:
        reply = self.rpc_raw(method, **params)
        assert "error" in reply, f"expected {method} to fail, got {reply.get('result')!r}"
        return reply["error"]

    def operation(self, method: str, **params):
        handle = self.rpc(method, **params)
        record = self.rpc("operations.get", operationId=handle["operationId"])
        if record["state"] != "succeeded":
            raise RpcFailure(record["error"])
        return record["result"]


class LegacyFailure(Exception):
    pass


class RpcFailure(Exception):
    def __init__(self, error):
        super().__init__(error["message"])
        self.error = error
        self.kind = error.get("data", {}).get("type")


def start(base, **app_options):
    profiles = Profiles(base, options=HostOptions(backup_minutes=0))
    app = App(profiles, **app_options)
    server = Server(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return app, server, f"http://127.0.0.1:{server.server_address[1]}"


def stop(app, server):
    server.shutdown()
    server.server_close()
    app.close()


@pytest.fixture
def server(tmp_path):
    app, srv, url = start(tmp_path / "base")
    yield Client(url), app
    stop(app, srv)


@pytest.fixture
def client(server):
    return server[0]


@pytest.fixture
def basic(client):
    """A deck with three Basic notes."""
    client.legacy("createDeck", deck="Test")
    ids = [client.legacy("addNote", note={"deckName": "Test", "modelName": "Basic",
                                          "fields": {"Front": front, "Back": back}, "tags": ["t"]})
           for front, back in (("chat", "cat"), ("chien", "dog"), ("oiseau", "bird"))]
    return ids


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
