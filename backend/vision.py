"""Authenticated upload, server-file selection and laboratory job API."""
import csv
import hashlib
import io
import json
import math
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image

from . import auth
from .store import db, now, uid, clean
from .vision_common import (VISION, EXAMPLES, VIDEO_EXTENSIONS, MAX_VIDEO_BYTES, MAX_CHUNK_BYTES,
    TERMINAL, PRIVATE_PARTS, server_root, server_path, inside, get_asset, get_job, public_asset, asset_path, create_job, capture_settings)

router = APIRouter(prefix='/api/v1/vision', tags=['Laboratorio de visión'])


@router.get('/status')
def status(request:Request):
    auth.admin(request)
    worker = clean(db.system.find_one({'_id':'vision'})) or {}
    worker['healthy'] = time.time() - worker.get('heartbeat_ts', 0) < 45 and worker.get('status')=='ready'
    host = os.getenv('POSTURE_TLS_HOST','172.19.33.30')
    port = os.getenv('POSTURE_TLS_PORT','8443')
    return {'worker':worker, 'max_video_bytes':MAX_VIDEO_BYTES, 'max_chunk_bytes':MAX_CHUNK_BYTES,
        'https_url':f'https://{host}:{port}/#vision', 'certificate_available':(VISION/'posture-root.crt').is_file(),
        'allowed_extensions':sorted(VIDEO_EXTENSIONS), 'smpl_available':False}


@router.get('/certificate')
def certificate(request:Request):
    auth.admin(request)
    path = VISION/'posture-root.crt'
    if not path.is_file():
        raise HTTPException(404,'Ejecuta ./launch_docker certificate para exportar el certificado público.')
    return FileResponse(path,media_type='application/x-x509-ca-cert',filename='POSTURE-root.crt')


@router.get('/files')
def files(request:Request,path:str='',recursive:bool=False,root:str='examples'):
    auth.admin(request)
    base = server_root(root)
    folder = server_path(root,path)
    if not folder.is_dir():
        raise HTTPException(404,'Carpeta del proyecto no encontrada.')
    entries = []
    def recursive_paths():
        for directory,dirs,names in os.walk(folder,followlinks=False):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in PRIVATE_PARTS and not (Path(directory)/d).is_symlink()]
            for name in names:
                yield Path(directory)/name
    paths = recursive_paths() if recursive else folder.iterdir()
    scanned = 0
    for item in paths:
        scanned += 1
        if scanned > 5000 or len(entries)>=500:
            break
        if item.is_symlink() or item.name.startswith('.') or item.name in PRIVATE_PARTS:
            continue
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS:
            entries.append({'name':item.name,'path':str(item.relative_to(base)),
                'kind':'video','size_bytes':item.stat().st_size})
        elif not recursive and item.is_dir():
            entries.append({'name':item.name,'path':str(item.relative_to(base)),'kind':'folder'})
    return {'root':root,'path':str(folder.relative_to(base)), 'entries':sorted(entries,key=lambda i:(i['kind']!='folder',i['name'].lower())),
        'limited':scanned>5000 or len(entries)>=500}


@router.post('/import',status_code=201)
def import_server(request:Request,body:dict):
    actor = auth.admin(request)
    root = body.get('root','examples')
    base = server_root(root)
    path = server_path(root,body.get('path',''))
    if not path.is_file() or path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(422,'Selecciona un vídeo dentro de la carpeta del proyecto habilitada.')
    if not 0 < path.stat().st_size <= MAX_VIDEO_BYTES:
        raise HTTPException(422,'Vídeo vacío o superior a 2 GiB.')
    # A reference: imports and deletion of analyses never overwrite the source.
    asset = {'_id':uid('video'),'name':path.name,'source':'server','root':root,'path':str(path.relative_to(base)),
        'size_bytes':path.stat().st_size,'uploaded_bytes':path.stat().st_size,'status':'ready',
        'created_at':now(),'created_by':actor['username'],'deleted':False}
    asset['asset_id']=asset['_id']
    db.vision_assets.insert_one(asset)
    return public_asset(asset)


