import os
DEFAULT_CONFIG = {
    'apiKey': None, 'apiLogPath': None, 'apiPollInterval': 25, 'apiVersion': 6, 'webBacklog': 5,
    'webBindAddress': '127.0.0.1', 'webBindPort': 8765, 'webCorsOrigin': None,
    'webCorsOriginList': ['http://localhost'], 'ignoreOriginList': [], 'webTimeout': 10000,
}
def setting(key):
    return DEFAULT_CONFIG[key]
