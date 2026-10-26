import json, os
SCHEMA = json.load(open(os.path.join(os.path.dirname(__file__), '..', 'api-v1.schema.json')))