@router.get('/assets')
def assets(request:Request):
    auth.admin(request)
    return [public_asset(a) for a in db.vision_assets.find({'deleted':{'$ne':True},'origin':{'$ne':'real'}}).sort('created_at',-1).limit(200)]


@router.post('/uploads',status_code=201)
def begin_upload(request:Request,body:dict):
    actor = auth.admin(request)
    name = str(body.get('name','')).replace('\\','/').split('/')[-1]
    name = re.sub(r'[^\w. ()-]','_',name,flags=re.UNICODE)[:180]
    if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(422,'Formato de vídeo no admitido.')
    size = body.get('size_bytes')
    if size is not None and (type(size)!=int or not 0 < size <= MAX_VIDEO_BYTES):
        raise HTTPException(422,'Vídeos de hasta 2 GiB.')
    capture = capture_settings(body['capture']) if 'capture' in body else None
    if capture:
        oid = capture['analysis_options']['operator_id']
        if oid and not db.operators.find_one({'_id':oid, 'deleted':{'$ne':True}}):
            raise HTTPException(422,'Operario no disponible.')
    aid = uid('video')
    relative = 'uploads/'+aid+'/'+name
    path = inside(VISION,relative)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.touch(exist_ok=False)
    asset = {'_id':aid, 'asset_id':aid, 'name':name, 'source':'upload', 'path':relative,
        'status':'uploading', 'size_bytes':size, 'uploaded_bytes':0,'upload_lock':0,
        'created_at':now(),'created_by':actor['username'],'deleted':False}
    if capture:
        asset['capture'] = capture
    db.vision_assets.insert_one(asset)
    return public_asset(asset)


@router.put('/uploads/{aid}')
async def upload_chunk(aid:str,request:Request,offset:int=Query(ge=0)):
    auth.admin(request)
    asset = get_asset(aid)
    if asset['source']!='upload' or asset['status']!='uploading':
        raise HTTPException(409,'Este vídeo no admite más bloques.')
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>MAX_CHUNK_BYTES:
            raise HTTPException(413,'Cada bloque está limitado a 8 MiB.')
    if not data or offset+len(data)>MAX_VIDEO_BYTES or (asset.get('size_bytes') is not None and offset+len(data)>asset['size_bytes']):
        raise HTTPException(422,'Bloque vacío o tamaño fuera del límite.')
    lock = time.time()+60
    claim = db.vision_assets.update_one({'_id':aid,'status':'uploading','uploaded_bytes':offset,
        '$or':[{'upload_lock':{'$lt':time.time()}},{'upload_lock':{'$exists':False}}]}, {'$set':{'upload_lock':lock}})
    if not claim.modified_count:
        raise HTTPException(409,{'message':'Desplazamiento incorrecto o subida ocupada.','uploaded_bytes':get_asset(aid)['uploaded_bytes']})
    try:
        with asset_path(asset).open('r+b') as handle:
            handle.seek(offset);handle.write(data);handle.truncate();handle.flush();os.fsync(handle.fileno())
        db.vision_assets.update_one({'_id':aid,'upload_lock':lock},{'$set':{'uploaded_bytes':offset+len(data),'upload_lock':0}})
    except Exception:
        db.vision_assets.update_one({'_id':aid,'upload_lock':lock},{'$set':{'upload_lock':0}})
        raise
    return {'uploaded_bytes':offset+len(data)}


@router.post('/uploads/{aid}/complete')
def complete_upload(aid:str,request:Request):
    auth.admin(request)
    asset = get_asset(aid)
    if asset['status']=='ready': return public_asset(asset)
    size = asset['uploaded_bytes']
    if not size or (asset.get('size_bytes') is not None and size!=asset['size_bytes']) or asset.get('upload_lock',0)>time.time():
        raise HTTPException(409,'La subida todavía no está completa.')
    db.vision_assets.update_one({'_id':aid,'status':'uploading'},{'$set':{'status':'ready','size_bytes':size,'completed_at':now()}})
    return public_asset(get_asset(aid))


