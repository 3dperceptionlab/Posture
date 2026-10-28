"""Production jobs run outside HTTP; storage never implies inference."""
import json

from .store import db, now
from .metrics import compute
from .real import get_iteration, get_asset, request_analyses, mark, public
from .vision_common import create_job


def ros_metrics(sample, context):
    pose=sample['pose']; space=pose['space']; converted={}
    known3d=(space['kind'] in ('camera_metric','world_metric') and space['unit'] in ('m','mm')
             and space['axes'] in ('optical','ros'))
    factor=.001 if space['unit']=='mm' else 1
    image_count=0
    for name,joint in pose['joints'].items():
        p=joint.get('position'); xyz=None
        if known3d and p is not None:
            p=[v*factor for v in p]
            xyz=[-p[1],-p[2],p[0]] if space['axes']=='ros' else p
        xy=joint.get('image_xy_px')
        if xy and not (0<=xy[0]<sample['image_width'] and 0<=xy[1]<sample['image_height']): xy=None
        image_count+=int(xy is not None)
        converted[name]={'status':joint['status'],'confidence':joint['confidence'],
            'image_xy_px':xy,'point_3d_m':xyz}
    payload={'pose':{'joints':converted,'space_3d':{'kind':'camera_metric','frame_id':'adapter_optical'} if known3d else None,
        'observed_at':sample['captured_at'],'frame_id':sample['frame_id']}}
    metrics=compute(payload,context)
    if known3d and metrics['geometry']=='optical_3d_unvalidated':
        metrics['geometry']='ros_3d_axis_converted_unvalidated' if space['axes']=='ros' else 'optical_3d_unvalidated'
    if not known3d and not image_count:
        metrics['geometry']='unknown_3d_convention'
        metrics['reason']='No hay coordenadas 2D ni una convención 3D métrica conocida. Se conservan los datos originales.'
    metrics.update(pose_source='ros',estimator={'name':pose['estimator_name'],'version':pose['estimator_version']},
        input_space=space,adapter_version='ros-pose-adapter-v1')
    return metrics


def prepare_archive(sql):
    sql('CREATE TABLE IF NOT EXISTS posture_real_raw (record_id TEXT PRIMARY KEY, record_kind TEXT, shift_id LONG, iteration_id LONG, operator_id TEXT, occurred_at TIMESTAMP WITH TIME ZONE, payload_json TEXT) CLUSTERED INTO 1 SHARDS WITH (number_of_replicas=0)')


def archive_pending(sql,http,orion,publish):
    for collection in ('real_shifts','real_iterations','real_samples','real_actions','real_assessments','real_results','real_forms','real_jobs'):
        pending=list(db[collection].find({'archive_dirty':True}).limit(32))
        bulk=[]
        for row in pending:
            at=row.get('captured_at') or row.get('observed_at') or row.get('submitted_at') or row.get('started_at') or row.get('created_at') or now()
            bulk.append([collection+':'+str(row['_id']),collection,row.get('shift_id'),row.get('iteration_id'),row.get('operator_id'),at,
                         json.dumps(public(row),separators=(',',':'),allow_nan=False)])
        if not bulk: continue
        sql('INSERT INTO posture_real_raw (record_id,record_kind,shift_id,iteration_id,operator_id,occurred_at,payload_json) VALUES (?,?,?,?,?,?,?) ON CONFLICT (record_id) DO UPDATE SET payload_json=excluded.payload_json',bulk_args=bulk)
        for row in pending:
            if collection in ('real_shifts','real_iterations'):
                kind='WorkShift' if collection=='real_shifts' else 'WorkIteration'
                number=row['shift_id'] if collection=='real_shifts' else row['iteration_id']
                entity={'id':f'urn:ngsi-ld:{kind}:{number}','type':kind,'@context':{'@vocab':'urn:posture:'}}
                for field in ('shift_id','iteration_id','operator_id','cell_id','status','label','started_at','ended_at'):
                    if row.get(field) is not None:
                        entity[field]={'type':'Property','value':row[field]}
                http.post(orion+'/ngsi-ld/v1/entityOperations/upsert',json=[entity],headers={'Content-Type':'application/ld+json'}).raise_for_status()
            if collection=='real_results':
                publish({'payload':{'cell_id':row['cell_id'],'message_id':row['_id'],'session_id':None},
                         'shift_id':row['shift_id'],'iteration_id':row['iteration_id'],'pose_source':'ros'},row['metrics'])
            db[collection].update_one({'_id':row['_id'],'archive_token':row['archive_token']},
                {'$set':{'archive_dirty':False,'archived_at':now()}})


