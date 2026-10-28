"""Shared laboratory storage and contract adapter (no GPU imports in the API)."""
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from .store import db, now, uid, clean, task_context

VISION = Path(os.getenv('VISION_ROOT', '/data/vision'))
EXAMPLES = Path(os.getenv('VISION_EXAMPLES', '/data/examples'))
PROJECT = Path(os.getenv('VISION_PROJECT', '/data/project'))
PRIVATE_PARTS = {'.runtime','.git','backups','data','@eaDir','node_modules','__pycache__','dmulero'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
MAX_VIDEO_BYTES = 2 * 1024**3
MAX_CHUNK_BYTES = 8 * 1024**2
CELL_ID = 'cell-vision-01'
UNASSIGNED = 'operator-vision-unassigned'
TERMINAL = {'completed', 'failed', 'cancelled'}
JOINT_NAMES = ['nose','left_eye_inner','left_eye','left_eye_outer','right_eye_inner','right_eye',
    'right_eye_outer','left_ear','right_ear','mouth_left','mouth_right','left_shoulder','right_shoulder',
    'left_elbow','right_elbow','left_wrist','right_wrist','left_pinky','right_pinky','left_index',
    'right_index','left_thumb','right_thumb','left_hip','right_hip','left_knee','right_knee',
    'left_ankle','right_ankle','left_heel','right_heel','left_foot_index','right_foot_index']
# COCO-WholeBody: body 0:17, feet 17:23, face 23:91, left hand 91:112, right 112:133.
# Unavailable MediaPipe-style eye inner/outer landmarks remain missing, never fabricated.
BODY33 = {'nose':0,'left_eye':1,'right_eye':2,'left_ear':3,'right_ear':4,
    'mouth_left':77,'mouth_right':71,'left_shoulder':5,'right_shoulder':6,
    'left_elbow':7,'right_elbow':8,'left_wrist':9,'right_wrist':10,
    'left_hip':11,'right_hip':12,'left_knee':13,'right_knee':14,'left_ankle':15,'right_ankle':16,
    'left_foot_index':17,'left_heel':19,'right_foot_index':20,'right_heel':22,
    'left_thumb':95,'left_index':99,'left_pinky':111,'right_thumb':116,'right_index':120,'right_pinky':132}


def initialize_vision():
    for name in ('uploads', 'jobs', 'live'):
        (VISION / name).mkdir(parents=True, exist_ok=True)
    db.vision_jobs.create_index([('status', 1), ('created_at', 1)])
    db.vision_results.create_index([('job_id', 1), ('offset_s', 1)], unique=True)
    db.vision_live.create_index([('job_id', 1), ('sequence', 1)], unique=True)
    db.vision_assets.create_index([('created_at', -1)])
    db.cells.update_one({'_id':CELL_ID}, {'$setOnInsert':{'cell_id':CELL_ID,
        'name':'Laboratorio de visión', 'operator_id':None, 'session_id':None, 'created_at':now()}}, upsert=True)
    db.operators.update_one({'_id':UNASSIGNED}, {'$setOnInsert':{'operator_id':UNASSIGNED,
        'display_name':'Laboratorio · sin asignar', 'created_at':now(), 'laboratory':True}}, upsert=True)


def inside(root, relative):
    """Restrict paths including symlinks; never expose arbitrary server files."""
    path = (root / str(relative)).resolve()
    if not path.is_relative_to(root.resolve()):
        raise HTTPException(403, 'La ruta queda fuera de la carpeta habilitada.')
    return path


def get_asset(aid):
    asset = db.vision_assets.find_one({'_id':aid, 'deleted':{'$ne':True}})
    if not asset:
        raise HTTPException(404, 'Vídeo no disponible.')
    return asset


def asset_path(asset):
    return server_path(asset.get('root','examples'),asset['path']) if asset['source']=='server' else inside(VISION,asset['path'])


def server_root(name):
    if name not in ('examples','project'):
        raise HTTPException(422,'Carpeta raíz no admitida.')
    return PROJECT if name=='project' else EXAMPLES


def server_path(root,relative):
    base=server_root(root)
    path=inside(base,relative)
    if any(p in PRIVATE_PARTS or p.startswith('.') for p in path.relative_to(base.resolve()).parts):
        raise HTTPException(403,'La carpeta es privada o está reservada a la aplicación.')
    return path


def public_asset(asset):
    return clean({k:v for k,v in asset.items() if k not in ('path','upload_lock')})


def get_job(jid):
    job = db.vision_jobs.find_one({'_id':jid, 'deleted':{'$ne':True}})
    if not job:
        raise HTTPException(404, 'Análisis no disponible.')
    session = db.sessions.find_one({'_id':job['session_id'], 'deleted':{'$ne':True}})
    if not session:
        raise HTTPException(404, 'La sesión de este análisis se ha eliminado.')
    return job


def options(body):
    try:
        fps = float(body.get('sample_fps', 5))
        confidence = float(body.get('confidence', .5))
        if not math.isfinite(fps) or not 1 <= fps <= 25 or not math.isfinite(confidence) or not .5 <= confidence <= .9:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(422, 'Frecuencia entre 1 y 25 fps; confianza entre 0,5 y 0,9.')
    return {'sample_fps':fps, 'confidence':confidence}


def capture_settings(capture):
    """Save capture intent and future analysis settings without creating any work."""
    if not isinstance(capture, dict) or capture.get('mode') not in ('manual', 'record', 'live'):
        raise HTTPException(422, 'Modo de captura inválido: manual, record o live.')
    body = capture.get('analysis_options', {})
    if not isinstance(body, dict):
        raise HTTPException(422, 'Opciones de captura inválidas.')
    saved = options(body)
    name = body.get('name')
    if name is not None and (not isinstance(name, str) or len(name) > 200):
        raise HTTPException(422, 'Nombre de captura de hasta 200 caracteres.')
    oid = body.get('operator_id')
    if oid is not None and (not isinstance(oid, str) or not 1 <= len(oid) <= 128):
        raise HTTPException(422, 'Operario inválido.')
    saved.update(name=name, operator_id=oid)
    if 'capture_fps' in body:
        fps = body['capture_fps']
        if type(fps) not in (int, float) or not math.isfinite(fps) or not 0 < fps <= 240:
            raise HTTPException(422, 'Frecuencia de cámara inválida.')
        saved['capture_fps'] = fps
    return {'mode': capture['mode'], 'analysis_options': saved}


def create_job(asset, body, actor, context=None, association=None, job_id=None):
    association = association or {}
    if job_id:
        previous = db.vision_jobs.find_one({'_id':job_id})
        if previous:
            return clean(previous)
    body = {**asset.get('capture', {}).get('analysis_options', {}), **body}
    opts = options(body)
    live = body.get('mode') == 'live'
    if asset['status'] != 'ready' and not (live and asset['status']=='uploading'):
        raise HTTPException(409, 'Termina de subir el vídeo antes de analizarlo.')
    oid = body.get('operator_id') or UNASSIGNED
    if not isinstance(oid, str) or not db.operators.find_one({'_id':oid, 'deleted':{'$ne':True}}):
        raise HTTPException(422, 'Operario no disponible.')
    jid = job_id or uid('vision')
    sid, study = ('session-'+jid, 'study-'+jid) if job_id else (uid('session'), uid('study'))
    stamp = now()
    cell = association.get('cell_id', CELL_ID)
    parents = {k:v for k,v in association.items() if k in ('shift_id','iteration_id','origin')}
    name = str(body.get('name') or asset['name'])[:200]
    study_row = {'_id':study, **parents, 'study_id':study, 'name':('Pieza · ' if parents else 'Laboratorio · ')+name,
        'description':'Original de vídeo y pose inferida; acceso de administración.',
        'created_at':stamp, 'created_by':actor['username'], 'deleted':False, 'vision_job_id':jid}
    db.studies.update_one({'_id':study},{'$setOnInsert':study_row},upsert=True)
    session_row = {'_id':sid, **parents, 'session_id':sid, 'operator_id':oid, 'cell_id':cell,
        'study_id':study, 'name':name, 'condition':'vision_laboratory', 'started_at':stamp,
        'status':'active', 'ended_at':None, 'synthetic':False, 'initial_profile_revision':None,
        'deleted':False, 'source':'vision', 'vision_job_id':jid, 'time_basis':'relative_video'}
    if parents:
        session_row.update(condition='real_iteration_analysis',started_at=association['recording_started_at'])
    db.sessions.update_one({'_id':sid},{'$setOnInsert':session_row},upsert=True)
    job = {'_id':jid, **association, 'job_id':jid, 'asset_id':asset['asset_id'], 'session_id':sid,
        'study_id':study, 'operator_id':oid, 'name':name, 'mode':'live' if live else 'file',
        'status':'capturing' if live else 'queued', 'created_at':stamp, 'updated_at':stamp,
        'created_by':actor['username'], 'options':opts, 'context':context if context is not None else task_context(),
        'processed_frames':0, 'evaluable_frames':0, 'progress':0, 'duration_s':None,
        'cancel_requested':False, 'deleted':False, 'error':None, 'stage':'Esperando capturas' if live else 'En cola',
        'estimator':'RTMW-x · cuerpo, cara y manos (133 puntos)', 'geometry':'projected_2d',
        'smpl_status':'not_configured', 'selection':'largest_person_then_confidence'}
    capture_fps = body.get('capture_fps')
    if type(capture_fps) in (int,float) and math.isfinite(capture_fps) and 0 < capture_fps <= 240:
        job['source_fps'] = capture_fps
    db.vision_jobs.insert_one(job)
    db.vision_assets.update_one({'_id':asset['asset_id']}, {'$set':{'analysis_requested_at':stamp}})
    return clean(job)


def telemetry(job, sequence, offset, keypoints, scores):
    at = (datetime.fromisoformat(job.get('recording_started_at',job['created_at']).replace('Z','+00:00')) + timedelta(seconds=offset)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    joints = {}
    for name in JOINT_NAMES:
        index = BODY33.get(name)
        confidence = float(scores[index]) if index is not None and index < len(scores) else 0
        p = keypoints[index] if index is not None and index < len(keypoints) else None
        usable = (p is not None and confidence >= job['options']['confidence']
                  and all(math.isfinite(float(v)) for v in p)
                  and 0 <= float(p[0]) < 1920 and 0 <= float(p[1]) < 1080)
        joints[name] = {'status':'detected' if usable else 'missing',
            'confidence':round(max(0,min(1,confidence)),4) if math.isfinite(confidence) else 0,
            'image_xy_px':[round(float(v),2) for v in p] if usable else None, 'point_3d_m':None}
    return {'schema_version':'0.1', 'message_type':'telemetry', 'message_id':f'{job["job_id"]}:{sequence}',
        'source_id':'posture-vision', 'boot_id':job['job_id'], 'sequence':sequence, 'cell_id':job.get('cell_id',CELL_ID),
        'session_id':job['session_id'], 'operator_id':job['operator_id'], 'study_id':job['study_id'],
        'emitted_at':at, 'clock_sync':'unknown', 'robot':None, 'table':None,
        'pose':{'observed_at':at, 'frame_id':f'{job["job_id"]}:{sequence}', 'camera_id':'vision-lab',
            'tracking_id':'foreground-selection', 'cycle_id':None, 'joint_schema':'posture.body33.v1',
            'estimator':{'name':'RTMW-x COCO-WholeBody', 'version':'rtmlib-0.0.16'},
            'image':{'width_px':1920,'height_px':1080,'mirrored':False},
            'calibration_id':None,'space_3d':None,'joints':joints},
        'frame':{'frame_id':f'{job["job_id"]}:{sequence}', 'camera_id':'vision-lab', 'captured_at':at,
            'width_px':1920, 'height_px':1080, 'capture_fps':job.get('source_fps') or 25,
            'retention_mode':'study','content_type':'image/jpeg'}}
