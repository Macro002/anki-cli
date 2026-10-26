"""Fixtures equivalent to Anki-Connect's, running anki-cli over real HTTP."""
import threading
from types import SimpleNamespace
import pytest
from jsonschema import Draft202012Validator
from plugin import AnkiConnect, _CURRENT, util
from plugin.contract import SCHEMA
from ankicli.app import App
from ankicli.host import HostOptions
from ankicli.profiles import Profiles
from ankicli.server import Server


@pytest.fixture
def native(tmp_path, monkeypatch):
    profiles = Profiles(collection=tmp_path / 'collection.anki2', options=HostOptions(backup_minutes=0))
    app = App(profiles)
    server = Server(('127.0.0.1', 0), app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _CURRENT.update(app=app, url=f'http://127.0.0.1:{server.server_address[1]}')
    host = profiles.host()
    host.run(lambda col: None)
    owner = AnkiConnect()
    owner.apply_settings()
    from ankicli.services import Services
    service = Services(app, host, host.col)
    try:
        yield owner, service
    finally:
        server.shutdown(); server.server_close(); app.close(); _CURRENT.clear()


def call(service, method, **params):
    value = service.app.call(method, params)
    meta = SCHEMA['x-methods'][method]
    if meta['completion'] == 'operation':
        record = service.app.operations.get(value['operationId'])
        if record['state'] != 'succeeded':
            raise AssertionError(record['error'])
        value = record['result']
    validator = Draft202012Validator({**SCHEMA, 'oneOf': [meta.get('operationResult', meta['result'])]})
    errors = list(validator.iter_errors(value))
    if errors:
        leaves = errors[0].context or errors
        pytest.fail('; '.join(str(list(e.path)) + ': ' + e.message for e in leaves))
    return value


@pytest.fixture
def admitted(native, monkeypatch):
    owner, service = native
    def drain():
        pass
    return owner, service, drain, [], ['change']