def auto_jobs():
    # Policies are frozen at iteration start; laboratory settings are unrelated.
    for iteration in db.real_iterations.find({'$or':[
        {'policies.ros_metrics_mode':'live','$or':[{'status':'active'},{'live_pending':True}]},
        {'policies.ros_metrics_mode':'after_iteration','status':{'$ne':'active'},'auto_ros_scheduled':{'$ne':True}},
        {'policies.video_analysis_mode':'when_ready','status':{'$ne':'active'},'video_status':'ready','auto_video_scheduled':{'$ne':True}}]}).limit(100):
        policies=iteration['policies']; sources=[]
        if policies['ros_metrics_mode']=='live' or (policies['ros_metrics_mode']=='after_iteration' and iteration['status']!='active'):
            sources.append('ros')
        if policies['video_analysis_mode']=='when_ready' and iteration['status']!='active' and iteration['video_status']=='ready':
            sources.append('video')
        for source in sources:
            live=source=='ros' and policies['ros_metrics_mode']=='live'
            if iteration.get('auto_'+source+'_scheduled') and not live: continue
            data={'client_analysis_id':'automatic-'+source,'sources':[source],
                'sample_fps':policies['sample_fps'],'confidence':policies['confidence']}
            jobs=request_analyses(iteration,data,{'username':'production-policy'})
            db.real_iterations.update_one({'_id':iteration['_id']},{'$set':{'auto_'+source+'_scheduled':True}})
            if live:
                state={'continuous':True}
                if iteration.get('live_pending') and jobs[0]['status']=='completed': state['status']='queued'
                db.real_jobs.update_one({'_id':jobs[0]['analysis_id']},{'$set':state})


def process_ros(job):
    iteration=get_iteration(job['iteration_id'])
    query={'iteration_id':job['iteration_id']}
    if not job.get('continuous'):
        query.update(sequence={'$gt':job['cursor']},received_at={'$lte':job['cutoff_at']})
    processed=0
    for sample in db.real_samples.find(query).sort('sequence',1):
        key=job['_id']+':'+str(sample['sequence'])
        if db.real_results.find_one({'_id':key}): continue
        metrics=ros_metrics(sample,job['context'])
        metrics.update(shift_id=job['shift_id'],iteration_id=job['iteration_id'])
        row={'_id':key,'analysis_id':job['_id'],'shift_id':job['shift_id'],'iteration_id':job['iteration_id'],
            'operator_id':job['operator_id'],'cell_id':job['cell_id'],'sequence':sample['sequence'],
            'captured_at':sample['captured_at'],'video_time_s':sample['video_time_s'],'metrics':metrics,
            'created_at':now(),'pose_source':'ros'}
        db.real_results.update_one({'_id':key},{'$setOnInsert':mark(row)},upsert=True)
        db.real_jobs.update_one({'_id':job['_id']},{'$max':{'cursor':sample['sequence']}})
        processed+=1
        if processed>=20: break
    result_count=db.real_results.count_documents({'analysis_id':job['_id']})
    valid=db.real_results.count_documents({'analysis_id':job['_id'],'metrics.rula':{'$ne':None}})
    total=db.real_samples.count_documents(query if job.get('continuous') else {
        'iteration_id':job['iteration_id'],'received_at':{'$lte':job['cutoff_at']}})
    complete=result_count>=total and (not job.get('continuous') or iteration['status']!='active')
    if job.get('continuous') and complete:
        db.real_iterations.update_one({'_id':iteration['_id'],'sample_count':total},{'$set':{'live_pending':False}})
    if processed==0 and job['status']==('completed' if complete else 'running'):
        return
    maxima=list(db.real_results.aggregate([{'$match':{'analysis_id':job['_id']}},
        {'$group':{'_id':None,'rula_max':{'$max':'$metrics.rula'},'reba_max':{'$max':'$metrics.reba'}}}]))
    db.real_jobs.update_one({'_id':job['_id']},{'$set':mark({'status':'completed' if complete else 'running',
        'processed_frames':result_count,'evaluable_frames':valid,'updated_at':now(),'error':None,
        'summary':{k:v for k,v in (maxima[0] if maxima else {}).items() if k!='_id'}})})


def process_video(job):
    iteration=get_iteration(job['iteration_id']); asset=get_asset(iteration['video_asset_id'])
    vision=create_job(asset,{'name':f'Iteración {iteration["iteration_id"]} · servidor',
        'operator_id':iteration['operator_id'],'sample_fps':job['options']['sample_fps'],
        'confidence':job['options']['confidence']},{'username':job['requested_by']},context=job['context'],
        association={'shift_id':iteration['shift_id'],'iteration_id':iteration['iteration_id'],'origin':'real',
            'cell_id':iteration['cell_id'],'recording_started_at':asset['upload_manifest']['recorded_at']},
        job_id='vision-'+job['_id'])
    db.real_jobs.update_one({'_id':job['_id']},{'$set':mark({'vision_job_id':vision['job_id'],
        'status':vision['status'],'processed_frames':vision['processed_frames'],'evaluable_frames':vision['evaluable_frames'],
        'summary':vision.get('summary'),'error':vision.get('error'),'updated_at':now()})})


def step():
    auto_jobs()
    for job in db.real_jobs.find({'status':{'$in':['queued','running','capturing','finalizing']}}).sort('created_at',1).limit(12):
        try:
            if job['source']=='video': process_video(job)
            else: process_ros(job)
        except Exception as error:
            db.real_jobs.update_one({'_id':job['_id']},{'$set':mark({'status':'failed','error':str(error)[:1000],'updated_at':now()})})
