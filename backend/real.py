"""Production acquisition: shifts, pieces, immutable samples and deferred analyses."""
import hashlib
import io
import json
import math
import os
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.security import HTTPBearer, APIKeyCookie
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from starlette.concurrency import run_in_threadpool

from . import auth
from .store import db, now, uid, clean, digest, MEDIA, task_context
from .vision_common import VISION, inside, create_job, get_asset
from .real_models import (ShiftStart, ShiftEnd, IterationStart, Summary, Sample, VideoStart,
    AnalysisRequest, LabelUpdate, Settings, FormDefinition, ShiftRead, IterationRead, SampleRead, SampleReceipt, AnalysisRead)

router = APIRouter(prefix='/api/v1', tags=['Real-world acquisition'],
    dependencies=[Depends(HTTPBearer(auto_error=False)),Depends(APIKeyCookie(name='posture_session',auto_error=False))],
    responses={401:{'description':'Missing or invalid credentials'},403:{'description':'Insufficient permissions'},
               409:{'description':'Identity, state or concurrent request conflict'},
               413:{'description':'Maximum size exceeded'},422:{'description':'Invalid contract or chronology'}})
MAX_IMAGE = 8 * 1024**2
MAX_BLOCK = 8 * 1024**2
DEFAULT_FORM = {'form_id':'posture.shift-checkin.v1','title':'Estado antes y después del turno',
    'description':'Formulario provisional del piloto, configurable. No es NASA-TLX y no calcula una puntuación clínica.',
    'questions':[
        {'key':'fatigue','label':'Fatiga percibida','type':'scale','minimum':0,'maximum':10,'required':False,'phases':['pre','post']},
        {'key':'workload','label':'Carga percibida','type':'scale','minimum':0,'maximum':10,'required':False,'phases':['pre','post']},
        {'key':'comfort','label':'Comodidad','type':'scale','minimum':0,'maximum':10,'required':False,'phases':['pre','post']},
        {'key':'comment','label':'Comentario','type':'text','required':False,'phases':['pre','post']} ]}


def mark(values=None):
    return {**(values or {}), 'archive_dirty':True, 'archive_token':uid('revision')}


def initialize_real():
    for collection, keys, opts in [
        ('real_shifts',[('shift_id',1)],{'unique':True}),
        ('real_shifts',[('cell_id',1)],{'unique':True,'partialFilterExpression':{'status':'active'}}),
        ('real_iterations',[('iteration_id',1)],{'unique':True}),
        ('real_iterations',[('cell_id',1)],{'unique':True,'partialFilterExpression':{'status':'active'}}),
        ('real_iterations',[('shift_id',1),('started_at',-1)],{}),
        ('real_iterations',[('operator_id',1),('started_at',-1)],{}),
        ('real_samples',[('iteration_id',1),('sequence',1)],{'unique':True}),
        ('real_samples',[('shift_id',1),('captured_at',1)],{}),
        ('real_results',[('analysis_id',1),('sequence',1)],{'unique':True}),
        ('real_actions',[('iteration_id',1),('event_id',1)],{'unique':True}),
        ('real_jobs',[('iteration_id',1),('created_at',-1)],{}),
    ]:
        db[collection].create_index(keys, **opts)
    initial_form=FormDefinition.model_validate(DEFAULT_FORM).model_dump(mode='json')
    db.real_forms.update_one({'_id':DEFAULT_FORM['form_id']},{'$setOnInsert':mark(initial_form)},upsert=True)
    db.config.update_one({'_id':'real-settings'},{'$setOnInsert':{
        'revision':1,'ros_metrics_mode':'manual','video_analysis_mode':'manual',
        'sample_fps':5,'confidence':.5,'assessment_form_id':DEFAULT_FORM['form_id'],'updated_at':now()}},upsert=True)
    (MEDIA/'real').mkdir(parents=True,exist_ok=True)


def public(doc):
    if doc is None:
        return None
    return clean({k:v for k,v in doc.items() if k not in (
        'start_digest','end_digest','digest','image_path','path','archive_token','archive_dirty','upload_lock')})


def encoded(model):
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):
            raise HTTPException(422,'Los datos deben ser JSON finito.')
        if isinstance(value,dict):
            for item in value.values(): finite(item)
        elif isinstance(value,(list,tuple)):
            for item in value: finite(item)
    finite(model.model_dump(mode='python'))
    data = model.model_dump(mode='json')
    try:
        digest(data)  # Includes extension dictionaries: reject nested NaN/Infinity too.
    except (TypeError,ValueError):
        raise HTTPException(422,'Los datos deben ser JSON finito.')
    return data