@router.delete('/assets/{aid}',status_code=202)
def delete_asset(aid:str,request:Request):
    actor = auth.admin(request)
    asset = get_asset(aid)
    if asset.get('origin')=='real':
        raise HTTPException(409,'El original pertenece a una iteración del entorno real.')
    jobs = list(db.vision_jobs.find({'asset_id':aid,'deleted':{'$ne':True}}))
    if any(j['status'] not in TERMINAL for j in jobs):
        raise HTTPException(409,'Cancela o termina los análisis antes de eliminar el vídeo.')
    for job in jobs:
        remove_job(job,actor)
    db.vision_assets.update_one({'_id':aid},{'$set':{'deleted':True,'deleted_at':now()}})
    if asset['source']=='upload': asset_path(asset).unlink(missing_ok=True)
    return {'status':'deleted','source_preserved':asset['source']=='server'}


@router.get('/jobs')
def jobs(request:Request):
    auth.admin(request)
    return clean(list(db.vision_jobs.find({'deleted':{'$ne':True},'origin':{'$ne':'real'}}).sort('created_at',-1).limit(100)))


@router.post('/jobs',status_code=201)
def new_job(request:Request,body:dict):
    actor = auth.admin(request)
    asset=get_asset(str(body.get('asset_id','')))
    if asset.get('origin')=='real':
        raise HTTPException(409,'Solicita este análisis desde /iterations/{id}/analyses.')
    return create_job(asset,body,actor)


@router.get('/jobs/{jid}')
def job_detail(jid:str,request:Request):
    auth.admin(request)
    return clean(get_job(jid))


@router.post('/jobs/{jid}/cancel')
def cancel(jid:str,request:Request):
    auth.admin(request)
    job = get_job(jid)
    if job['status'] not in TERMINAL:
        db.vision_jobs.update_one({'_id':jid},{'$set':{'cancel_requested':True,'updated_at':now()}})
    return {'status':'cancellation_requested'}


def remove_job(job,actor):
    db.vision_jobs.update_one({'_id':job['job_id']},{'$set':{'deleted':True,'cancel_requested':True,'deleted_at':now()}})
    db.sessions.update_one({'_id':job['session_id']},{'$set':{'deleted':True,'status':'deleted',
        'purged':False,'deleted_at':now(),'deleted_by':actor['username']}})
    db.studies.update_one({'_id':job['study_id']},{'$set':{'deleted':True,'deleted_at':now()}})


@router.delete('/jobs/{jid}',status_code=202)
def delete_job(jid:str,request:Request):
    actor = auth.admin(request)
    job=get_job(jid)
    if job.get('origin')=='real': raise HTTPException(409,'Este análisis pertenece al entorno real.')
    remove_job(job,actor)
    return {'status':'deletion_pending'}


@router.post('/jobs/{jid}/finish')
def finish_live(jid:str,request:Request):
    auth.admin(request)
    job = get_job(jid)
    if job['mode']!='live' or job['status']!='capturing':
        raise HTTPException(409,'La captura ya está cerrada.')
    if get_asset(job['asset_id'])['status']!='ready':
        raise HTTPException(409,'Termina de guardar el vídeo original antes de cerrar la captura.')
    db.vision_jobs.update_one({'_id':jid,'status':'capturing'},{'$set':{'status':'finalizing','stage':'Terminando capturas pendientes','updated_at':now()}})
    return {'status':'finalizing'}


