import json
import logging
import os
import time
from datetime import datetime, timezone

import httpx
from pymongo import ReturnDocument
from .store import db, initialize, now, uid, MEDIA
from .metrics import compute

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
ORION=os.getenv('ORION_URL','http://orion:1026')
CRATE=os.getenv('CRATE_URL','http://crate:4200')
QL=os.getenv('QUANTUMLEAP_URL','http://quantumleap:8668')
HTTP=httpx.Client(timeout=5)
CONTEXT={'@vocab':'urn:posture:'}


def sql(stmt,args=None,bulk_args=None):
    response=HTTP.post(CRATE+'/_sql', json={'stmt':stmt,**({'bulk_args':bulk_args} if bulk_args is not None else {'args':args or []})})
    response.raise_for_status()
    result=response.json()
    if any(item.get('error') for item in result.get('results',[])):
        raise RuntimeError('CrateDB rechazó una fila del lote de archivo.')
    return result


def prepare():
    sql('CREATE TABLE IF NOT EXISTS posture_raw (message_id TEXT PRIMARY KEY, session_id TEXT, operator_id TEXT, cell_id TEXT, observed_at TIMESTAMP WITH TIME ZONE, message_type TEXT, payload_json TEXT) CLUSTERED INTO 1 SHARDS WITH (number_of_replicas=0)')
    from .real_processing import prepare_archive
    prepare_archive(sql)
    columns={row[0] for row in sql("SELECT column_name FROM information_schema.columns WHERE table_name='posture_raw' AND table_schema='doc'")['rows']}
    for name in ('shift_id','iteration_id'):
        if name not in columns:
            sql('ALTER TABLE posture_raw ADD COLUMN '+name+' LONG')
    sub={'id':'urn:ngsi-ld:Subscription:posture-metrics','type':'Subscription',
         'entities':[{'type':'ErgonomicObservation'}],
         'watchedAttributes':['sampleId'],
         'notification':{'endpoint':{'uri':QL+'/v2/notify','accept':'application/json'}, 'format':'normalized'},
         '@context':CONTEXT}
    r=HTTP.get(ORION+'/ngsi-ld/v1/subscriptions/'+sub['id'])
    if r.status_code==404:
        r=HTTP.post(ORION+'/ngsi-ld/v1/subscriptions',json=sub,headers={'Content-Type':'application/ld+json'})
    if r.is_error:
        raise RuntimeError(f'Orion subscription {r.status_code}: {r.text[:300]}')
    r.raise_for_status()
    db.system.update_one({'_id':'fiware'}, {'$set':{'ready':True,'checked_at':now(),'error':None}},upsert=True)
    # Reconcile the latest surviving observation after startup or dependency recovery.
    deleted=[s['_id'] for s in db.sessions.find({'deleted':True},{'_id':1})]
    for cell in db.cells.find():
        record=db.inbox.find_one({'cell_id':cell['_id'],'message_type':'telemetry',
                                 'session_id':{'$nin':deleted}},sort=[('observed_at',-1)])
        if record:
            publish(record,db.results.find_one({'_id':record['_id']}))


def publish(record,metrics):
    payload=record['payload']
    cell=payload['cell_id']
    entities=[];markers=[]
    def add(kind,at,values):
        suffix=':'+record['pose_source'] if kind=='ErgonomicObservation' and record.get('pose_source') else ''
        key='context:'+kind+':'+cell+suffix
        previous=db.latest.find_one({'_id':key})
        if previous and previous['observed_at']>at:
            return
        entity={'id':f'urn:ngsi-ld:{kind}:{cell}{suffix}','type':kind,'@context':CONTEXT}
        for name,value in values.items():
            if value is not None:
                entity[name]={'type':'Property','value':value,'observedAt':at}
        entities.append(entity);markers.append((key,at))
    if metrics and metrics['rula'] is not None:
        add('ErgonomicObservation',metrics['observed_at'],{
            'rula':metrics['rula'],'reba':metrics['reba'],'coverage':metrics['coverage'],
            'sampleId':payload['message_id'],'sessionId':payload.get('session_id') or '',
            'status':metrics['status'],'shiftId':record.get('shift_id'),
            'iterationId':record.get('iteration_id'),'poseSource':record.get('pose_source')})
    if payload.get('robot'):
        r=payload['robot']
        add('RobotStation',r['observed_at'],{'jointPositions':r['joint_positions_rad'],
            'tcpPose':r['tcp_pose'],'robotMode':r['robot_mode'],'safetyStatus':r['safety_status'],
            'suctionCommanded':r['suction']['commanded_active'],'sampleId':payload['message_id'],
            'sessionId':payload.get('session_id') or ''})
    if payload.get('table'):
        t=payload['table']
        add('ErgonomicTable',t['observed_at'],{'height':t['height_m'],'state':t['state'],
            'sampleId':payload['message_id'],'sessionId':payload.get('session_id') or ''})
    if not entities:
        return
    response=HTTP.post(ORION+'/ngsi-ld/v1/entityOperations/upsert',json=entities,
                       headers={'Content-Type':'application/ld+json'})
    if response.is_error:
        raise RuntimeError(f'Orion upsert {response.status_code}: {response.text[:300]}')
    response.raise_for_status()
    for key,at in markers:
        db.latest.update_one({'_id':key},{'$set':{'observed_at':at}},upsert=True)


