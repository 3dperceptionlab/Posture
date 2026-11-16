"""Durable, administrator-only laboratory export queue (no GPU dependencies)."""
import re

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from .store import db, now, uid, clean
from .vision_common import VISION, inside, TERMINAL


def initialize_exports():
    (VISION/'exports').mkdir(parents=True,exist_ok=True)
    db.vision_exports.create_index('created_at')
    db.vision_exports.create_index('active',unique=True,partialFilterExpression={'active':True})


def public_export(row):
    return clean({k:v for k,v in row.items() if k not in ('path','job_ids','active')})


def get_export(eid):
    row=db.vision_exports.find_one({'_id':eid,'deleted':{'$ne':True}})
    if not row: raise HTTPException(404,'Exportación no disponible.')
    return row


def laboratory_export_jobs():
    """All retained lab jobs, independent of the history page's 100-row limit."""
    jobs=list(db.vision_jobs.find({'deleted':{'$ne':True},'origin':{'$ne':'real'}},
        {'job_id':1,'asset_id':1,'session_id':1,'name':1,'operator_id':1,'table_height_cm':1,
         'status':1,'created_at':1}).sort('created_at',1))
    sessions={row['_id'] for row in db.sessions.find({'_id':{'$in':[j['session_id'] for j in jobs]},
        'deleted':{'$ne':True}},{'_id':1})}
    assets={row['_id']:row for row in db.vision_assets.find({'_id':{'$in':[j['asset_id'] for j in jobs]},
        'deleted':{'$ne':True}},{'capture.camera_index':1,'capture.group_id':1})}
    return [{**job, 'camera_index':assets[job['asset_id']].get('capture',{}).get('camera_index',1)}
            for job in jobs if job['session_id'] in sessions and job['asset_id'] in assets]


def export_candidates():
    jobs=laboratory_export_jobs()
    return {'jobs':clean([job for job in reversed(jobs) if job['status'] in TERMINAL]),
            'active_runs':sum(job['status'] not in TERMINAL for job in jobs)}


def validate_job_ids(job_ids):
    if job_ids is None:return None
    if not isinstance(job_ids,list) or not 1<=len(job_ids)<=5000 or any(
        not isinstance(jid,str) or not 1<=len(jid)<=128 for jid in job_ids):
        raise HTTPException(422,'Selecciona entre 1 y 5.000 ejecuciones válidas en job_ids.')
    return set(job_ids)


def matching_active_export(active,jobs):
    if set(active['job_ids'])==set(jobs):return public_export(active)
    raise HTTPException(409,'Hay otra exportación en curso. Espera a que termine o cancélala antes de crear otro ZIP.')


def request_export(actor,job_ids=None):
    requested=validate_job_ids(job_ids)
    initialize_exports()
    jobs=[]; skipped=[]
    for job in laboratory_export_jobs():
        if requested is not None and job['job_id'] not in requested:continue
        if job['status'] not in TERMINAL:
            skipped.append({'job_id':job['job_id'],'name':job['name'],'status':job['status']})
        else: jobs.append(job['job_id'])
    if requested is not None and set(jobs)!=requested:
        raise HTTPException(409,'Alguna ejecución seleccionada no está disponible o aún no ha terminado. Actualiza la selección.')
    if not jobs: raise HTTPException(409,'No hay análisis terminados para exportar.')
    active=db.vision_exports.find_one({'active':True,'deleted':{'$ne':True}})
    if active:return matching_active_export(active,jobs)
    eid=uid('export')
    row={'_id':eid,'export_id':eid,'status':'queued','active':True,'created_at':now(),
        'created_by':actor['username'],'job_ids':jobs,'scope':'selection' if requested is not None else 'all',
        'total_runs':len(jobs),'completed_runs':0,
        'skipped_runs':skipped,'progress':0,'stage':'En cola','warnings':[],'error':None}
    try: db.vision_exports.insert_one(row)
    except DuplicateKeyError:
        active=db.vision_exports.find_one({'active':True})
        if active:return matching_active_export(active,jobs)
        raise HTTPException(409,'Reintenta la solicitud de exportación.')
    return public_export(row)


def export_path(row):
    return inside(VISION,row.get('path','exports/'+row['export_id']+'.zip'))


def folder_name(index,job):
    name=re.sub(r'[^A-Za-z0-9_-]+','-',job['name']).strip('-')[:70] or 'run'
    return f'{index:03d}-{name}-{job["job_id"]}'


def flatten(value,prefix=''):
    """Lossless scalar columns; lists stay JSON in CSV cells."""
    import json
    result={}
    for key,item in value.items():
        name=prefix+key
        if isinstance(item,dict): result.update(flatten(item,name+'.'))
        elif isinstance(item,list): result[name]=json.dumps(item,ensure_ascii=False,allow_nan=False)
        else: result[name]=item
    return result
