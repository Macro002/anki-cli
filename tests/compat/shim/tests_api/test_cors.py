from plugin.protocol import Deferred
def response_parts(response):
    raw = response.value if isinstance(response, Deferred) else response
    head, body = raw.split(b'\r\n\r\n', 1)
    lines = head.split(b'\r\n')
    headers = {}
    for line in lines[1:]:
        k, v = line.split(b': ', 1)
        # Normalise header names to Anki-Connect's capitalisation.
        headers[b'-'.join(part.capitalize() for part in k.split(b'-'))] = v
    assert int(headers[b'Content-Length']) == len(body)
    return lines[0], headers, body