def process(record):
    p=record['payload']
    session=db.sessions.find_one({'_id':p.get('session_id')}) if p.get('session_id') else None
    if session and session.get('deleted'):
        db.inbox.delete_one({'_id':record['_id']})
        return
    if not record.get('processed'):
        metrics=None
        if p['message_type']=='telemetry':
            if p.get('frame'):
                frame=p['frame']
                db.frames.update_one({'_id':frame['frame_id']},{'$setOnInsert':{
                    **frame,'frame_id':frame['frame_id'],'session_id':p.get('session_id'),
                    'operator_id':p.get('operator_id'),'study_id':p.get('study_id'),
                    'status':'pending','path':None}},upsert=True)
            phase=db.events.find_one({'session_id':p.get('session_id'), 'event_type':'phase_started',
                                      'observed_at':{'$lte':record['observed_at']}},sort=[('observed_at',-1)])
            effective=dict(p)
            effective['_phase']=(phase or {}).get('data',{}).get('phase','manual_finishing')
            metrics=compute(effective,record['context'])
            if metrics:
                metrics.update({'_id':p['message_id'],'message_id':p['message_id'],
                    'session_id':p.get('session_id'),'operator_id':p.get('operator_id'),
                    'cell_id':p['cell_id'],'study_id':p.get('study_id'),'processed_at':now()})
                metrics.update({k:record[k] for k in ('shift_id','iteration_id','origin','pose_source') if k in record})
                db.results.replace_one({'_id':p['message_id']},metrics,upsert=True)
                if metrics['rula'] is not None and (metrics['rula']>=5 or metrics['reba']>=8):
                    window=metrics['observed_at'][:15] # bounded groups, retaining interval provenance
                    alert_id=f'{p.get("session_id")}:{window}'
                    db.alerts.update_one({'_id':alert_id},{'$setOnInsert':{
                        'alert_id':alert_id,'session_id':p.get('session_id'),'operator_id':p.get('operator_id'),
                        'observed_at':metrics['observed_at'],'created_at':now(),'acknowledged':False,
                        'message':'Revisar postura: indicador preliminar elevado.',
                        'rula':metrics['rula'],'reba':metrics['reba'],'status':'preliminary_assumed',
                        'rule':'RULA >=5 o REBA >=8 en muestra; revisar distribución y cobertura.'}},upsert=True)
        elif p['message_type']=='event':
            db.events.replace_one({'_id':p['message_id']},{'_id':p['message_id'],**p},upsert=True)
            if p['event_type']=='session_ended' and p.get('session_id'):
                db.sessions.update_one({'_id':p['session_id']},{'$set':{'status':'closed','ended_at':p['observed_at']}})
        elif p['message_type']=='shift_assessment':
            previous=db.assessments.find_one({'_id':p['assessment_id']})
            if previous and previous['message_id']!=p['message_id']:
                from .store import digest
                if digest({k:v for k,v in previous.items() if k!='_id'})!=digest(p):
                    raise ValueError('assessment_id already belongs to another message')
            db.assessments.replace_one({'_id':p['assessment_id']},{'_id':p['assessment_id'],**p},upsert=True)
        elif p['message_type']=='profile_application':
            # A stale confirmation is stored historically but never replaces newer state.
            key=p['cell_id']+':'+p['profile_id']
            previous=db.profile_status.find_one({'_id':key})
            if not previous or previous['requested_revision']<p['requested_revision'] or (
                previous['requested_revision']==p['requested_revision'] and previous['observed_at']<=p['observed_at']):
                db.profile_status.replace_one({'_id':key},{'_id':key,**p},upsert=True)
        db.inbox.update_one({'_id':record['_id']},{'$set':{'processed':True,'processed_at':now()}})
    if not record.get('archived'):
        sql('INSERT INTO posture_raw (message_id,session_id,operator_id,cell_id,observed_at,message_type,payload_json,shift_id,iteration_id) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT (message_id) DO NOTHING',
            [p['message_id'],p.get('session_id'),p.get('operator_id'),p['cell_id'],record['observed_at'],p['message_type'],json.dumps(p,separators=(',',':')),record.get('shift_id'),record.get('iteration_id')])
        db.inbox.update_one({'_id':record['_id']},{'$set':{'archived':True}})
    if not record.get('published'):
        metric=db.results.find_one({'_id':p['message_id']})
        publish(record,metric)
        db.inbox.update_one({'_id':record['_id']},{'$set':{'published':True}})
    db.inbox.update_one({'_id':record['_id']},{'$set':{'pending':False,'error':None,'lease_until':0}})


