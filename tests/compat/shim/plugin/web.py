"""Bridge Anki-Connect's in-process HTTP handler to a real anki-cli server."""
import http.client
import urllib.parse

class WebRequest:
    def __init__(self, method, headers, body, path=b'/'):
        self.method, self.headers, self.body, self.path = method, headers, body, path

class WebServer:
    def __init__(self, owner):
        self.owner = owner
    def handlerWrapper(self, req):
        self.owner.apply_settings()
        url = urllib.parse.urlsplit(self.owner.url)
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=60)
        headers = {k.decode(): v.decode() for k, v in req.headers.items()}
        method = req.method.decode() if isinstance(req.method, bytes) else req.method
        path = req.path.decode() if isinstance(req.path, bytes) else req.path
        conn.request(method, path, body=req.body if req.body else None, headers=headers)
        response = conn.getresponse()
        body = response.read()
        lines = [f'HTTP/1.1 {response.status} {response.reason}']
        for key, value in response.getheaders():
            lines.append(f'{key}: {value}')
        conn.close()
        return ('\r\n'.join(lines) + '\r\n\r\n').encode() + body

class WebClient:  # not emulated
    def __init__(self, *args, **kwargs):
        raise NotImplementedError('socket-level client not emulated')
