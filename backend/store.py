import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from pymongo import MongoClient
from pymongo.write_concern import WriteConcern

ROOT = Path(__file__).resolve().parent.parent
MEDIA = Path(os.getenv('MEDIA_ROOT', '/data/media'))
client = MongoClient(os.getenv('MONGO_URL', 'mongodb://mongo:27017'), serverSelectionTimeoutMS=3000)
db = client.get_database('posture_app', write_concern=WriteConcern(w=1, j=True))


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def uid(prefix):
    import uuid
    return f'{prefix}-{uuid.uuid4().hex}'


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k != '_id'}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def initialize():
    for attempt in range(30):
        try:
            client.admin.command('ping')
            break
        except Exception:
            if attempt == 29:
                raise
            time.sleep(1)
    for collection, keys, options in [
        ('inbox', [('payload.source_id', 1), ('payload.boot_id', 1), ('payload.sequence', 1)], {'unique': True}),
        ('inbox', [('session_id', 1), ('observed_at', 1)], {}),
        ('inbox', [('pending', 1), ('retry_at', 1)], {}),
        ('results', [('session_id', 1), ('observed_at', 1)], {}),
        ('results', [('cell_id', 1), ('observed_at', -1)], {}),
        ('events', [('session_id', 1), ('observed_at', 1)], {}),
        ('profiles', [('profile_id', 1), ('revision', -1)], {'unique': True}),
        ('sessions', [('started_at', -1)], {}),
        ('frames', [('session_id', 1), ('captured_at', 1)], {}),
        ('assessments', [('session_id', 1)], {}),
        ('auth_sessions', [('expires_at', 1)], {'expireAfterSeconds': 0}),
    ]:
        db[collection].create_index(keys, **options)
    if not db.config.find_one({'_id': 'ergonomics'}):
        context = json.loads((ROOT / 'examples/task-context.provisional.json').read_text())
        db.config.insert_one({'_id': 'ergonomics', 'value': context, 'updated_at': now()})
    db.cells.update_one({'_id': 'cell-lab-01'}, {'$setOnInsert': {
        'cell_id': 'cell-lab-01', 'name': 'Célula POSTURE', 'operator_id': None,
        'session_id': None, 'created_at': now()}}, upsert=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    from .vision_common import initialize_vision
    initialize_vision()
    from .real import initialize_real
    initialize_real()


def task_context():
    return db.config.find_one({'_id': 'ergonomics'})['value']
