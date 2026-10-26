"""A stand-in for the Anki-Connect add-on object, backed by anki-cli."""
from types import SimpleNamespace
from . import util
from .protocol import Deferred
from .web import WebServer
from ankicli.legacy import Legacy, SIGNATURES, bind, legacy_request

_CURRENT = {}

class AnkiConnect:
    def __init__(self):
        self.app = _CURRENT.get('app')
        self.url = _CURRENT.get('url')
        self.server = WebServer(self)
        owner = self
        class Dispatcher:
            def request(self, payload):
                from ankicli.rpc import Rpc
                return Deferred(Rpc(owner.app).handle(payload))
        self.runtime = SimpleNamespace(tokens={}, cursors={}, exit_requested=False, dispatcher=Dispatcher())
        self._window = SimpleNamespace(_background_op_count=0, pm=SimpleNamespace(sync_auth=lambda: None))
    def apply_settings(self):
        if self.app is not None:
            self.app.api_key = util.setting('apiKey')
            origins = list(util.setting('webCorsOriginList'))
            if util.DEFAULT_CONFIG.get('webCorsOrigin'):
                origins.append(util.DEFAULT_CONFIG['webCorsOrigin'])
            self.app.cors_origins = origins
    def window(self):
        return self._window
    def legacy_actions(self):
        return list(SIGNATURES)
    def handler(self, request):
        self.apply_settings()
        if self.app is None:
            from ankicli.app import App
            from ankicli.profiles import Profiles
            import tempfile
            self.app = App(Profiles(tempfile.mkdtemp()))
            self.apply_settings()
        return Legacy(self.app).handle(request)
    def handler_async(self, request, barrier=False, depth=0):
        return Deferred(self.handler(request))
    def resolve_action(self, name, version, params):
        if name not in SIGNATURES:
            raise Exception('unsupported action')
        return name, bind(name, legacy_request({'action': name, 'params': params})['params'])
