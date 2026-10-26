"""LunaTranslator's desktop GET-with-body flow, replayed over a real socket."""
import json
import os
import socket
import urllib.parse
from pathlib import Path

from plugin import util
from tests_api.test_lunatranslator import FIELDS, exercise_luna
from tests_api.test_runtime import admitted, native  # noqa: F401


def raw_get(owner, action, **params):
    owner.apply_settings()
    url = urllib.parse.urlsplit(owner.url)
    payload = json.dumps({'action': action, 'version': 6, 'params': params}).encode()
    with socket.create_connection((url.hostname, url.port), timeout=10) as sock:
        sock.sendall(b'GET / HTTP/1.1\r\nHost: 127.0.0.1:8765\r\nContent-Type: application/json\r\n'
                     b'Connection: close\r\nContent-Length: ' + str(len(payload)).encode() + b'\r\n\r\n' + payload)
        response = b''
        while chunk := sock.recv(65536):
            response += chunk
    head, body = response.split(b'\r\n\r\n', 1)
    assert head.startswith(b'HTTP/1.1 200 OK')
    assert b'Content-Length: ' + str(len(body)).encode() in head
    reply = json.loads(body)
    assert set(reply) == {'result', 'error'}
    return reply


def test_luna_desktop_get_flow(admitted, tmp_path):
    owner, service, _, _, _ = admitted
    first, deleted, replacement, source = exercise_luna(lambda a, **p: raw_get(owner, a, **p), tmp_path)
    assert service.col.find_notes('') == sorted([first, replacement])
    model = service.col.models.by_name('modelofluna')
    assert [f['name'] for f in model['flds']] == FIELDS
    assert model['css'] == '.card { color: blue; }'
    assert model['tmpls'][0]['qfmt'] == '{{word}} {{example_sentence}}'
    for id in [first, replacement]:
        note = service.col.get_note(id)
        assert note['word'] == '猫' and set(note.tags) == {'luna', '日本語'} and len(note.card_ids()) == 1
        for kind in ('audio', 'picture', 'video'):
            for entry in source[kind]:
                field = entry['fields'][0]
                name = entry['filename'].lower()
                assert name in os.path.normcase(note[field])
                assert (Path(service.col.media.dir()) / name).read_bytes() == field.encode()


def test_luna_without_key(admitted, monkeypatch):
    owner, service, _, _, _ = admitted
    monkeypatch.setitem(util.DEFAULT_CONFIG, 'apiKey', 'secret')
    assert raw_get(owner, 'createDeck', deck='Unauthorized') == {
        'result': None, 'error': 'valid api key must be provided'}
    assert service.col.decks.id_for_name('Unauthorized') is None
