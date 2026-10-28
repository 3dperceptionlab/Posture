import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from pymongo.errors import DuplicateKeyError

from . import auth
from .store import db, client, initialize, now, uid, clean, digest, task_context, ROOT, MEDIA
from .validation import validate, observed_at, SCHEMA
from .profile_height import TABLE_HEIGHT_RULE, height_values


@asynccontextmanager
async def lifespan(app):
    if auth.auth_mode() == 'development':
        logging.getLogger('uvicorn.error').warning(auth.DEVELOPMENT_WARNING)
    initialize()
    auth.initialize_admin()
    yield
    client.close()


app=FastAPI(title='POSTURE Data Processing and Dashboard API',version='0.1.0',lifespan=lifespan,docs_url=None)


@app.get('/api/docs',include_in_schema=False)
def api_docs():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title='POSTURE · API documentation',
        swagger_js_url='/assets/vendor/swagger-ui/swagger-ui-bundle.js',
        swagger_css_url='/assets/vendor/swagger-ui/swagger-ui.css',
        swagger_favicon_url='/assets/branding/posture.svg',
        swagger_ui_parameters={'validatorUrl':None},
    )


@app.middleware('http')
async def headers(request, call_next):
    if request.url.path.endswith('/update_sample') and 'content-length' not in request.headers:
        return JSONResponse({'detail':'La muestra multipart requiere Content-Length.'},status_code=411)
    length=request.headers.get('content-length','0')
    try:
        max_size=(10*1024*1024 if request.url.path.endswith('/update_sample') else
                  8*1024*1024 if '/frames/' in request.url.path or '/vision/uploads/' in request.url.path
                  or request.url.path.endswith('/video') else 2*1024*1024)
        if int(length)>max_size:
            return JSONResponse({'detail':'Solicitud demasiado grande.'},status_code=413)
    except ValueError:
        return JSONResponse({'detail':'Content-Length inválido.'},status_code=400)
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and request.headers.get('authorization','').startswith('Bearer ') is False:
        from urllib.parse import urlparse
        if urlparse(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'Origen de escritura no permitido.'},status_code=403)
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['X-POSTURE-Auth-Mode']=auth.auth_mode()
        if auth.auth_mode() == 'development':
            response.headers['X-POSTURE-Auth-Warning']=auth.DEVELOPMENT_WARNING
        if getattr(request.state,'auth_bypassed',False):
            response.headers['X-POSTURE-Auth-Bypass']='true'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api') else 'no-cache'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    return response


@app.get('/healthz')
def health():
    try:
        client.admin.command('ping')
        return {'status':'ok','service':'posture-api','version':'0.1.0'}
    except Exception:
        return JSONResponse({'status':'unavailable'},status_code=503)


@app.post('/api/v1/auth/login')
def login(request:Request,response:Response,body:dict):
    return auth.login(str(body.get('username',''))[:100],str(body.get('password',''))[:1000],request,response)


@app.post('/api/v1/auth/logout')
def logout(request:Request,response:Response):
    token=request.cookies.get('posture_session','')
    db.auth_sessions.delete_one({'_id':hashlib.sha256(token.encode()).hexdigest()})
    response.delete_cookie('posture_session')
    return {'ok':True}


@app.get('/api/v1/auth/me')
def me(request:Request):
    return auth.principal(request)


@app.post('/api/v1/auth/password')
def password(request:Request,body:dict):
    user=auth.principal(request)
    if user.get('unauthenticated'):
        raise HTTPException(401,'Inicia sesión con una cuenta real para cambiar su contraseña.')
    stored=db.users.find_one({'_id':user['username']})
    new=str(body.get('new_password',''))
    if not auth.check_password(str(body.get('current_password','')),stored['password_hash']):
        raise HTTPException(403,'La contraseña actual no es correcta.')
    if len(new)<16:
        raise HTTPException(422,'La nueva contraseña debe tener al menos 16 caracteres.')
    db.users.update_one({'_id':user['username']},{'$set':{'password_hash':auth.hash_password(new)}})
    db.auth_sessions.delete_many({'username':user['username']})
    return {'ok':True,'message':'Contraseña actualizada. Vuelve a iniciar sesión.'}


@app.get('/api/v1/users')
def users(request:Request):
    auth.admin(request)
    return clean(list(db.users.find({}, {'password_hash':0})))


@app.post('/api/v1/users',status_code=201)
def add_user(request:Request,body:dict):
    actor=auth.admin(request)
    name=str(body.get('username',''))
    password=str(body.get('password',''))
    role=body.get('role','viewer')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,60}',name) or len(password)<16 or role not in ('admin','viewer'):
        raise HTTPException(422,'Usuario de 3–60 caracteres, contraseña de al menos 16 y rol admin/viewer.')
    try:
        db.users.insert_one({'_id':name,'username':name,'password_hash':auth.hash_password(password),'role':role,'created_at':now()})
    except DuplicateKeyError:
        raise HTTPException(409,'La cuenta ya existe.')
    return {'username':name,'role':role}


@app.delete('/api/v1/users/{username}')
def delete_user(username:str,request:Request):
    actor=auth.admin(request)
    if username==actor['username']:
        raise HTTPException(409,'No puedes eliminar tu propia cuenta durante esta sesión.')
    if not db.users.delete_one({'_id':username}).deleted_count:
        raise HTTPException(404,'Cuenta no encontrada.')
    db.auth_sessions.delete_many({'username':username})
    return {'ok':True}