def key_for(kind,source,client):
    return kind+'-'+hashlib.sha256((source+'\0'+client).encode()).hexdigest()


def next_id(kind):
    row=db.real_counters.find_one_and_update({'_id':kind},{'$inc':{'value':1}},upsert=True,return_document=ReturnDocument.AFTER)
    return row['value']


@contextmanager
def lock(key):
    token=uid('lock'); stamp=time.time()
    try:
        row=db.real_locks.find_one_and_update({'_id':key,'until':{'$lt':stamp}},
            {'$set':{'token':token,'until':stamp+120}},upsert=True,return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        raise HTTPException(409,'Operación concurrente: reintenta con el mismo identificador.',headers={'Retry-After':'1'})
    try:
        yield row
    finally:
        db.real_locks.delete_one({'_id':key,'token':token})


def get_shift(shift_id):
    row=db.real_shifts.find_one({'shift_id':shift_id})
    if not row: raise HTTPException(404,'Turno no encontrado.')
    return row


def get_iteration(iteration_id):
    row=db.real_iterations.find_one({'iteration_id':iteration_id})
    if not row: raise HTTPException(404,'Iteración no encontrada.')
    return row


def mirror_operator(source,operator):
    oid=key_for('operator-hmi',source,str(operator['id']))
    db.operators.update_one({'_id':oid},{'$set':{'operator_id':oid,'display_name':operator['name'],
        'external_id':str(operator['id']),'hmi_source':source,'source':'hmi','stature_m':operator.get('stature_m'),
        'hmi_profile':operator.get('profile',{}),'updated_at':now(),'deleted':False},'$setOnInsert':{'created_at':now()}},upsert=True)
    return oid


def form_by_id(form_id):
    form=db.real_forms.find_one({'_id':form_id})
    if not form: raise HTTPException(422,'Formulario desconocido. Consulta /assessment-forms.')
    return {k:form[k] for k in ('form_id','title','description','questions')}


def check_assessment(assessment,form,phase):
    if assessment['form_id']!=form['form_id']:
        raise HTTPException(422,'El formulario debe coincidir con la versión fijada para el turno.')
    questions={q['key']:q for q in form['questions'] if phase in q.get('phases',['pre','post'])}
    answers=assessment['answers']
    if set(answers)-set(questions): raise HTTPException(422,'Hay respuestas no definidas para esta fase del formulario.')
    for name,q in questions.items():
        if name not in answers:
            if q.get('required'): raise HTTPException(422,'Falta respuesta obligatoria: '+name)
            continue
        value=answers[name]
        if q['type']=='scale' and (type(value) not in (int,float) or not q.get('minimum',0)<=value<=q.get('maximum',10)):
            raise HTTPException(422,'Respuesta fuera de escala: '+name)
        if q['type']=='text' and (not isinstance(value,str) or len(value)>2000):
            raise HTTPException(422,'Texto de respuesta inválido: '+name)
        if q['type']=='choice' and value not in q['choices']:
            raise HTTPException(422,'Opción de respuesta inválida: '+name)


def save_assessment(shift,assessment,phase):
    aid=f'shift-{shift["shift_id"]}:{phase}'
    db.real_assessments.update_one({'_id':aid},{'$setOnInsert':mark({**assessment,'assessment_id':aid,
        'phase':phase,'shift_id':shift['shift_id'],'operator_id':shift['operator_id'],'received_at':now(),
        'form_definition':shift['form_definition']})},upsert=True)


@router.get('/assessment-forms',summary='List versioned HMI questionnaires')
def forms(request:Request):
    auth.principal(request,device=True)
    return [public(f) for f in db.real_forms.find().sort('form_id',1)]


@router.post('/assessment-forms',status_code=201,summary='Register an immutable questionnaire version',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def add_form(request:Request,body:FormDefinition):
    auth.admin(request); data=encoded(body)
    with lock('forms:'+body.form_id):
        previous=db.real_forms.find_one({'_id':body.form_id})
        if previous:
            if digest({k:previous[k] for k in data})!=digest(data):
                raise HTTPException(409,'El ID de formulario ya existe. Usa una versión nueva.')
            return public(previous)
        db.real_forms.insert_one({'_id':body.form_id,**mark(data)})
    return data


@router.get('/real/settings',summary='Read independent production acquisition settings')
def settings(request:Request):
    auth.principal(request,device=True)
    return clean(db.config.find_one({'_id':'real-settings'}))


@router.put('/real/settings',summary='Configure policies for future iterations',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def set_settings(request:Request,body:Settings):
    actor=auth.admin(request); data=encoded(body); expected=data.pop('expected_revision')
    form_by_id(data['assessment_form_id'])
    row=db.config.find_one_and_update({'_id':'real-settings','revision':expected},
        {'$set':{**data,'updated_at':now(),'updated_by':actor['username']},'$inc':{'revision':1}},return_document=ReturnDocument.AFTER)
    if not row: raise HTTPException(412,'La configuración cambió. Recarga antes de guardar.')
    return clean(row)


@router.post('/shifts',status_code=201,response_model=ShiftRead,summary='Start a shift with HMI operator and pre-shift questionnaire')
def start_shift(request:Request,body:ShiftStart):
    auth.editor(request); data=encoded(body); fingerprint=digest(data)
    key=key_for('shift',data['source_id'],data['client_shift_id'])
    with lock('cell:'+data['cell_id']):
        old=db.real_shifts.find_one({'_id':key})
        if old:
            if old['start_digest']!=fingerprint: raise HTTPException(409,'client_shift_id reutilizado con otros datos.')
            save_assessment(old,old['assessment'],'pre')
            return JSONResponse(public(old),status_code=200)
        if db.real_shifts.find_one({'cell_id':data['cell_id'],'status':'active'}):
            raise HTTPException(409,'Ya hay un turno activo en esta célula.')
        previous=db.real_shifts.find_one({'cell_id':data['cell_id']},sort=[('shift_id',-1)])
        if previous and previous.get('ended_at') and data['started_at']<previous['ended_at']:
            raise HTTPException(409,'El turno solapa el anterior.')
        config=clean(db.config.find_one({'_id':'real-settings'}))
        form=form_by_id(config['assessment_form_id']); check_assessment(data['assessment'],form,'pre')
        oid=mirror_operator(data['source_id'],data['operator'])
        row={'_id':key,**mark(data),'shift_id':next_id('shift'),'operator_id':oid,'external_operator_id':str(data['operator']['id']),
            'status':'active','ended_at':None,'start_digest':fingerprint,'form_definition':form,'created_at':now()}
        db.cells.update_one({'_id':data['cell_id']},{'$setOnInsert':{'cell_id':data['cell_id'],'name':data['cell_id'],
            'source':'hmi','created_at':now(),'operator_id':None,'session_id':None}},upsert=True)
        db.real_shifts.insert_one(row); save_assessment(row,data['assessment'],'pre')
    return public(row)


@router.post('/shifts/{shift_id}/end',response_model=ShiftRead,summary='End a shift with its post-shift questionnaire')
def end_shift(shift_id:int,request:Request,body:ShiftEnd):
    auth.editor(request); data=encoded(body); shift=get_shift(shift_id)
    with lock('cell:'+shift['cell_id']):
        shift=get_shift(shift_id)
        if shift.get('end_digest'):
            if shift['end_digest']!=digest(data): raise HTTPException(409,'El cierre ya contiene otros datos.')
            save_assessment(shift,shift['end_assessment'],'post')
            return public(shift)
        if data['ended_at']<shift['started_at']: raise HTTPException(422,'El fin precede al inicio del turno.')
        check_assessment(data['assessment'],shift['form_definition'],'post')
        latest=db.real_iterations.find_one({'shift_id':shift_id},sort=[('started_at',-1)])
        if latest and data['ended_at']<(latest.get('ended_at') or latest['started_at']):
            raise HTTPException(422,'El fin del turno precede a sus iteraciones.')
        last_sample=db.real_samples.find_one({'shift_id':shift_id},sort=[('captured_at',-1)])
        if last_sample and last_sample['captured_at']>data['ended_at']:
            raise HTTPException(422,'El fin del turno precede a sus muestras.')
        db.real_iterations.update_many({'shift_id':shift_id,'status':'active'},{'$set':mark({
            'status':'aborted','ended_at':data['ended_at'],'completion_reason':'shift_ended'})})
        fields=mark({'status':data['status'],'ended_at':data['ended_at'],'end_assessment':data['assessment'],
            'end_digest':digest(data),'end_metadata':data['metadata'],'end_reason':data['reason']})
        db.real_shifts.update_one({'_id':shift['_id']},{'$set':fields}); shift.update(fields)
        save_assessment(shift,data['assessment'],'post')
    return public(shift)


@router.get('/shifts',response_model=list[ShiftRead])
def shifts(request:Request,operator_id:str=None,label:str=None,before_id:int=None,limit:int=Query(100,ge=1,le=500)):
    auth.principal(request,device=True); query={}
    if operator_id: query['operator_id']=operator_id
    if label is not None: query['label']=label
    if before_id is not None: query['shift_id']={'$lt':before_id}
    return [public(s) for s in db.real_shifts.find(query).sort('shift_id',-1).limit(limit)]


@router.get('/shifts/{shift_id}',response_model=ShiftRead)
def shift_detail(shift_id:int,request:Request):
    auth.principal(request,device=True)
    return {**public(get_shift(shift_id)),'assessments':[public(a) for a in db.real_assessments.find({'shift_id':shift_id})]}


@router.patch('/shifts/{shift_id}',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def label_shift(shift_id:int,request:Request,body:LabelUpdate):
    auth.admin(request); row=get_shift(shift_id)
    db.real_shifts.update_one({'_id':row['_id']},{'$set':mark(encoded(body))})
    return public(get_shift(shift_id))


@router.post('/iterations',status_code=201,response_model=IterationRead,summary='Start an iteration when the UR begins workpiece pickup')
def start_iteration(request:Request,body:IterationStart):
    auth.editor(request); data=encoded(body); fingerprint=digest(data)
    key=key_for('iteration',data['source_id'],data['client_iteration_id'])
    with lock('cell:'+data['cell_id']):
        old=db.real_iterations.find_one({'_id':key})
        if old:
            if old['start_digest']!=fingerprint: raise HTTPException(409,'client_iteration_id reutilizado con otros datos.')
            return JSONResponse(public(old),status_code=200)
        shift=get_shift(data['shift_id'])
        if shift['status']!='active' or shift['cell_id']!=data['cell_id'] or shift['source_id']!=data['source_id']:
            raise HTTPException(409,'Turno activo, origen y célula deben coincidir.')
        if str(data['operator']['id'])!=shift['external_operator_id']:
            raise HTTPException(422,'El operario no coincide con el turno.')
        if data['started_at']<shift['started_at']: raise HTTPException(422,'La pieza precede al inicio del turno.')
        previous=db.real_iterations.find_one({'cell_id':data['cell_id']},sort=[('iteration_id',-1)])
        if previous and data['started_at']<(previous.get('ended_at') or previous['started_at']):
            raise HTTPException(409,'El inicio solapa una iteración anterior o llega fuera de orden.')
        if previous and previous['status']=='active':
            last=db.real_samples.find_one({'iteration_id':previous['iteration_id']},sort=[('captured_at',-1)])
            if last and last['captured_at']>data['started_at']: raise HTTPException(409,'Hay muestras posteriores al nuevo inicio.')
            db.real_iterations.update_one({'_id':previous['_id']},{'$set':mark({'status':'completed',
                'ended_at':data['started_at'],'completion_reason':'next_iteration_started','auto_closed':True})})
        oid=mirror_operator(data['source_id'],data['operator'])
        row={'_id':key,**mark(data),'iteration_id':next_id('iteration'),'operator_id':oid,
            'external_operator_id':str(data['operator']['id']),'status':'active','ended_at':None,
            'summary_received':False,'completion_reason':None,'created_at':now(),'start_digest':fingerprint,
            'policies':clean(db.config.find_one({'_id':'real-settings'})),'context':task_context(),
            'sample_count':0,'video_status':'missing'}
        db.real_iterations.insert_one(row)
    return public(row)


@router.post('/iterations/{iteration_id}/summary',response_model=IterationRead,summary='Close an iteration on Quality Check, error or cancellation')
def iteration_summary(iteration_id:int,request:Request,body:Summary):
    auth.editor(request); data=encoded(body); initial=get_iteration(iteration_id)
    with lock('cell:'+initial['cell_id']):
        row=get_iteration(iteration_id)
        if row.get('end_digest'):
            if row['end_digest']!=digest(data): raise HTTPException(409,'El resumen ya contiene otros datos.')
        else:
            if data['ended_at']<row['started_at']: raise HTTPException(422,'El fin precede al inicio de la pieza.')
            last=db.real_samples.find_one({'iteration_id':iteration_id},sort=[('captured_at',-1)])
            if last and last['captured_at']>data['ended_at']: raise HTTPException(422,'Hay muestras posteriores al cierre solicitado.')
            following=db.real_iterations.find_one({'cell_id':row['cell_id'],'iteration_id':{'$gt':iteration_id}},sort=[('iteration_id',1)])
            shift=get_shift(row['shift_id'])
            boundary=following['started_at'] if following else shift.get('ended_at')
            if boundary and data['ended_at']>boundary: raise HTTPException(409,'El fin solapa la siguiente pieza o supera el turno.')
            action_ids=[a['event_id'] for a in data['actions']]
            if len(set(action_ids))!=len(action_ids): raise HTTPException(422,'event_id repetido dentro del resumen.')
            if any(not row['started_at']<=a['observed_at']<=data['ended_at'] for a in data['actions']):
                raise HTTPException(422,'Las acciones deben estar dentro del intervalo de la pieza.')
            fields=mark({'status':data['status'],'ended_at':data['ended_at'],'completion_reason':data['completion_reason'],
                'summary':data,'end_digest':digest(data),'summary_received':True,'summary_received_at':now()})
            db.real_iterations.update_one({'_id':row['_id']},{'$set':fields}); row.update(fields)
        # Reconcile these on duplicate too if a process stopped after saving the summary.
        for action in data['actions']:
            db.real_actions.update_one({'_id':f'{iteration_id}:{action["event_id"]}'},{'$setOnInsert':mark({**action,
                'iteration_id':iteration_id,'shift_id':row['shift_id'],'operator_id':row['operator_id']})},upsert=True)
    return public(row)


@router.get('/iterations',response_model=list[IterationRead])
def iterations(request:Request,shift_id:int=None,operator_id:str=None,label:str=None,status:str=None,
               before_id:int=None,limit:int=Query(100,ge=1,le=500)):
    auth.principal(request,device=True); query={}
    for key,value in (('shift_id',shift_id),('operator_id',operator_id),('label',label),('status',status)):
        if value is not None: query[key]=value
    if before_id is not None: query['iteration_id']={'$lt':before_id}
    return [public(i) for i in db.real_iterations.find(query,{'summary':0,'context':0}).sort('iteration_id',-1).limit(limit)]


@router.get('/iterations/{iteration_id}',response_model=IterationRead)
def iteration_detail(iteration_id:int,request:Request):
    auth.principal(request,device=True); row=get_iteration(iteration_id)
    return {**public(row),'sample_count':db.real_samples.count_documents({'iteration_id':iteration_id}),
        'analyses':[public(j) for j in db.real_jobs.find({'iteration_id':iteration_id}).sort('created_at',-1)],
        'video_analyses':clean(list(db.vision_jobs.find({'iteration_id':iteration_id,'deleted':{'$ne':True}},{'context':0,'model_manifest':0}).sort('created_at',-1)))}


@router.patch('/iterations/{iteration_id}',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def label_iteration(iteration_id:int,request:Request,body:LabelUpdate):
    auth.admin(request); row=get_iteration(iteration_id)
    db.real_iterations.update_one({'_id':row['_id']},{'$set':mark(encoded(body))})
    return public(get_iteration(iteration_id))


def write_atomic(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uid('tmp'))
    try:
        with temp.open('xb') as handle:
            handle.write(data);handle.flush();os.fsync(handle.fileno())
        temp.replace(path)
        descriptor=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        temp.unlink(missing_ok=True)


@router.post('/iterations/{iteration_id}/update_sample',status_code=202,response_model=SampleReceipt,
    summary='Store one ROS pose and its JPEG; processing is manual by default')
async def update_sample(iteration_id:int,request:Request,
    metadata:str=Form(description='JSON matching Sample. Schema: GET /api/v1/real/contracts/sample',
        json_schema_extra={'contentMediaType':'application/json','contentSchema':{'$ref':'#/components/schemas/RealSample'}}),
    image:UploadFile=File(description='JPEG from the exact pose frame, up to 8 MiB')):
    await run_in_threadpool(auth.editor,request)
    if len(metadata)>1024**2: raise HTTPException(413,'Metadatos limitados a 1 MiB.')
    try: data=encoded(Sample.model_validate_json(metadata))
    except ValidationError as error:
        raise HTTPException(422,[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in error.errors()])
    raw=await image.read(MAX_IMAGE+1); await image.close()
    if len(raw)>MAX_IMAGE: raise HTTPException(413,'JPEG limitado a 8 MiB.')
    return await run_in_threadpool(persist_sample,iteration_id,data,raw)


def persist_sample(iteration_id,data,raw):
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            if decoded.format!='JPEG' or decoded.size!=(data['image_width'],data['image_height']):
                raise ValueError()
            decoded.verify()
    except (ValueError,UnidentifiedImageError,OSError,Image.DecompressionBombError):
        raise HTTPException(422,'JPEG inválido o dimensiones distintas de los metadatos.')
    sha=hashlib.sha256(raw).hexdigest(); fingerprint=digest({'metadata':data,'image_sha256':sha})
    key=f'{iteration_id}:{data["sequence"]}'; old=db.real_samples.find_one({'_id':key})
    if old:
        if old['digest']!=fingerprint: raise HTTPException(409,'Secuencia reutilizada con otra pose o imagen.')
        return JSONResponse({'status':'duplicate','durable':True,'iteration_id':iteration_id,'shift_id':old['shift_id'],
            'sequence':data['sequence']},status_code=200)
    iteration=get_iteration(iteration_id)
    # Serialize the final boundary check with lifecycle changes; disk I/O is outside the cell lock.
    path=Path('real')/str(iteration['shift_id'])/str(iteration_id)/(str(data['sequence'])+'-'+sha+'.jpg')
    write_atomic(MEDIA/path,raw)
    with lock('cell:'+iteration['cell_id']):
        iteration=get_iteration(iteration_id)
        if data['captured_at']<iteration['started_at'] or (iteration.get('ended_at') and data['captured_at']>iteration['ended_at']):
            raise HTTPException(422,'El frame está fuera del intervalo de la iteración.')
        record={'_id':key,**mark(data),'iteration_id':iteration_id,'shift_id':iteration['shift_id'],
            'operator_id':iteration['operator_id'],'source_id':iteration['source_id'],'cell_id':iteration['cell_id'],
            'image_path':str(path),'image_sha256':sha,'image_size_bytes':len(raw),'digest':fingerprint,'received_at':now()}
        try: db.real_samples.insert_one(record)
        except DuplicateKeyError:
            old=db.real_samples.find_one({'_id':key})
            if not old or old['digest']!=fingerprint: raise HTTPException(409,'Secuencia duplicada con otros datos.')
            return JSONResponse({'status':'duplicate','durable':True,'iteration_id':iteration_id,
                'shift_id':iteration['shift_id'],'sequence':data['sequence']},status_code=200)
        fields={}
        if iteration['policies']['ros_metrics_mode']=='live': fields['live_pending']=True
        db.real_iterations.update_one({'_id':iteration['_id']},{'$inc':{'sample_count':1},
            '$max':{'last_sample_at':data['captured_at']},'$set':mark(fields)})
    return {'status':'accepted','durable':True,'iteration_id':iteration_id,'shift_id':iteration['shift_id'],
        'sequence':data['sequence'],'processing':'not_requested' if iteration['policies']['ros_metrics_mode']=='manual' else 'policy'}


@router.get('/real/contracts/sample',summary='JSON Schema for the update_sample metadata field')
def sample_contract(request:Request):
    auth.principal(request,device=True)
    return Sample.model_json_schema()


@router.get('/iterations/{iteration_id}/samples',response_model=list[SampleRead])
def samples(iteration_id:int,request:Request,after_sequence:int=-1,limit:int=Query(100,ge=1,le=1000)):
    auth.principal(request,device=True); get_iteration(iteration_id)
    return [public(s) for s in db.real_samples.find({'iteration_id':iteration_id,'sequence':{'$gt':after_sequence}}).sort('sequence',1).limit(limit)]


@router.get('/iterations/{iteration_id}/samples/{sequence}/image',summary='Download original JPEG: administrators only',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def sample_image(iteration_id:int,sequence:int,request:Request):
    auth.admin(request); row=db.real_samples.find_one({'iteration_id':iteration_id,'sequence':sequence})
    if not row or not (MEDIA/row['image_path']).is_file(): raise HTTPException(404,'Imagen no disponible.')
    return FileResponse(MEDIA/row['image_path'],media_type='image/jpeg')


@router.post('/iterations/{iteration_id}/video/uploads',status_code=201,summary='Prepare a resumable MP4 upload')
def start_video(iteration_id:int,request:Request,body:VideoStart):
    actor=auth.editor(request); data=encoded(body); row=get_iteration(iteration_id)
    with lock('video:'+str(iteration_id)):
        aid='video-real-'+str(iteration_id); old=db.vision_assets.find_one({'_id':aid})
        if old:
            if old['upload_manifest']!=data: raise HTTPException(409,'Esta iteración ya tiene otro manifiesto de vídeo.')
            db.real_iterations.update_one({'_id':row['_id']},{'$set':mark({'video_asset_id':aid,'video_status':old['status']})})
            return JSONResponse(public(old),status_code=200)
        path=f'uploads/{aid}/original.mp4'; file=inside(VISION,path)
        file.parent.mkdir(parents=True,exist_ok=True)
        # A failed initial call can leave an empty file before the DB document exists.
        if not file.exists(): file.touch()
        asset={'_id':aid,'asset_id':aid,'name':f'Iteración {iteration_id}.mp4','source':'upload','origin':'real',
            'shift_id':row['shift_id'],'iteration_id':iteration_id,'operator_id':row['operator_id'],
            'path':path,'status':'uploading','size_bytes':data['size_bytes'],'uploaded_bytes':0,
            'upload_manifest':data,'created_at':now(),'created_by':actor['username'],'deleted':False}
        db.vision_assets.insert_one(asset)
        db.real_iterations.update_one({'_id':row['_id']},{'$set':mark({'video_asset_id':aid,'video_status':'uploading'})})
    return public({k:v for k,v in asset.items() if k!='path'})


@router.put('/iterations/{iteration_id}/video',summary='Upload an MP4 block at the exact offset; maximum 8 MiB',
    openapi_extra={'requestBody':{'required':True,'content':{'video/mp4':{'schema':{'type':'string','format':'binary'}}}}})
async def video_chunk(iteration_id:int,request:Request,offset:int=Query(ge=0)):
    await run_in_threadpool(auth.editor,request)
    raw=bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw)>MAX_BLOCK: raise HTTPException(413,'Bloque limitado a 8 MiB.')
    if not raw: raise HTTPException(422,'Bloque vacío.')
    return await run_in_threadpool(persist_video_chunk,iteration_id,offset,raw)


def persist_video_chunk(iteration_id,offset,raw):
    get_iteration(iteration_id)
    with lock('video:'+str(iteration_id)):
        asset=get_asset('video-real-'+str(iteration_id)); path=inside(VISION,asset['path'])
        if offset<asset['uploaded_bytes'] and offset+len(raw)<=asset['uploaded_bytes']:
            with path.open('rb') as handle:
                handle.seek(offset)
                if handle.read(len(raw))!=raw: raise HTTPException(409,'El bloque ya guardado contiene otros bytes.')
            return {'status':'duplicate','uploaded_bytes':asset['uploaded_bytes']}
        if asset['status']!='uploading' or offset!=asset['uploaded_bytes']:
            raise HTTPException(409,{'message':'Desplazamiento incorrecto.','uploaded_bytes':asset['uploaded_bytes']})
        if offset+len(raw)>asset['size_bytes']: raise HTTPException(422,'El bloque supera el tamaño declarado.')
        with path.open('r+b') as handle:
            handle.seek(offset);handle.write(raw);handle.truncate();handle.flush();os.fsync(handle.fileno())
        db.vision_assets.update_one({'_id':asset['_id']},{'$set':{'uploaded_bytes':offset+len(raw)}})
    return {'status':'accepted','uploaded_bytes':offset+len(raw)}


@router.post('/iterations/{iteration_id}/video/complete',summary='Verify size and SHA-256 and complete the MP4 upload')
def complete_video(iteration_id:int,request:Request):
    auth.editor(request); row=get_iteration(iteration_id)
    with lock('video:'+str(iteration_id)):
        asset=get_asset('video-real-'+str(iteration_id)); path=inside(VISION,asset['path'])
        if asset['uploaded_bytes']!=asset['size_bytes'] or path.stat().st_size!=asset['size_bytes']:
            raise HTTPException(409,'El vídeo todavía está incompleto.')
        with path.open('rb') as stream:
            header=stream.read(12);stream.seek(0);sha=hashlib.file_digest(stream,'sha256').hexdigest()
        if len(header)<12 or header[4:8]!=b'ftyp': raise HTTPException(422,'Se requiere un contenedor MP4 con cabecera ftyp.')
        if sha!=asset['upload_manifest']['sha256']: raise HTTPException(422,'SHA-256 del MP4 incorrecto.')
        db.vision_assets.update_one({'_id':asset['_id']},{'$set':{'status':'ready','sha256':sha,'completed_at':now()}})
        db.real_iterations.update_one({'_id':row['_id']},{'$set':mark({'video_status':'ready'})})
    return {'iteration_id':iteration_id,'shift_id':row['shift_id'],'status':'ready','sha256':sha,
        'processing':'not_requested' if row['policies']['video_analysis_mode']=='manual' else 'policy'}


@router.get('/iterations/{iteration_id}/video',summary='Download original MP4: administrators only',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def original_video(iteration_id:int,request:Request):
    auth.admin(request); get_iteration(iteration_id); asset=get_asset('video-real-'+str(iteration_id))
    if asset['status']!='ready': raise HTTPException(409,'Vídeo incompleto.')
    return FileResponse(inside(VISION,asset['path']),media_type='video/mp4',filename=asset['name'])


def request_analyses(row,data,actor):
    fingerprint=digest(data); stamp=now(); result=[]
    for source in data['sources']:
        key=key_for('analysis',str(row['iteration_id']),data['client_analysis_id']+':'+source)
        old=db.real_jobs.find_one({'_id':key})
        if old and old['digest']!=fingerprint:
            raise HTTPException(409,'client_analysis_id reutilizado con otras opciones.')
    # Validate every requested source before scheduling any of them.
    if 'video' in data['sources']:
        asset=get_asset(row.get('video_asset_id','missing'))
        if asset['status']!='ready': raise HTTPException(409,'Termina la subida del MP4 antes de analizarlo.')
    for source in data['sources']:
        key=key_for('analysis',str(row['iteration_id']),data['client_analysis_id']+':'+source)
        old=db.real_jobs.find_one({'_id':key})
        if old:
            if old['digest']!=fingerprint: raise HTTPException(409,'client_analysis_id reutilizado con otras opciones.')
            result.append(public(old));continue
        job={'_id':key,'analysis_id':key,'iteration_id':row['iteration_id'],'shift_id':row['shift_id'],
            'operator_id':row['operator_id'],'cell_id':row['cell_id'],'source':source,'status':'queued',
            'created_at':stamp,'requested_by':actor['username'],'digest':fingerprint,'options':data,
            'cutoff_at':stamp,'cursor':-1,'processed_frames':0,'evaluable_frames':0,'context':row['context'],'error':None}
        db.real_jobs.insert_one(mark(job));result.append(public(job))
    return result


@router.post('/iterations/{iteration_id}/analyses',status_code=202,response_model=list[AnalysisRead],summary='Request ROS metrics and/or GPU analysis of the MP4',openapi_extra={'security':[{'APIKeyCookie':[]}]})
def analyze(iteration_id:int,request:Request,body:AnalysisRequest):
    actor=auth.admin(request); row=get_iteration(iteration_id); data=encoded(body)
    with lock('analysis:'+str(iteration_id)):
        return request_analyses(row,data,actor)


@router.get('/iterations/{iteration_id}/analyses/{analysis_id}/results')
def analysis_results(iteration_id:int,analysis_id:str,request:Request,after_sequence:int=-1,
                     limit:int=Query(1000,ge=1,le=5000)):
    auth.principal(request,device=True); get_iteration(iteration_id)
    job=db.real_jobs.find_one({'_id':analysis_id,'iteration_id':iteration_id})
    if not job: raise HTTPException(404,'Análisis no encontrado.')
    if job['source']=='video':
        rows=db.vision_results.find({'job_id':job.get('vision_job_id'),'sequence':{'$gt':after_sequence}}).sort('sequence',1).limit(limit)
    else:
        rows=db.real_results.find({'analysis_id':analysis_id,'sequence':{'$gt':after_sequence}}).sort('sequence',1).limit(limit)
    # Native video keypoints/frames remain in administrator-only vision routes.
    return {'analysis':public(job),'samples':[{'sequence':r['sequence'],'video_time_s':r.get('video_time_s',r.get('offset_s')),
        'captured_at':r.get('captured_at'),'metrics':r['metrics']} for r in rows]}
