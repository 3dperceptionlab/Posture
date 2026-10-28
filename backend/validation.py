import json
import math
from datetime import datetime
from jsonschema import Draft202012Validator, FormatChecker
from fastapi import HTTPException
from .store import ROOT

SCHEMA = json.loads((ROOT/'schemas/messages.schema.json').read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def validate(message):
    # Pick a known branch for readable errors instead of a generic oneOf failure.
    kind = message.get('message_type') if isinstance(message,dict) else None
    if kind not in ('telemetry','event','profile_application','shift_assessment'):
        raise HTTPException(422, 'message_type no reconocido.')
    branch = dict(SCHEMA)
    branch['oneOf'] = [{'$ref':f'#/$defs/{kind}'}]
    errors = sorted(Draft202012Validator(branch, format_checker=FormatChecker()).iter_errors(message), key=lambda e:str(e.path))
    if errors:
        raise HTTPException(422, {'message':'JSON incompatible con el contrato v0.1',
            'errors':[{'path':'/'.join(map(str,e.absolute_path)), 'message':e.message[:500]} for e in errors[:8]]})
    try:
        size=len(json.dumps(message, allow_nan=False).encode())
    except ValueError:
        raise HTTPException(422, 'No se permiten NaN ni infinitos.')
    if size > 256*1024:
        raise HTTPException(413, 'Un mensaje no puede superar 256 KiB.')
    if kind == 'telemetry':
        pose,robot,frame = message.get('pose'),message.get('robot'),message.get('frame')
        if pose and not pose.get('space_3d') and any(j['point_3d_m'] is not None for j in pose['joints'].values()):
            raise HTTPException(422, 'Las coordenadas 3D requieren space_3d.')
        if pose and frame and any((pose['frame_id']!=frame['frame_id'],pose['camera_id']!=frame['camera_id'],pose['observed_at']!=frame['captured_at'])):
            raise HTTPException(422, 'Pose y frame deben corresponder a la misma captura.')
        if robot and robot.get('tcp_pose'):
            q=robot['tcp_pose']['orientation_xyzw']
            if abs(math.sqrt(sum(x*x for x in q))-1)>.001:
                raise HTTPException(422, 'El cuaternión TCP debe estar normalizado.')
    if kind == 'profile_application' and message['status']=='applied':
        if any(message[k]['state']!='applied' or message[k]['applied_revision']!=message['requested_revision'] for k in ('robot','table')):
            raise HTTPException(422, 'La revisión no está confirmada en ambos componentes.')
    return message


def observed_at(message):
    for key in ('observed_at','submitted_at'):
        if message.get(key):
            return message[key]
    values=[message[k]['observed_at'] for k in ('pose','robot','table') if message.get(k)]
    return min(values) if values else message['emitted_at']