def get_session(sid):
    session=db.sessions.find_one({'_id':sid})
    if not session or session.get('deleted'):
        raise HTTPException(404,'Sesión no disponible.')
    return session


def latest_profile(operator_id, cell_id='cell-lab-01'):
    return db.profiles.find_one({'operator_id':operator_id,'cell_id':cell_id},sort=[('revision',-1)])


def profile_values(body, current=None):
    heights=height_values(body,current)
    try:
        pose=body['presentation_pose']
        xyz=pose['position_m']; q=pose['orientation_xyzw']
        if len(xyz)!=3 or len(q)!=4 or not all(type(n) in (int,float) and math.isfinite(n) for n in xyz+q):
            raise ValueError()
        if any(abs(n)>5 for n in xyz) or abs(sum(n*n for n in q)-1)>.002001:
            raise ValueError()
        if not isinstance(pose['frame_id'],str) or not pose['frame_id']:
            raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise HTTPException(422,'Pose, cuaternión o altura inválidos. Altura 0,2–2 m; ROS valida los límites de la célula.')
    return {'presentation_pose':{'position_m':xyz,'orientation_xyzw':q,'frame_id':pose['frame_id']},
            **heights,'table_height_reference':'tabletop_above_floor','apply_policy':'next_safe_state'}


@app.get('/api/v1/profile-rules/table-height')
def table_height_rule(request:Request):
    auth.principal(request,device=True)
    return TABLE_HEIGHT_RULE


@app.get('/api/v1/operators')
def operators(request:Request):
    auth.principal(request,device=True)
    rows=[]
    for op in db.operators.find({'deleted':{'$ne':True}}).sort('display_name',1):
        if op.get('laboratory'):
            continue
        p=latest_profile(op['operator_id'])
        status=db.profile_status.find_one({'profile_id':p['profile_id']},sort=[('observed_at',-1)]) if p else None
        rows.append({**clean(op),'profile':clean(p),'application':clean(status)})
    return rows


@app.post('/api/v1/operators',status_code=201)
def add_operator(request:Request,body:dict):
    auth.editor(request)
    name=str(body.get('display_name','')).strip()
    if not 1<=len(name)<=200:
        raise HTTPException(422,'Introduce un nombre de 1 a 200 caracteres.')
    values=profile_values(body)
    oid=uid('operator'); pid=uid('profile')
    cell=body.get('cell_id','cell-lab-01')
    if not db.cells.find_one({'_id':cell}):
        raise HTTPException(422,'La célula no existe.')
    profile={'_id':pid+':1','schema_version':'0.1','profile_id':pid,'operator_id':oid,
        'display_name':name,'cell_id':cell,'revision':1,'updated_at':now(),**values}
    db.profiles.insert_one(profile)
    db.operators.insert_one({'_id':oid,'operator_id':oid,'display_name':name,'profile_id':pid,'created_at':now()})
    return clean(profile)


@app.put('/api/v1/operator-profiles/{pid}')
def update_profile(pid:str,request:Request,body:dict):
    auth.editor(request)
    current=db.profiles.find_one({'profile_id':pid},sort=[('revision',-1)])
    if not current:
        raise HTTPException(404,'Perfil no encontrado.')
    expected=body.get('expected_revision')
    if request.headers.get('if-match'):
        try:
            expected=int(request.headers['if-match'].strip('"').split(':')[-1])
        except ValueError:
            raise HTTPException(422,'If-Match inválido.')
    if expected!=current['revision']:
        raise HTTPException(412,'El perfil cambió. Recarga antes de guardar.')
    name=str(body.get('display_name',current['display_name'])).strip()
    if not 1<=len(name)<=200:
        raise HTTPException(422,'Nombre inválido.')
    values=profile_values(body,current)
    new={**current,**values,'_id':pid+':'+str(current['revision']+1),
         'revision':current['revision']+1,'display_name':name,'updated_at':now()}
    try:
        db.profiles.insert_one(new)
    except DuplicateKeyError:
        raise HTTPException(412,'Otra edición se guardó antes. Recarga el perfil.')
    db.operators.update_one({'_id':new['operator_id']},{'$set':{'display_name':name}})
    return clean(new)


@app.get('/api/v1/operator-profiles/{pid}/revisions')
def revisions(pid:str,request:Request):
    auth.principal(request,device=True)
    return clean(list(db.profiles.find({'profile_id':pid}).sort('revision',-1)))


@app.delete('/api/v1/operators/{oid}',status_code=202)
def delete_operator(oid:str,request:Request):
    actor=auth.admin(request)
    if not db.operators.find_one({'_id':oid,'deleted':{'$ne':True}}):
        raise HTTPException(404,'Operario no encontrado.')
    db.operators.update_one({'_id':oid},{'$set':{'deleted':True,'display_name':'Operario eliminado','deleted_at':now()}})
    db.profiles.delete_many({'operator_id':oid})
    db.profile_status.delete_many({'operator_id':oid})
    for s in db.sessions.find({'operator_id':oid,'deleted':{'$ne':True}}):
        db.sessions.update_one({'_id':s['_id']},{'$set':{'deleted':True,'deleted_at':now(),
            'deleted_by':actor['username'],'status':'deleted','purged':False}})
    db.cells.update_many({'operator_id':oid},{'$set':{'operator_id':None,'session_id':None}})
    return {'status':'deletion_pending'}


@app.get('/api/v1/cells')
def cells(request:Request):
    auth.principal(request,device=True)
    return clean(list(db.cells.find()))


