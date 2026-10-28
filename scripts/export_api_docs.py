"""Print the portable strict-mode ROS OpenAPI reference to stdout.

From the repository root, after rebuilding the API image:
docker compose exec -T api python - < scripts/export_api_docs.py > docs/ros/openapi.json

This process-local override does not change the running server's authentication.
"""
import copy
import json
import os

os.environ['POSTURE_AUTH_MODE'] = 'strict'

from backend.app import app
from backend.real import router

schema = copy.deepcopy(app.openapi())
paths = {route.path for route in router.routes}
schema['paths'] = {path: item for path, item in schema['paths'].items() if path in paths}
schema['info']['title'] = 'POSTURE Data Processing and Dashboard · HMI / ROS contract 1.0'
schema['servers'] = [{'url': '/', 'description': 'Current deployment origin; configure your server URL in external clients.'}]
print(json.dumps(schema, ensure_ascii=False, indent=2))