@router.put('/jobs/{jid}/frames/{sequence}',status_code=202)
async def live_frame(jid:str,sequence:int,request:Request,offset_s:float=Query(ge=0,le=3600)):
    auth.admin(request)
    job = get_job(jid)
    if job['mode']!='live' or job['status']!='capturing' or job['cancel_requested']:
        raise HTTPException(409,'La captura no está activa.')
    if not 0 <= sequence <= 100000 or not math.isfinite(offset_s):
        raise HTTPException(422,'Secuencia o tiempo inválidos.')
    key = f'{jid}:{sequence}'
    if db.vision_live.find_one({'_id':key}): return {'status':'duplicate'}
    if db.vision_live.count_documents({'job_id':jid,'status':'pending'})>=15:
        raise HTTPException(429,'La GPU tiene capturas pendientes; omite este frame.')
    data = bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data)>MAX_CHUNK_BYTES: raise HTTPException(413,'JPEG de hasta 8 MiB.')
    try:
        image = Image.open(io.BytesIO(data))
        if image.format!='JPEG' or image.size!=(1920,1080): raise ValueError()
        image.verify()
    except Exception:
        raise HTTPException(422,'Envía JPEG válido, normalizado a 1920×1080.')
    relative = 'live/'+jid+'/'+str(sequence)+'.jpg'
    path = inside(VISION,relative)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(data)
    from pymongo.errors import DuplicateKeyError
    try:
        db.vision_live.insert_one({'_id':key,'job_id':jid,'sequence':sequence,'offset_s':round(offset_s,6),
            'path':relative,'status':'pending','created_at':now()})
    except DuplicateKeyError:
        return {'status':'duplicate'}
    db.vision_jobs.update_one({'_id':jid},{'$set':{'last_capture_at':now(),'last_capture_ts':time.time()}})
    return {'status':'queued'}


@router.get('/jobs/{jid}/results')
def results(jid:str,request:Request,after:float=Query(-1,ge=-1),limit:int=Query(5000,ge=1,le=20000)):
    auth.admin(request)
    job = get_job(jid)
    rows = list(db.vision_results.find({'job_id':jid,'offset_s':{'$gt':after}}, {'_id':0}).sort('offset_s',1).limit(limit))
    total = db.vision_results.count_documents({'job_id':jid})
    return {'job':clean(job),'samples':rows,'total':total,'last_offset_s':rows[-1]['offset_s'] if rows else after}


@router.get('/jobs/{jid}/video')
def video(jid:str,request:Request,format:str='mp4'):
    auth.admin(request)
    job = get_job(jid)
    if format not in ('mp4','webm'): raise HTTPException(422,'Formato de reproducción no admitido.')
    field = 'preview_webm_path' if format=='webm' else 'preview_path'
    if not job.get(field): raise HTTPException(404,'El vídeo de reproducción todavía se está preparando.')
    return FileResponse(inside(VISION,job[field]),media_type='video/'+format,headers={'Cache-Control':'no-store'})


@router.get('/jobs/{jid}/original')
def original(jid:str,request:Request):
    auth.admin(request)
    asset = get_asset(get_job(jid)['asset_id'])
    if asset['status']!='ready': raise HTTPException(409,'Grabación en curso.')
    return FileResponse(asset_path(asset),filename=asset['name'])


@router.get('/jobs/{jid}/export.json')
def export_json(jid:str,request:Request):
    auth.admin(request)
    job = clean(get_job(jid))
    def chunks():
        yield '{"job":'+json.dumps(job,ensure_ascii=False)+',"samples":['
        first = True
        for row in db.vision_results.find({'job_id':jid},{'_id':0}).sort('offset_s',1):
            yield ('' if first else ',')+json.dumps(row,ensure_ascii=False,allow_nan=False)
            first = False
        yield ']}'
    return StreamingResponse(chunks(),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="{jid}.json"'})


@router.get('/jobs/{jid}/export.csv')
def export_csv(jid:str,request:Request):
    auth.admin(request)
    get_job(jid)
    def chunks():
        buffer = io.StringIO(); writer = csv.writer(buffer)
        writer.writerow(['offset_s','persons_detected','selection_confidence','rula_preliminary','reba_preliminary','coverage','status','trunk_deg','neck_deg'])
        yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
        for row in db.vision_results.find({'job_id':jid}).sort('offset_s',1):
            m = row['metrics']
            writer.writerow([row['offset_s'],row['persons_detected'],row['selection_confidence'],
                m['rula'],m['reba'],m['coverage'],m['status'],m['angles']['trunk'],m['angles']['neck']])
            yield buffer.getvalue();buffer.seek(0);buffer.truncate(0)
    return StreamingResponse(chunks(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{jid}.csv"'})