@app.get('/api/v1/cells/{cid}/desired-profile')
def desired(cid:str,request:Request):
    auth.principal(request,device=True)
    cell=db.cells.find_one({'_id':cid})
    p=latest_profile(cell['operator_id'],cid) if cell and cell.get('operator_id') else None
    if not p:
        raise HTTPException(404,'Selecciona un operario e inicia una sesión para esta célula.')
    etag='"'+p['profile_id']+':'+str(p['revision'])+'"'
    if request.headers.get('if-none-match')==etag:
        return Response(status_code=304,headers={'ETag':etag})
    return JSONResponse({**clean(p),'session_id':cell.get('session_id')},headers={'ETag':etag})


@app.post('/api/v1/sessions',status_code=201)
def create_session(request:Request,body:dict):
    auth.editor(request)
    return start_session(body)


def start_session(body):
    operator_id=body.get('operator_id')
    cell_id=body.get('cell_id','cell-lab-01')
    if not db.operators.find_one({'_id':operator_id,'deleted':{'$ne':True},'laboratory':{'$ne':True}}):
        raise HTTPException(422,'Selecciona un operario existente.')
    cell=db.cells.find_one({'_id':cell_id})
    if not cell:
        raise HTTPException(422,'Célula desconocida.')
    if cell.get('session_id'):
        active=db.sessions.find_one({'_id':cell['session_id'],'status':'active','deleted':{'$ne':True}})
        if active:
            raise HTTPException(409,'La célula ya tiene una sesión activa. Ciérrala antes de cambiar de operario.')
    study_id=body.get('study_id') or None
    if study_id and not db.studies.find_one({'_id':study_id,'deleted':{'$ne':True}}):
        raise HTTPException(422,'Estudio desconocido.')
    sid=uid('session')
    profile=latest_profile(operator_id,cell_id)
    session={'_id':sid,'session_id':sid,'operator_id':operator_id,'cell_id':cell_id,'study_id':study_id,
        'name':str(body.get('name') or 'Sesión de trabajo')[:200], 'condition':str(body.get('condition','assisted'))[:60],
        'started_at':now(),'status':'active','ended_at':None,'synthetic':False,
        'initial_profile_revision':profile['revision'] if profile else None,'deleted':False}
    db.sessions.insert_one(session)
    # compare-and-set so concurrent requests cannot claim the same cell.
    claim=db.cells.update_one({'_id':cell_id,'session_id':cell.get('session_id')},
                             {'$set':{'session_id':sid,'operator_id':operator_id}})
    if not claim.modified_count:
        db.sessions.delete_one({'_id':sid})
        raise HTTPException(409,'Otra sesión se inició en la célula. Recarga.')
    return clean(session)


def session_query(operator_id=None,study_id=None,from_date=None,to_date=None):
    q={'deleted':{'$ne':True}}
    if operator_id: q['operator_id']=operator_id
    if study_id: q['study_id']=study_id
    if from_date or to_date:
        q['started_at']={}
        if from_date: q['started_at']['$gte']=from_date
        if to_date: q['started_at']['$lte']=to_date+'T23:59:59.999Z' if len(to_date)==10 else to_date
    return q


@app.get('/api/v1/sessions')
def sessions(request:Request,operator_id:str=None,study_id:str=None,from_date:str=None,to_date:str=None,limit:int=Query(100,ge=1,le=500)):
    auth.principal(request,device=True)
    rows=[]
    for s in db.sessions.find(session_query(operator_id,study_id,from_date,to_date)).sort('started_at',-1).limit(limit):
        op=db.operators.find_one({'_id':s['operator_id']}) or {}
        count=db.inbox.count_documents({'session_id':s['_id']})
        latest=db.results.find_one({'session_id':s['_id']},sort=[('observed_at',-1)])
        rows.append({**clean(s),'operator_name':op.get('display_name','Operario'), 'message_count':count,'latest_metrics':clean(latest)})
    return rows


@app.post('/api/v1/sessions/{sid}/close')
def close_session(sid:str,request:Request):
    auth.editor(request)
    s=get_session(sid)
    db.sessions.update_one({'_id':sid},{'$set':{'status':'closed','ended_at':s.get('ended_at') or now()}})
    db.cells.update_one({'_id':s['cell_id'],'session_id':sid},{'$set':{'session_id':None}})
    return {'ok':True}


@app.delete('/api/v1/sessions/{sid}',status_code=202)
def delete_session(sid:str,request:Request):
    actor=auth.admin(request)
    s=get_session(sid)
    db.sessions.update_one({'_id':sid},{'$set':{'deleted':True,'deleted_at':now(),'deleted_by':actor['username'],'status':'deleted','purged':False}})
    db.cells.update_one({'_id':s['cell_id'],'session_id':sid},{'$set':{'session_id':None}})
    return {'status':'deletion_pending','session_id':sid}


