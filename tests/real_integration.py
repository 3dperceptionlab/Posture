"""End-to-end production acquisition; all fixtures use a private QA source/cell."""
import copy
import hashlib
import io
import json
import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

import httpx
from PIL import Image

from backend.store import db, ROOT, MEDIA
from backend.vision_common import VISION
from tests.test_real import sample_fixture


def run():
    base=os.getenv('POSTURE_TEST_URL','http://api:8080')
    admin=httpx.Client(base_url=base,timeout=30)
    device=httpx.Client(base_url=base,timeout=30,headers={'Authorization':'Bearer '+os.environ['POSTURE_INGEST_TOKEN']})
    source='qa-real-'+uuid.uuid4().hex[:12];cell=source;shift_ids=[];iteration_ids=[];checks=[];viewer_name=None
    origin=datetime.now(timezone.utc)-timedelta(minutes=2)
    stamp=lambda seconds:(origin+timedelta(seconds=seconds)).isoformat(timespec='microseconds').replace('+00:00','Z')
    def check(label,condition):
        if not condition: raise AssertionError(label)
        checks.append(label)
    def post(path,data,client=device,expected=(200,201,202)):
        r=client.post('/api/v1'+path,json=data)
        if r.status_code not in expected: raise AssertionError(f'{path}: {r.status_code} {r.text[:1200]}')
        return r.json()
    def wait_for(fn,label):
        until=time.monotonic()+90
        while time.monotonic()<until:
            value=fn()
            if value:return value
            time.sleep(.3)
        raise AssertionError('Timeout: '+label)
    def assessment(phase):
        return {'form_id':settings['assessment_form_id'],'submitted_at':stamp(0 if phase=='pre' else 20),'answers':{}}
    def start_piece(n):
        row=post('/iterations',{'source_id':source,'cell_id':cell,'client_iteration_id':str(n),
            'shift_id':shift['shift_id'],'started_at':stamp(n*3),'operator':operator,'robot_assisted':True})
        iteration_ids.append(row['iteration_id']);return row
    def sample(row,sequence=0,unknown=False):
        data=sample_fixture();data.update(sequence=sequence,captured_at=row['started_at'],frame_id=f'frame-{row["iteration_id"]}-{sequence}',video_time_s=0)
        if unknown:
            for j in data['pose']['joints'].values(): j['image_xy_px']=None
        response=device.post(f'/api/v1/iterations/{row["iteration_id"]}/update_sample',
            data={'metadata':json.dumps(data)},files={'image':('frame.jpg',jpeg,'image/jpeg')})
        return response,data
    def upload(row):
        manifest={'size_bytes':len(mp4),'sha256':hashlib.sha256(mp4).hexdigest(),'recorded_at':row['started_at']}
        result=post(f'/iterations/{row["iteration_id"]}/video/uploads',manifest)
        cut=len(mp4)//2
        url=f'/api/v1/iterations/{row["iteration_id"]}/video'
        first=device.put(url+'?offset=0',content=mp4[:cut]);check('MP4 first block accepted',first.status_code==200)
        retry=device.put(url+'?offset=0',content=mp4[:cut]);check('MP4 block retry idempotent',retry.json()['status']=='duplicate')
        check('incomplete MP4 cannot finish',device.post(url+'/complete').status_code==409)
        check('incorrect offset rejected',device.put(url+'?offset=1',content=b'bad').status_code==409)
        second=device.put(url+'?offset='+str(cut),content=mp4[cut:]);check('MP4 second block accepted',second.status_code==200)
        result=post(f'/iterations/{row["iteration_id"]}/video/complete',{})
        check('MP4 verified with SHA-256',result['sha256']==manifest['sha256']);return result
    def done(iid):
        jobs=list(db.real_jobs.find({'iteration_id':iid}))
        if any(j['status']=='failed' for j in jobs): raise AssertionError(str([(j['source'],j['error']) for j in jobs]))
        return jobs if jobs and all(j['status']=='completed' for j in jobs) else None
    try:
        check('anonymous acquisition read denied',admin.get('/api/v1/iterations').status_code==401)
        check('admin login',admin.post('/api/v1/auth/login',json={'username':os.environ['POSTURE_ADMIN_USER'],
            'password':os.environ['POSTURE_ADMIN_PASSWORD']}).status_code==200)
        settings=device.get('/api/v1/real/settings').json()
        check('production defaults manual',settings['ros_metrics_mode']=='manual' and settings['video_analysis_mode']=='manual')
        operator={'id':42,'name':source,'stature_m':1.75,'profile':{'table_height_m':1.04,'presentation':'hmi-owned'}}
        body={'source_id':source,'cell_id':cell,'client_shift_id':'shift-1','started_at':stamp(0),
              'operator':operator,'assessment':assessment('pre'),'label':'QA'}
        shift=post('/shifts',body);shift_ids.append(shift['shift_id'])
        check('numeric shift ID and HMI snapshot',type(shift['shift_id'])==int and shift['operator']['profile']==operator['profile'])
        check('shift retry returns same ID',post('/shifts',body)['shift_id']==shift['shift_id'])
        check('shift identity conflict rejected',device.post('/api/v1/shifts',json={**body,'label':'different'}).status_code==409)
        check('second active shift denied',device.post('/api/v1/shifts',json={**body,'client_shift_id':'another'}).status_code==409)
        first=start_piece(1)
        check('numeric iteration ID linked to shift',first['shift_id']==shift['shift_id'] and type(first['iteration_id'])==int)
        stream=io.BytesIO();Image.new('RGB',(1920,1080),'#d7e4da').save(stream,'JPEG');jpeg=stream.getvalue()
        response,sample_body=sample(first);check('sample durably accepted',response.status_code==202 and response.json()['durable'])
        repeat,_=sample(first);check('sample retry idempotent',repeat.status_code==200)
        changed={**sample_body,'video_time_s':.1}
        check('sample identity conflict rejected',device.post(f'/api/v1/iterations/{first["iteration_id"]}/update_sample',
            data={'metadata':json.dumps(changed)},files={'image':('frame.jpg',jpeg,'image/jpeg')}).status_code==409)
        wait_for(lambda:db.real_samples.find_one({'iteration_id':first['iteration_id'],'archived_at':{'$exists':True}}),'raw archive')
        check('manual ingestion creates no analysis',db.real_jobs.count_documents({'iteration_id':first['iteration_id']})==0)
        check('manual ingestion creates no metric',db.real_results.count_documents({'iteration_id':first['iteration_id']})==0)
        second=start_piece(2)
        old=device.get(f'/api/v1/iterations/{first["iteration_id"]}').json()
        check('next pickup closes prior iteration',old['status']=='completed' and old['ended_at']==second['started_at'] and old['auto_closed'])
        summary={'ended_at':stamp(5),'completion_reason':'quality_check','actions':[
            {'event_id':'qc-1','type':'quality_check','observed_at':stamp(5),'message':'Comando de voz'}]}
        post(f'/iterations/{first["iteration_id"]}/summary',summary)
        check('summary retry idempotent',post(f'/iterations/{first["iteration_id"]}/summary',summary)['summary_received'])
        check('conflicting summary rejected',device.post(f'/api/v1/iterations/{first["iteration_id"]}/summary',json={**summary,'status':'error'}).status_code==409)
        post(f'/iterations/{second["iteration_id"]}/summary',{'ended_at':stamp(8),'status':'error','completion_reason':'pickup_error'})
        label=admin.patch(f'/api/v1/iterations/{first["iteration_id"]}',json={'label':'QA baseline'})
        check('iteration label editable',label.status_code==200 and label.json()['label']=='QA baseline')
        check('iteration filter by shift/operator/label',len(device.get('/api/v1/iterations',params={
            'shift_id':shift['shift_id'],'operator_id':shift['operator_id'],'label':'QA baseline'}).json())==1)
        mp4=Path('/data/examples/videos/mmpose-demo.mp4').read_bytes()
        upload(first)
        time.sleep(1)
        check('manual video receipt creates no inference',db.vision_jobs.count_documents({'iteration_id':first['iteration_id']})==0)
        check('production originals absent from laboratory',not any(a['asset_id']=='video-real-'+str(first['iteration_id']) for a in admin.get('/api/v1/vision/assets').json()))
        viewer_name=source;password=uuid.uuid4().hex
        post('/users',{'username':viewer_name,'password':password,'role':'viewer'},admin)
        viewer=httpx.Client(base_url=base);viewer.post('/api/v1/auth/login',json={'username':viewer_name,'password':password})
        image_url=f'/api/v1/iterations/{first["iteration_id"]}/samples/0/image';video_url=f'/api/v1/iterations/{first["iteration_id"]}/video'
        check('admin original JPEG accessible',admin.get(image_url).content==jpeg)
        check('admin original MP4 accessible',admin.get(video_url).content==mp4)
        check('viewer originals denied',viewer.get(image_url).status_code==403 and viewer.get(video_url).status_code==403)
        check('ROS originals denied',device.get(image_url).status_code in (401,403) and device.get(video_url).status_code in (401,403))
        check('viewer can query shifts',viewer.get('/api/v1/shifts').status_code==200)
        check('viewer cannot request inference',viewer.post(f'/api/v1/iterations/{first["iteration_id"]}/analyses',json={'client_analysis_id':'denied','sources':['ros']}).status_code==403)
        analysis={'client_analysis_id':'manual-both','sources':['ros','video'],'sample_fps':5,'confidence':.5}
        requested=post(f'/iterations/{first["iteration_id"]}/analyses',analysis,admin)
        check('explicit analysis request schedules two sources',len(requested)==2)
        check('analysis request retry idempotent',[j['analysis_id'] for j in post(f'/iterations/{first["iteration_id"]}/analyses',analysis,admin)]==[j['analysis_id'] for j in requested])
        jobs=wait_for(lambda:done(first['iteration_id']),'manual ROS and GPU analyses')
        check('both analyses produce results',all(j['processed_frames']>0 for j in jobs))
        check('ROS metrics linked to shift',db.real_results.find_one({'iteration_id':first['iteration_id']})['shift_id']==shift['shift_id'])
        check('GPU results linked to shift',db.vision_results.find_one({'iteration_id':first['iteration_id']})['shift_id']==shift['shift_id'])
        check('GPU inbox has real association',db.inbox.find_one({'iteration_id':first['iteration_id']})['shift_id']==shift['shift_id'])
        third=start_piece(3)
        db.real_iterations.update_one({'iteration_id':third['iteration_id']},{'$set':{
            'policies.ros_metrics_mode':'live','policies.video_analysis_mode':'when_ready'}})
        response,_=sample(third,unknown=True);check('unknown 3D sample accepted',response.status_code==202)
        live=wait_for(lambda:db.real_results.find_one({'iteration_id':third['iteration_id']}),'live metrics policy')
        check('unknown conventions produce no fabricated score',live['metrics']['rula'] is None and live['metrics']['geometry']=='unknown_3d_convention')
        check('live metrics run before piece closes',db.real_iterations.find_one({'iteration_id':third['iteration_id']})['status']=='active')
        upload(third)
        check('automatic video waits for closed piece',db.vision_jobs.count_documents({'iteration_id':third['iteration_id']})==0)
        post(f'/iterations/{third["iteration_id"]}/summary',{'ended_at':stamp(11)})
        wait_for(lambda:done(third['iteration_id']),'automatic video after close')
        check('video-ready policy schedules GPU automatically',db.vision_jobs.count_documents({'iteration_id':third['iteration_id']})==1)
        fourth=start_piece(4)
        db.real_iterations.update_one({'iteration_id':fourth['iteration_id']},{'$set':{'policies.ros_metrics_mode':'after_iteration'}})
        sample(fourth);time.sleep(.8)
        check('after-iteration policy does not compute during capture',db.real_results.count_documents({'iteration_id':fourth['iteration_id']})==0)
        post(f'/iterations/{fourth["iteration_id"]}/summary',{'ended_at':stamp(14),'status':'aborted','completion_reason':'operator_cancelled'})
        wait_for(lambda:done(fourth['iteration_id']),'after-iteration metrics')
        check('iteration IDs increase',iteration_ids==sorted(set(iteration_ids)))
        closing={'ended_at':stamp(20),'assessment':assessment('post')}
        end=post(f'/shifts/{shift["shift_id"]}/end',closing)
        check('shift closure stores post questionnaire',end['status']=='completed' and end['end_assessment']['form_id']==settings['assessment_form_id'])
        check('shift closure retry idempotent',post(f'/shifts/{shift["shift_id"]}/end',closing)['shift_id']==shift['shift_id'])
        detail=device.get(f'/api/v1/shifts/{shift["shift_id"]}').json()
        check('pre/post forms queryable together',{a['phase'] for a in detail['assessments']}=={'pre','post'})
        check('shift label editable',admin.patch(f'/api/v1/shifts/{shift["shift_id"]}',json={'label':'QA shift'}).status_code==200)
        config={k:settings[k] for k in ('ros_metrics_mode','video_analysis_mode','sample_fps','confidence','assessment_form_id')}
        check('settings revision conflicts blocked',admin.put('/api/v1/real/settings',json={**config,'expected_revision':settings['revision']+999}).status_code==412)
        schema=admin.get('/openapi.json').json()
        check('OpenAPI documents typed production contracts','RealSample' in schema['components']['schemas'] and 'ShiftStart' in schema['components']['schemas'])
        wait_for(lambda:db.real_shifts.find_one({'shift_id':shift['shift_id'],'archive_dirty':False}),'final shift archive')
        check('all raw samples archived',db.real_samples.count_documents({'shift_id':shift['shift_id'],'archive_dirty':True})==0)
        print(json.dumps({'passed':len(checks),'checks':checks,'source':source,
                         'shift_ids':shift_ids,'iteration_ids':iteration_ids},ensure_ascii=False))
    finally:
        import runpy
        try:
            clean_source=runpy.run_path('/data/project/scripts/cleanup_real_qa.py')['clean_source']
            clean_source(source)
        finally:
            if viewer_name: admin.delete('/api/v1/users/'+viewer_name)


if __name__=='__main__':run()