def cleanup():
    changed=False
    for session in db.sessions.find({'deleted':True,'purged':{'$ne':True}}):
        sid=session['_id']
        for frame in db.frames.find({'session_id':sid}):
            path=frame.get('path')
            if path:
                (MEDIA/path).unlink(missing_ok=True)
        sql('DELETE FROM posture_raw WHERE session_id=?',[sid])
        # QL projects sessionId into a tenant table; discover actual columns before deletion.
        tables=sql("SELECT table_schema,table_name FROM information_schema.columns WHERE column_name='sessionid'")['rows']
        for schema,table in tables:
            if (schema.startswith('mt') or schema=='doc') and table.startswith('et') and table.replace('_','').isalnum():
                sql(f'DELETE FROM "{schema}"."{table}" WHERE sessionid=?',[sid])
        for name in ('inbox','results','events','assessments','frames','alerts'):
            db[name].delete_many({'session_id':sid})
        for kind in ('ErgonomicObservation','RobotStation','ErgonomicTable'):
            entity_id=f'urn:ngsi-ld:{kind}:{session["cell_id"]}'
            r=HTTP.get(ORION+'/ngsi-ld/v1/entities/'+entity_id)
            if r.status_code==200:
                entity=r.json()
                current_session=entity.get('sessionId',entity.get('urn:posture:sessionId',{})).get('value')
                if current_session==sid:
                    HTTP.delete(ORION+'/ngsi-ld/v1/entities/'+entity_id).raise_for_status()
                    db.latest.delete_one({'_id':f'context:{kind}:{session["cell_id"]}'})
        db.sessions.update_one({'_id':sid},{'$set':{'purged':True,'purged_at':now()}})
        changed=True
    expiry=now()
    for frame in db.frames.find({'retention_mode':'transient','expires_at':{'$lt':expiry},'path':{'$ne':None}}):
        (MEDIA/frame['path']).unlink(missing_ok=True)
        db.frames.update_one({'_id':frame['_id']},{'$set':{'path':None,'status':'expired'}})
    return changed


def run():
    initialize()
    prepared=False
    next_prepare=0
    while True:
        try:
            if not prepared and time.time()>=next_prepare:
                try:
                    prepare()
                    prepared=True
                except Exception as exc:
                    next_prepare=time.time()+5
                    logging.warning('FIWARE initialization: %s',str(exc)[:200])
                    db.system.update_one({'_id':'fiware'},{'$set':{'ready':False,'error':str(exc)[:500],'checked_at':now()}},upsert=True)
            for _ in range(100):
                stamp=time.time()
                record=db.inbox.find_one_and_update({'pending':True,'retry_at':{'$lte':stamp},
                    'lease_until':{'$lt':stamp}}, {'$set':{'lease_until':stamp+60}},
                    sort=[('observed_at',1)], return_document=ReturnDocument.AFTER)
                if not record:
                    break
                try:
                    process(record)
                except Exception as exc:
                    tries=record.get('attempts',0)+1
                    db.inbox.update_one({'_id':record['_id']},{'$set':{'lease_until':0,
                        'attempts':tries,'retry_at':time.time()+min(60,2**min(tries,6)),
                        'error':str(exc)[:500]}})
                    logging.warning('Message %s retry %s: %s',record['_id'],tries,str(exc)[:150])
            from .real_processing import step, archive_pending
            step()
            if prepared:
                archive_pending(sql,HTTP,ORION,publish)
            if cleanup():
                prepared=False
                next_prepare=0
            db.system.update_one({'_id':'worker'},{'$set':{'heartbeat':now(),'status':'running','error':None}},upsert=True)
        except Exception as exc:
            logging.warning('Worker dependency: %s',str(exc)[:250])
            db.system.update_one({'_id':'worker'},{'$set':{'heartbeat':now(),'status':'retrying','error':str(exc)[:500]}},upsert=True)
            prepared=False
        time.sleep(.5)


if __name__=='__main__':
    run()
