"""Integration against the running stack. Only removes its own QA session."""
import copy
import io
import json
import os
import time
import uuid
import httpx
from PIL import Image
from backend.store import ROOT

BASE=os.getenv('POSTURE_TEST_URL','http://api:8080')


def run():
    c=httpx.Client(base_url=BASE,timeout=30)
    checks=[]
    def check(label,condition):
        if not condition: raise AssertionError(label)
        checks.append(label)
    check('unauthenticated data denied',c.get('/api/v1/sessions').status_code==401)
    r=c.post('/api/v1/auth/login',json={'username':os.environ['POSTURE_ADMIN_USER'],'password':os.environ['POSTURE_ADMIN_PASSWORD']})
    check('admin login',r.status_code==200)
    suffix=uuid.uuid4().hex[:10]
    profile=json.loads((ROOT/'examples/operator-profile.json').read_text())
    r=c.post('/api/v1/operators',json={**profile,'display_name':'QA '+suffix})
    check('operator creation',r.status_code==201)
    p=r.json();oid=p['operator_id'];pid=p['profile_id']
    study=c.post('/api/v1/studies',json={'name':'QA '+suffix,'description':'Automated integration fixture'}).json()
    r=c.post('/api/v1/sessions',json={'operator_id':oid,'study_id':study['study_id'],'name':'QA '+suffix})
    check('session creation',r.status_code==201)
    session=r.json();sid=session['session_id']
    check('one active session per cell',c.post('/api/v1/sessions',json={'operator_id':oid}).status_code==409)
    m=json.loads((ROOT/'examples/telemetry.json').read_text())
    m.update(message_id='qa-'+suffix,source_id='qa-integration',boot_id=suffix,sequence=1,
        session_id=sid,operator_id=oid,study_id=study['study_id'])
    m['pose']['frame_id']='qa-frame-'+suffix;m['frame']['frame_id']=m['pose']['frame_id']
    for part in ('robot','table'):m[part]['applied_profile_revision']=1
    bad=copy.deepcopy(m);bad['robot']['tcp_pose']['orientation_xyzw']=[0,0,0,0]
    check('bad orientation rejected',c.post('/api/v1/ingest',json=bad).status_code==422)
    check('durable ingestion',c.post('/api/v1/ingest',json=m).status_code==202)
    check('retry idempotent',c.post('/api/v1/ingest',json=m).status_code==200)
    bad=copy.deepcopy(m);bad['robot']['robot_mode']='paused'
    check('reused identity conflict',c.post('/api/v1/ingest',json=bad).status_code==409)
    body={**p,'expected_revision':1,'table_height_m':.97}
    r=c.put('/api/v1/operator-profiles/'+pid,json=body)
    check('profile revision incremented',r.status_code==200 and r.json()['revision']==2)
    check('concurrent edit blocked',c.put('/api/v1/operator-profiles/'+pid,json=body).status_code==412)
    desired=c.get('/api/v1/cells/cell-lab-01/desired-profile')
    check('desired profile exposed to ROS',desired.status_code==200 and desired.json()['revision']==2)
    check('ETag caching',c.get('/api/v1/cells/cell-lab-01/desired-profile',headers={'If-None-Match':desired.headers['etag']}).status_code==304)
    ack=json.loads((ROOT/'examples/profile-application.json').read_text())
    ack.update(message_id='qa-ack-'+suffix,source_id=m['source_id'],boot_id=suffix,sequence=2,
        session_id=sid,operator_id=oid,study_id=study['study_id'],profile_id=pid,requested_revision=2)
    for component in ('robot','table'):ack[component]['applied_revision']=2
    check('applied profile accepted',c.post('/api/v1/ingest',json=ack).status_code==202)
    image=Image.new('RGB',(1920,1080),'#e6eee3');buffer=io.BytesIO();image.save(buffer,'JPEG');raw=buffer.getvalue()
    frame_url='/api/v1/frames/'+m['frame']['frame_id']
    check('study image stored',c.put(frame_url,content=raw,headers={'Content-Type':'image/jpeg'}).status_code==201)
    check('image retry idempotent',c.put(frame_url,content=raw,headers={'Content-Type':'image/jpeg'}).json()['status']=='duplicate')
    check('admin image retrieval',c.get(frame_url).status_code==200)
    second=io.BytesIO();Image.new('RGB',(1920,1080),'red').save(second,'JPEG')
    check('frame content identity protected',c.put(frame_url,content=second.getvalue(),headers={'Content-Type':'image/jpeg'}).status_code==409)
    vname='qa-viewer-'+suffix;vpass=uuid.uuid4().hex
    check('viewer creation',c.post('/api/v1/users',json={'username':vname,'password':vpass,'role':'viewer'}).status_code==201)
    viewer=httpx.Client(base_url=BASE)
    viewer.post('/api/v1/auth/login',json={'username':vname,'password':vpass})
    check('viewer cannot access image',viewer.get(frame_url).status_code==403)
    check('viewer cannot modify profiles',viewer.put('/api/v1/operator-profiles/'+pid,json=body).status_code==403)
    check('viewer can read sessions',viewer.get('/api/v1/sessions').status_code==200)
    device=httpx.Client(base_url=BASE,headers={'Authorization':'Bearer '+os.environ['POSTURE_INGEST_TOKEN']})
    check('ROS can read desired profile',device.get('/api/v1/cells/cell-lab-01/desired-profile').status_code==200)
    check('ROS can read preliminary summary',device.get('/api/v1/cells/cell-lab-01/summary').status_code==200)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        t=c.get('/api/v1/sessions/'+sid+'/timeline').json()
        if t.get('samples') and t['samples'][0]['metrics'] and t['samples'][0]['archived']:break
        time.sleep(.5)
    check('metrics produced',bool(t.get('samples') and t['samples'][0]['metrics']))
    check('canonical CrateDB archive confirmed',t['samples'][0]['archived'])
    check('preliminary label preserved',t['samples'][0]['metrics']['status']=='preliminary_assumed')
    check('CSV export',c.get('/api/v1/sessions/'+sid+'/export.csv').status_code==200)
    check('manual deletion accepted',c.delete('/api/v1/sessions/'+sid).status_code==202)
    check('deleted session immediately inaccessible',c.get('/api/v1/sessions/'+sid+'/timeline').status_code==404)
    new=copy.deepcopy(m);new.update(message_id='qa-late-'+suffix,sequence=3)
    check('late ingest cannot restore deleted session',c.post('/api/v1/ingest',json=new).status_code==404)
    c.delete('/api/v1/studies/'+study['study_id'])
    check('QA account removal',c.delete('/api/v1/users/'+vname).status_code==200)
    check('QA operator removal',c.delete('/api/v1/operators/'+oid).status_code==202)
    print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))


if __name__=='__main__':run()