def ingest_message(payload,context=None,association=None):
    validate(payload)
    mid=payload['message_id']
    previous=db.inbox.find_one({'_id':mid})
    fingerprint=digest(payload)
    if previous:
        if previous.get('session_id'):
            get_session(previous['session_id'])
        if previous['digest']!=fingerprint:
            raise HTTPException(409,'message_id reutilizado con contenido diferente.')
        return {'message_id':mid,'status':'duplicate','durable':True}
    if not db.cells.find_one({'_id':payload['cell_id']}):
        raise HTTPException(422,'Célula desconocida.')
    sid=payload.get('session_id')
    if sid:
        session=get_session(sid)
        if session['cell_id']!=payload['cell_id'] or session['operator_id']!=payload.get('operator_id') or session.get('study_id')!=payload.get('study_id'):
            raise HTTPException(422,'La célula, operario y estudio deben coincidir con la sesión.')
    elif payload.get('study_id') or payload.get('operator_id'):
        raise HTTPException(422,'Los datos vinculados a persona/estudio requieren una sesión.')
    if payload.get('study_id') and not db.studies.find_one({'_id':payload['study_id'],'deleted':{'$ne':True}}):
        raise HTTPException(422,'Estudio no disponible.')
    kind=payload['message_type']
    if kind=='profile_application':
        p=db.profiles.find_one({'profile_id':payload['profile_id'],'revision':payload['requested_revision']})
        if not p or p['cell_id']!=payload['cell_id'] or p['operator_id']!=payload.get('operator_id'):
            raise HTTPException(422,'La confirmación no corresponde a un perfil/revisión del operario y célula.')
    if kind=='shift_assessment':
        old=db.inbox.find_one({'payload.assessment_id':payload['assessment_id']})
        if old and old['_id']!=mid:
            raise HTTPException(409,'assessment_id ya registrado; conserva también message_id en reintentos.')
    frame=payload.get('frame') if kind=='telemetry' else None
    if frame:
        old_frame=db.frames.find_one({'_id':frame['frame_id']})
        if old_frame and (old_frame.get('session_id')!=sid or old_frame['captured_at']!=frame['captured_at'] or old_frame['camera_id']!=frame['camera_id']):
            raise HTTPException(409,'frame_id ya pertenece a otra captura o sesión.')
    parents={k:v for k,v in (association or {}).items() if k in ('shift_id','iteration_id','origin','pose_source')}
    record={'_id':mid,**parents,'digest':fingerprint,'payload':payload,'session_id':sid,
        'operator_id':payload.get('operator_id'),'cell_id':payload['cell_id'], 'study_id':payload.get('study_id'),
        'message_type':kind,'observed_at':observed_at(payload),'received_at':now(),
        'context':context if context is not None else task_context(),'pending':True,'processed':False,'archived':False,'published':False,
        'retry_at':0,'lease_until':0,'attempts':0,'error':None}
    try:
        db.inbox.insert_one(record)
    except DuplicateKeyError:
        old=db.inbox.find_one({'_id':mid})
        if old and old['digest']==fingerprint:
            return {'message_id':mid,'status':'duplicate','durable':True}
        raise HTTPException(409,'Identidad o secuencia duplicada.')
    if frame:
        if frame['retention_mode']=='study' and not payload.get('study_id'):
            raise HTTPException(422,'Se requiere estudio para conservar imágenes.')
        db.frames.update_one({'_id':frame['frame_id']},{'$setOnInsert':{
            **frame,**parents,'frame_id':frame['frame_id'],'session_id':sid,'operator_id':payload.get('operator_id'),
            'study_id':payload.get('study_id'),'status':'pending','path':None}},upsert=True)
    return {'message_id':mid,'status':'accepted','durable':True}


@app.post('/api/v1/ingest',status_code=202)
def ingest(request:Request,body:dict):
    auth.editor(request)
    result=ingest_message(body)
    return JSONResponse(result,status_code=200 if result['status']=='duplicate' else 202)


@app.post('/api/v1/ingest/batches',status_code=202)
def batch(request:Request,body:dict):
    auth.editor(request)
    messages=body.get('messages')
    if not isinstance(messages,list) or not 1<=len(messages)<=100:
        raise HTTPException(422,'messages debe contener entre 1 y 100 mensajes.')
    results=[]
    for p in messages:
        try:
            results.append(ingest_message(p))
        except HTTPException as e:
            results.append({'message_id':p.get('message_id') if isinstance(p,dict) else None,'status':'error','http_status':e.status_code,'detail':e.detail})
    return {'batch_id':body.get('batch_id'),'results':results}


@app.get('/api/v1/sessions/{sid}/timeline')
def timeline(sid:str,request:Request,limit:int=Query(600,ge=1,le=2000),before:str=None):
    auth.principal(request)
    get_session(sid)
    q={'session_id':sid,'message_type':'telemetry'}
    if before: q['observed_at']={'$lt':before}
    records=list(db.inbox.find(q,{'payload':1,'observed_at':1,'processed':1,'archived':1,'error':1}).sort([('observed_at',-1),('_id',-1)]).limit(limit))
    metrics={r['_id']:clean(r) for r in db.results.find({'_id':{'$in':[r['_id'] for r in records]}})}
    return {'total':db.inbox.count_documents({'session_id':sid,'message_type':'telemetry'}),
        'samples':[{'payload':r['payload'],'metrics':metrics.get(r['_id']),
                    'archived':r.get('archived',False),'error':r.get('error')} for r in reversed(records)],
        'next_before':records[-1]['observed_at'] if records else None,
        'events':clean(list(db.events.find({'session_id':sid}).sort('observed_at',1).limit(500)))}


