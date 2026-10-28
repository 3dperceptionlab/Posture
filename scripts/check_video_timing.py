"""Run: docker compose exec -T vision python - --job ID < scripts/check_video_timing.py

Checks real decoder PTS against every stored sample and both generated previews.
It never mutates the selected job or original video.
"""
import argparse
import json
import subprocess
from pathlib import Path

from backend.store import db
from backend.vision_common import asset_path,VISION


def timestamps(path):
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],text=True))
    result=[float(f['best_effort_timestamp_time']) for f in data['frames']]
    return [t-result[0] for t in result]


def check(job_id):
    job=db.vision_jobs.find_one({'_id':job_id,'deleted':{'$ne':True}})
    if not job or job['status']!='completed':raise AssertionError('El análisis debe estar terminado.')
    source=timestamps(asset_path(db.vision_assets.find_one({'_id':job['asset_id']})))
    samples=list(db.vision_results.find({'job_id':job_id}).sort('offset_s',1))
    assert samples and job['timing_version']=='source-pts-v1'
    errors=[abs(s['offset_s']-source[s['source_frame_index']]) for s in samples]
    assert max(errors)<.00001,(max(errors),'PTS de muestra incorrecto')
    assert samples[-1]['offset_s']>source[-1]-1/job['options']['sample_fps']-.1
    previews={}
    for kind,key in [('mp4','preview_path'),('webm','preview_webm_path')]:
        pts=timestamps(VISION/job[key])
        assert len(pts)==len(source),(kind,len(pts),len(source))
        worst=max(abs(a-b) for a,b in zip(pts,source))
        assert worst<=.00101,(kind,worst)
        previews[kind]={'frames':len(pts),'max_timestamp_error_s':round(worst,9),'last_frame_s':pts[-1]}
    nominal_last=(len(source)-1)/job['source_fps']
    report={'job_id':job_id,'name':job['name'],'source_frames':len(source),
        'source_nominal_fps':job['source_fps'],'source_average_fps':job.get('source_average_fps'),
        'last_source_frame_s':source[-1],'nominal_clock_would_end_at_s':nominal_last,
        'legacy_clock_error_at_end_s':round(source[-1]-nominal_last,6),'analysed_samples':len(samples),
        'last_sample_s':samples[-1]['offset_s'],'max_sample_timestamp_error_s':max(errors),
        'previews':previews}
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True)
    check(parser.parse_args().job)
