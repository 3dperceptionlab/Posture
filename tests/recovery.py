"""Fixture for scripts/test_recovery; uses only a dedicated QA session."""
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
import httpx
from backend.store import ROOT

statefile=Path('/tmp/posture-recovery.json')
c=httpx.Client(base_url='http://api:8080',timeout=20)
c.post('/api/v1/auth/login',json={'username':os.environ['POSTURE_ADMIN_USER'],'password':os.environ['POSTURE_ADMIN_PASSWORD']}).raise_for_status()
mode=sys.argv[1]
if mode=='prepare':
    profile=json.loads((ROOT/'examples/operator-profile.json').read_text())
    r=c.post('/api/v1/operators',json={**profile,'display_name':'QA recuperación'});r.raise_for_status();operator=r.json()
    r=c.post('/api/v1/sessions',json={'operator_id':operator['operator_id'],'name':'QA recuperación','condition':'laboratory'});r.raise_for_status()
    statefile.write_text(json.dumps({'operator':operator,'session':r.json()}))
elif mode=='send':
    saved=json.loads(statefile.read_text());s=saved['session'];p=json.loads((ROOT/'examples/telemetry.json').read_text())
    stamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')
    p.update(message_id=s['session_id']+':offline',source_id='qa-recovery',boot_id=s['session_id'],sequence=1,
             session_id=s['session_id'],operator_id=s['operator_id'],study_id=None,emitted_at=stamp)
    p['pose'].update(observed_at=stamp,frame_id=s['session_id']+':frame',cycle_id=None)
    p['robot'].update(observed_at=stamp,cycle_id=None)
    p['table']['observed_at']=stamp
    p['frame'].update(captured_at=stamp,frame_id=p['pose']['frame_id'],retention_mode='transient')
    r=c.post('/api/v1/ingest',json=p);r.raise_for_status();assert r.status_code==202
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        sample=c.get('/api/v1/sessions/'+s['session_id']+'/timeline').json()['samples'][0]
        if sample['metrics']:
            assert not sample['archived']
            print('PASS: accepted durably and metrics available while CrateDB is stopped')
            break
        time.sleep(.3)
    else:raise AssertionError('Metrics blocked by historian outage')
elif mode=='verify':
    s=json.loads(statefile.read_text())['session'];deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        sample=c.get('/api/v1/sessions/'+s['session_id']+'/timeline').json()['samples'][0]
        if sample['archived']:
            print('PASS: pending original archived after CrateDB recovery')
            break
        time.sleep(.5)
    else:raise AssertionError('Original not archived after recovery')
elif mode=='cleanup':
    if statefile.exists():
        saved=json.loads(statefile.read_text());c.delete('/api/v1/operators/'+saved['operator']['operator_id']).raise_for_status();statefile.unlink()
