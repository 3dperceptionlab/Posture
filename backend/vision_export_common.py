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


def request_export(actor):
    initialize_exports()
    active=db.vision_exports.find_one({'active':True,'deleted':{'$ne':True}})
    if active: return public_export(active)
    jobs=[]; skipped=[]
    for job in db.vision_jobs.find({'deleted':{'$ne':True},'origin':{'$ne':'real'}}).sort('created_at',1):
        if not db.sessions.find_one({'_id':job['session_id'],'deleted':{'$ne':True}}): continue
        if job['status'] not in TERMINAL:
            skipped.append({'job_id':job['job_id'],'name':job['name'],'status':job['status']})
        else: jobs.append(job['job_id'])
    if not jobs: raise HTTPException(409,'No hay análisis terminados para exportar.')
    eid=uid('export')
    row={'_id':eid,'export_id':eid,'status':'queued','active':True,'created_at':now(),
        'created_by':actor['username'],'job_ids':jobs,'total_runs':len(jobs),'completed_runs':0,
        'skipped_runs':skipped,'progress':0,'stage':'En cola','warnings':[],'error':None}
    try: db.vision_exports.insert_one(row)
    except DuplicateKeyError:
        active=db.vision_exports.find_one({'active':True})
        if active: return public_export(active)
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