@app.get('/api/v1/sessions/{sid}/export.csv')
def export(sid:str,request:Request):
    auth.principal(request)
    get_session(sid)
    def rows():
        text=io.StringIO(); writer=csv.writer(text)
        writer.writerow(['observed_at','message_id','rula_preliminary','reba_preliminary','coverage','status','geometry','context_revision'])
        yield text.getvalue(); text.seek(0);text.truncate(0)
        for m in db.results.find({'session_id':sid}).sort('observed_at',1):
            values=[m.get(k) for k in ('observed_at','message_id','rula','reba','coverage','status','geometry','context_revision')]
            values=[("'"+v) if isinstance(v,str) and v.startswith(('=','+','-','@')) else v for v in values]
            writer.writerow(values);yield text.getvalue();text.seek(0);text.truncate(0)
    return StreamingResponse(rows(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="posture-{sid}.csv"'})


@app.get('/api/v1/studies')
def studies(request:Request):
    auth.principal(request)
    return [{**clean(s),'frame_count':db.frames.count_documents({'study_id':s['_id'],'status':'available'})}
            for s in db.studies.find({'deleted':{'$ne':True}}).sort('created_at',-1)]


@app.post('/api/v1/studies',status_code=201)
def add_study(request:Request,body:dict):
    actor=auth.admin(request)
    name=str(body.get('name','')).strip()
    if not 1<=len(name)<=200: raise HTTPException(422,'Nombre de estudio requerido.')
    sid=uid('study')
    s={'_id':sid,'study_id':sid,'name':name,'description':str(body.get('description',''))[:2000],
       'created_at':now(),'created_by':actor['username'],'deleted':False}
    db.studies.insert_one(s)
    return clean(s)


@app.delete('/api/v1/studies/{study_id}',status_code=202)
def delete_study(study_id:str,request:Request):
    actor=auth.admin(request)
    if not db.studies.find_one({'_id':study_id,'deleted':{'$ne':True}}): raise HTTPException(404,'Estudio no encontrado.')
    db.studies.update_one({'_id':study_id},{'$set':{'deleted':True,'deleted_at':now()}})
    for s in db.sessions.find({'study_id':study_id,'deleted':{'$ne':True}}):
        db.sessions.update_one({'_id':s['_id']},{'$set':{'deleted':True,'deleted_at':now(),'deleted_by':actor['username'],'status':'deleted','purged':False}})
        db.cells.update_one({'session_id':s['_id']},{'$set':{'session_id':None}})
    return {'status':'deletion_pending'}


@app.get('/api/v1/studies/{study_id}/frames')
def frames(study_id:str,request:Request):
    auth.admin(request)
    if not db.studies.find_one({'_id':study_id,'deleted':{'$ne':True}}): raise HTTPException(404,'Estudio no disponible.')
    return clean(list(db.frames.find({'study_id':study_id,'status':'available'},{'path':0}).sort('captured_at',-1).limit(100)))


@app.put('/api/v1/frames/{frame_id:path}',status_code=201)
async def put_frame(frame_id:str,request:Request):
    auth.editor(request)
    frame=db.frames.find_one({'_id':frame_id})
    if not frame: raise HTTPException(404,'Envía primero metadatos de este frame en telemetría.')
    if frame.get('session_id'): get_session(frame['session_id'])
    data=bytearray()
    async for part in request.stream():
        data.extend(part)
        if len(data)>8*1024*1024: raise HTTPException(413,'JPEG limitado a 8 MiB.')
    digest_value=hashlib.sha256(data).hexdigest()
    expected=request.headers.get('x-content-sha256')
    if expected and expected!=digest_value: raise HTTPException(422,'Hash de imagen incorrecto.')
    if frame.get('sha256'):
        if frame['sha256']!=digest_value: raise HTTPException(409,'frame_id ya contiene otra imagen.')
        if frame.get('status')=='available': return {'status':'duplicate','frame_id':frame_id}
    try:
        image=Image.open(io.BytesIO(data))
        if image.format!='JPEG' or image.size!=(1920,1080): raise ValueError()
        image.verify()
    except Exception:
        raise HTTPException(422,'Se requiere JPEG válido de 1920×1080.')
    path=hashlib.sha256(frame_id.encode()).hexdigest()+'.jpg'
    claim=db.frames.update_one({'_id':frame_id,'$or':[{'sha256':{'$exists':False}},
        {'sha256':None},{'sha256':digest_value}]},{'$set':{'sha256':digest_value,'status':'uploading'}})
    if not claim.matched_count:
        raise HTTPException(409,'El frame ya se está guardando con otro contenido.')
    temp=MEDIA/(path+'.'+uid('tmp'))
    temp.write_bytes(data);temp.replace(MEDIA/path)
    expires=(datetime.now(timezone.utc)+timedelta(minutes=10)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    db.frames.update_one({'_id':frame_id},{'$set':{'path':path,'sha256':digest_value,'status':'available',
        'size_bytes':len(data),'expires_at':expires if frame['retention_mode']=='transient' else None}})
    return {'status':'available','frame_id':frame_id,'sha256':digest_value}


@app.get('/api/v1/frames/{frame_id:path}')
def get_frame(frame_id:str,request:Request):
    auth.admin(request)
    frame=db.frames.find_one({'_id':frame_id,'status':'available','retention_mode':'study'})
    if not frame or not frame.get('path'): raise HTTPException(404,'Imagen no disponible.')
    get_session(frame['session_id'])
    return FileResponse(MEDIA/frame['path'],media_type='image/jpeg',headers={'Cache-Control':'no-store'})


@app.get('/api/v1/assessments')
def assessments(request:Request,session_id:str=None):
    auth.principal(request)
    q={}
    if session_id:
        get_session(session_id);q['session_id']=session_id
    deleted=[s['_id'] for s in db.sessions.find({'deleted':True},{'_id':1})]
    if not session_id: q['session_id']={'$nin':deleted}
    return clean(list(db.assessments.find(q).sort('submitted_at',-1).limit(200)))


@app.get('/api/v1/alerts')
def alerts(request:Request):
    auth.principal(request)
    deleted=[s['_id'] for s in db.sessions.find({'deleted':True},{'_id':1})]
    return clean(list(db.alerts.find({'session_id':{'$nin':deleted}}).sort('observed_at',-1).limit(100)))


@app.post('/api/v1/alerts/{aid}/acknowledge')
def acknowledge(aid:str,request:Request):
    actor=auth.admin(request)
    db.alerts.update_one({'_id':aid},{'$set':{'acknowledged':True,'acknowledged_at':now(),'acknowledged_by':actor['username']}})
    return {'ok':True}


@app.get('/api/v1/cells/{cid}/summary')
def cell_summary(cid:str,request:Request,window_seconds:int=Query(60,ge=10,le=3600)):
    auth.principal(request,device=True)
    if not db.cells.find_one({'_id':cid}): raise HTTPException(404,'Célula desconocida.')
    stamp=datetime.now(timezone.utc)
    begin=(stamp-timedelta(seconds=window_seconds)).isoformat(timespec='milliseconds').replace('+00:00','Z')
    deleted=[s['_id'] for s in db.sessions.find({'deleted':True},{'_id':1})]
    latest=db.results.find_one({'cell_id':cid,'session_id':{'$nin':deleted}},sort=[('observed_at',-1)])
    values=list(db.results.find({'cell_id':cid,'session_id':{'$nin':deleted},'observed_at':{'$gte':begin,'$lte':now()}},
                               {'observed_at':1,'rula':1,'reba':1,'coverage':1,'angles':1}).sort('observed_at',1).limit(10000))
    valid=high=0.0; distributions={'rula':{},'reba':{}};angle_totals={};angle_times={}
    for a,b in zip(values,values[1:]):
        dt=(datetime.fromisoformat(b['observed_at'].replace('Z','+00:00'))-datetime.fromisoformat(a['observed_at'].replace('Z','+00:00'))).total_seconds()
        if not 0<dt<=2 or a['rula'] is None or a['reba'] is None:continue
        valid+=dt
        if a['rula']>=5 or a['reba']>=8:high+=dt
        for kind in distributions:
            key=str(a[kind]);distributions[kind][key]=distributions[kind].get(key,0)+dt
        for name,value in a.get('angles',{}).items():
            if value is not None:
                angle_totals[name]=angle_totals.get(name,0)+value*dt
                angle_times[name]=angle_times.get(name,0)+dt
    age=(stamp-datetime.fromisoformat(latest['observed_at'].replace('Z','+00:00'))).total_seconds() if latest else None
    fresh=age is not None and -2<=age<=120
    return {'cell_id':cid,'generated_at':now(),'window_seconds':window_seconds,
        'latest_capture_at':latest['observed_at'] if latest else None,
        'capture_age_seconds':round(age,1) if age is not None else None,'fresh':fresh,
        'sample_count':len(values),'valid_observed_seconds':round(valid,2),
        'missing_or_uncovered_seconds':round(max(0,window_seconds-valid),2),
        'elevated_seconds':round(high,2),'max_gap_seconds':2,
        'score_distribution_seconds':distributions,
        'angle_means_deg':{k:round(v/angle_times[k],2) for k,v in angle_totals.items()},
        'latest_scores':{'rula':latest['rula'],'reba':latest['reba']} if latest else None,
        'preliminary_alert':bool(fresh and high>=10),'status':'preliminary_assumed',
        'rule':'Revisar si RULA >=5 o REBA >=8 acumulan >=10 s observados en ventana; no extrapolar huecos.',
        'assumptions':latest.get('assumptions',[]) if latest else []}


@app.get('/api/v1/context')
def context(request:Request):
    auth.principal(request)
    return task_context()


@app.put('/api/v1/context')
def update_context(request:Request,body:dict):
    auth.admin(request)
    previous=task_context()
    if body.get('revision')!=previous['revision']:
        raise HTTPException(412,'La configuración ha cambiado.')
    # Preserve the complete structure and accept only finite values of the expected type.
    try:
        if set(body)!=set(previous): raise ValueError()
        for key,old in previous['operation'].items():
            item=body['operation'][key]
            if old['value'] is None:
                if item['value'] is not None and not isinstance(item['value'],str): raise ValueError()
            elif type(item['value'])!=type(old['value']): raise ValueError()
            if item['provenance'] not in ('assumed','unknown','user_estimate','manual_observation','measured'): raise ValueError()
        if not 0<=body['part']['mass_kg']['value']<=100: raise ValueError()
        if body['operation']['grip_quality']['value'] not in ('good','fair','poor','unacceptable'): raise ValueError()
        if body['operation']['wrist_twist']['value'] not in ('midrange','endrange'): raise ValueError()
        for key in previous['phases']:
            mass=body['phases'][key]['human_load_proxy_kg']['value']
            if type(mass) not in (float,int) or not math.isfinite(mass) or not 0<=mass<=100: raise ValueError()
        json.dumps(body,allow_nan=False)
    except (KeyError,TypeError,ValueError):
        raise HTTPException(422,'Estructura o factores del contexto inválidos.')
    body['revision']+=1
    changed=db.config.update_one({'_id':'ergonomics','value.revision':previous['revision']},{'$set':{'value':body,'updated_at':now()}})
    if not changed.modified_count: raise HTTPException(412,'Edición concurrente. Recarga.')
    return body


@app.get('/api/v1/schema')
def schema(request:Request):
    auth.principal(request,device=True)
    return SCHEMA


@app.get('/api/v1/stats')
def stats(request:Request):
    auth.principal(request)
    sids=[s['_id'] for s in db.sessions.find({'deleted':{'$ne':True}},{'_id':1})]
    query={'session_id':{'$in':sids}}
    recent=list(db.results.find(query,{'rula':1,'reba':1,'coverage':1,'observed_at':1}).sort('observed_at',-1).limit(1000))
    valid=[r for r in recent if r.get('rula') is not None]
    latest=db.inbox.find_one(query,sort=[('observed_at',-1)])
    return {'sessions':len(sids),'operators':db.operators.count_documents({'deleted':{'$ne':True},'laboratory':{'$ne':True}}),
        'active_sessions':db.sessions.count_documents({'status':'active','deleted':{'$ne':True}}),
        'messages':db.inbox.count_documents(query),'pending':db.inbox.count_documents({**query,'pending':True}),
        'coverage':round(sum(r['coverage'] for r in recent)/len(recent),3) if recent else None,
        'elevated_samples':sum(1 for r in valid if r['rula']>=5 or r['reba']>=8),'evaluated_samples':len(valid),
        'latest_received_at':latest['received_at'] if latest else None,
        'assessments':db.assessments.count_documents(query),'images':db.frames.count_documents({**query,'status':'available','retention_mode':'study'})}


@app.get('/api/v1/system')
def system(request:Request):
    auth.admin(request)
    services={}
    for name,url in [('orion',os.getenv('ORION_URL','http://orion:1026')+'/version'),
                     ('crate',os.getenv('CRATE_URL','http://crate:4200')+'/'),
                     ('quantumleap',os.getenv('QUANTUMLEAP_URL','http://quantumleap:8668')+'/version')]:
        try:
            r=httpx.get(url,timeout=3)
            services[name]={'ok':r.status_code<400,'status_code':r.status_code}
        except Exception:
            services[name]={'ok':False}
    services['mongo']={'ok':bool(client.admin.command('ping')['ok'])}
    worker=clean(db.system.find_one({'_id':'worker'}))
    if worker:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(worker['heartbeat'].replace('Z','+00:00'))).total_seconds()
        worker['healthy']=age<30
    ql_history=None
    try:
        with httpx.Client(timeout=3) as http:
            r=http.post(os.getenv('CRATE_URL','http://crate:4200')+'/_sql',json={'stmt':'SELECT count(*) FROM etergonomicobservation'})
            if r.status_code==200: ql_history=r.json()['rows'][0][0]
    except Exception:
        pass
    return {'services':services,'worker':worker,'fiware':clean(db.system.find_one({'_id':'fiware'})),
        'pending':db.inbox.count_documents({'pending':True}),'quantumleap_rows':ql_history,
        'archive_count':db.inbox.count_documents({'archived':True}),
        'errors':clean(list(db.inbox.find({'error':{'$ne':None}},{'payload':0,'context':0}).limit(10))),
        'runtime':{'reconstruction':'not_configured','metrics':'RULA/REBA preliminares con geometría disponible',
                   'retention':'Hasta borrado manual; originales transitorios de imagen: 10 min'}}


@app.post('/api/v1/demo',status_code=201)
def demo(request:Request):
    auth.admin(request)
    if db.sessions.count_documents({'synthetic':True,'deleted':{'$ne':True}})>=5:
        raise HTTPException(409,'Ya hay cinco sesiones simuladas. Elimina alguna para generar otra.')
    template=json.loads((ROOT/'examples/telemetry.json').read_text())
    op=db.operators.find_one({'synthetic':True})
    if not op:
        p=json.loads((ROOT/'examples/operator-profile.json').read_text())
        oid=uid('operator');pid=uid('profile')
        p.update({'_id':pid+':1','profile_id':pid,'operator_id':oid,'revision':1,
                  'display_name':'Operario · simulación','updated_at':now()})
        db.profiles.insert_one(p)
        op={'_id':oid,'operator_id':oid,'profile_id':pid,'display_name':p['display_name'],'synthetic':True,'created_at':now()}
        db.operators.insert_one(op)
    study_id=uid('study')
    db.studies.insert_one({'_id':study_id,'study_id':study_id,'name':'Laboratorio · datos sintéticos',
        'description':'Simulación generada por POSTURE; ninguna imagen representa una persona real.',
        'created_at':now(),'synthetic':True,'deleted':False})
    sid=uid('session');start=datetime.now(timezone.utc)-timedelta(minutes=6)
    stamp=lambda d:d.isoformat(timespec='milliseconds').replace('+00:00','Z')
    session={'_id':sid,'session_id':sid,'operator_id':op['_id'],'cell_id':'cell-lab-01','study_id':study_id,
        'name':'Prueba de laboratorio','condition':'simulation','status':'closed','synthetic':True,
        'started_at':stamp(start),'ended_at':stamp(start+timedelta(seconds=357)),'deleted':False}
    db.sessions.insert_one(session)
    base={k:template[k] for k in ('schema_version','cell_id','clock_sync')}
    def envelope(seq,kind,at):
        return {**base,'message_type':kind,'message_id':sid+':'+str(seq),'sequence':seq,
            'source_id':'simulator','boot_id':sid,'session_id':sid,'operator_id':op['_id'],
            'study_id':study_id,'emitted_at':at}
    seq=0
    for i in range(120):
        at=stamp(start+timedelta(seconds=i*3));cycle=sid+':piece-'+str(i//12+1)
        if i%12==0:
            seq+=1
            ingest_message({**envelope(seq,'event',at),'observed_at':at,'cycle_id':cycle,
                'event_type':'phase_started','origin':'inferred','reason':'Evento sintético',
                'data':{'phase':'manual_finishing','phase_instance_id':cycle+':finishing'}})
        seq+=1
        message=json.loads(json.dumps(template));message.update(envelope(seq,'telemetry',at))
        lean=math.sin(i/11)*.6+(.5 if 36<i<80 else 0)
        for name,joint in message['pose']['joints'].items():
            if joint['image_xy_px']:
                x,y=joint['image_xy_px'];joint['image_xy_px']=[round(x+lean*(1080-y)*.25,2),y]
        message['pose'].update({'observed_at':at,'frame_id':sid+':frame-'+str(i),'cycle_id':cycle})
        message['robot'].update({'observed_at':at,'cycle_id':cycle,'robot_mode':'idle' if i%12>3 else 'moving','applied_profile_revision':1})
        message['robot']['suction'].update({'commanded_active':i%12<4,'last_command_at':at})
        message['robot']['joint_positions_rad'][0]=round(math.sin(i/12)*.8,3)
        message['table'].update({'observed_at':at,'applied_profile_revision':1})
        message['frame'].update({'frame_id':message['pose']['frame_id'],'captured_at':at})
        ingest_message(message)
        if i in (0,40,80):
            image=Image.new('RGB',(1920,1080),'#ecf1ed');draw=ImageDraw.Draw(image)
            draw.text((80,60),'POSTURE / SIMULACION DE LABORATORIO - IMAGEN SINTETICA',fill='#124c46',font_size=34)
            for joint in message['pose']['joints'].values():
                if joint['image_xy_px']:
                    x,y=joint['image_xy_px'];draw.ellipse((x-10,y-10,x+10,y+10),fill='#16766d')
            for a,b in [('left_shoulder','right_shoulder'),('left_shoulder','left_elbow'),('left_elbow','left_wrist'),('right_shoulder','right_elbow'),('right_elbow','right_wrist'),('left_shoulder','left_hip'),('right_shoulder','right_hip'),('left_hip','right_hip'),('left_hip','left_knee'),('right_hip','right_knee')]:
                draw.line((*message['pose']['joints'][a]['image_xy_px'],*message['pose']['joints'][b]['image_xy_px']),fill='#16766d',width=7)
            path=hashlib.sha256(message['frame']['frame_id'].encode()).hexdigest()+'.jpg'
            image.save(MEDIA/path,'JPEG',quality=85)
            db.frames.update_one({'_id':message['frame']['frame_id']},{'$set':{'status':'available','path':path,'sha256':hashlib.sha256((MEDIA/path).read_bytes()).hexdigest(),'size_bytes':(MEDIA/path).stat().st_size,'expires_at':None}})
    seq+=1
    form=json.loads((ROOT/'examples/shift-assessment.json').read_text());form.update(envelope(seq,'shift_assessment',stamp(start+timedelta(seconds=357))))
    form.update({'assessment_id':uid('assessment'),'submitted_at':form['emitted_at'],'shift_id':sid+':shift'})
    ingest_message(form)
    return {'session_id':sid,'study_id':study_id,'messages':seq,'synthetic':True}


from .vision import router as vision_router
app.include_router(vision_router)
from .real import router as real_router
app.include_router(real_router)


def openapi_contract():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    from .real_models import Sample
    schema=get_openapi(title='POSTURE Data Processing and Dashboard API',version='1.0.0',routes=app.routes,
        description='Data processing and dashboard module: HMI/ROS acquisition by shift and workpiece iteration, '
                    'plus independent laboratory tools. In strict mode, acquisition requires a ROS Bearer token '
                    'or administrator session cookie. Receiving data does not imply metric calculation. '
                    'Contract and examples: docs/ROS_API.md.')
    sample=Sample.model_json_schema(ref_template='#/components/schemas/{model}')
    components=schema.setdefault('components',{}).setdefault('schemas',{})
    components.update(sample.pop('$defs',{}));components['RealSample']=sample
    # FastAPI merges list-valued openapi_extra; an explicit security policy replaces it.
    for route in [*app.routes,*real_router.routes]:
        override=(getattr(route,'openapi_extra',None) or {}).get('security')
        if override is not None:
            for method in getattr(route,'methods',[]):
                operation=schema.get('paths',{}).get(route.path,{}).get(method.lower())
                if operation is not None: operation['security']=override
    mode=auth.auth_mode()
    schema['info']['x-posture-auth-mode']=mode
    if mode == 'development':
        schema['info']['description']+=' DEVELOPMENT MODE: requests without credentials have administrator access. Responses include X-POSTURE-Auth-Warning. Invalid credentials are rejected. Use POSTURE_AUTH_MODE=strict for deployment.'
        for path in schema['paths'].values():
            for operation in path.values():
                if isinstance(operation,dict) and operation.get('security'):
                    operation['security']=[*operation['security'],{}]
    app.openapi_schema=schema
    return schema


app.openapi=openapi_contract
app.mount('/assets',StaticFiles(directory=ROOT/'backend/static'),name='assets')


@app.get('/',include_in_schema=False)
def index():
    return FileResponse(ROOT/'backend/static/index.html')
