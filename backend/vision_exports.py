"""Single CPU export worker: existing poses -> timestamped overlays -> ZIP64."""
import bisect
import csv
import hashlib
import io
import json
import logging
import math
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw
from pymongo import ReturnDocument

from .store import db, now, clean
from .vision_common import VISION, inside, get_job, get_asset, asset_path
from .vision_export_common import initialize_exports, folder_name, flatten

log=logging.getLogger('posture.exports')
EDGES=[(0,1),(0,2),(1,3),(2,4),(5,6),(5,7),(7,9),(6,8),(8,10),
       (5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16),
       (15,17),(15,19),(16,20),(16,22)]
for base in (91,112):
    for finger in range(5):
        EDGES.append((base,base+1+finger*4))
        EDGES.extend((base+1+finger*4+j,base+2+finger*4+j) for j in range(3))


def update(eid,**values):
    db.vision_exports.update_one({'_id':eid},{'$set':{**values,'updated_at':now()}})


def check(eid):
    if not db.vision_exports.find_one({'_id':eid,'deleted':{'$ne':True}}):
        raise RuntimeError('Exportación eliminada o cancelada.')


def overlay_events(times,samples):
    """Snap each sample to the first actual frame at/after it, never a future pose."""
    events={0:None}
    for row in samples:
        offset=row['offset_s']
        if not math.isfinite(offset): continue
        index=bisect.bisect_left(times,offset-1e-6)
        if index<len(times): events[index]=row
    return sorted(events.items())


def draw_pose(row,cut):
    image=Image.new('RGBA',(1920,1080),(0,0,0,0))
    if not row: return image
    points,scores=row.get('keypoints',[]),row.get('scores',[])
    draw=ImageDraw.Draw(image)
    def usable(i):
        return (i<len(points) and i<len(scores) and scores[i] is not None and scores[i]>=cut
            and len(points[i])==2 and all(math.isfinite(v) and abs(v)<100000 for v in points[i]))
    for a,b in EDGES:
        if usable(a) and usable(b):
            draw.line([tuple(points[a]),tuple(points[b])],fill='#ffcf78' if a>=91 else '#c9ff9c',width=3 if a>=91 else 5)
    for i,point in enumerate(points):
        if not usable(i) or 23<=i<91: continue
        x,y=point; radius=3 if i>=91 else 6
        draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='white',outline='#145a4d',width=2)
    return image


def render_overlay(job,rows,folder,eid):
    source=inside(VISION,job['preview_path'])
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time,pkt_duration_time',
        '-of','json',str(source)],text=True))['frames']
    if not probe: raise RuntimeError('El vídeo de reproducción no contiene frames.')
    times=[float(frame['best_effort_timestamp_time']) for frame in probe]
    origin=times[0];times=[value-origin for value in times]
    if any(b<=a for a,b in zip(times,times[1:])): raise RuntimeError('Timestamps del vídeo inválidos.')
    tail=float(probe[-1].get('pkt_duration_time') or (times[-1]-times[-2] if len(times)>1 else .04))
    end=times[-1]+max(.001,tail)
    events=overlay_events(times,rows)
    lines=['ffconcat version 1.0']
    for n,(index,row) in enumerate(events):
        if n%50==0:check(eid)
        filename=f'pose-{n:06d}.png'
        draw_pose(row,job.get('options',{}).get('confidence',.5)).save(folder/filename)
        stop=times[events[n+1][0]] if n+1<len(events) else end
        lines.extend([f"file '{filename}'",'option framerate 1000000',f'duration {stop-times[index]:.6f}'])
    lines.extend([f"file 'pose-{len(events)-1:06d}.png'",'option framerate 1000000'])
    playlist=folder/'poses.ffconcat';playlist.write_text('\n'.join(lines)+'\n')
    output=folder/'skeleton.mp4'
    command=['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-threads','2','-i',str(source),
        '-f','concat','-safe','0','-i',str(playlist),'-filter_complex_threads','2','-filter_complex',
        '[0:v]setpts=PTS-STARTPTS[base];[1:v]setpts=PTS-STARTPTS[pose];[base][pose]overlay=shortest=1:eof_action=repeat:format=auto',
        '-an','-c:v','libx264','-preset','ultrafast','-crf','23','-pix_fmt','yuv420p','-threads','2','-bf','0',
        '-fps_mode','passthrough','-enc_time_base','1:1000','-video_track_timescale','1000000',
        '-use_editlist','0','-movflags','+faststart',str(output)]
    with (folder/'ffmpeg.log').open('w+') as errors:
        with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=errors) as process:
            start=time.monotonic()
            try:
                while process.poll() is None:
                    check(eid)
                    if time.monotonic()-start>7200: raise RuntimeError('Tiempo de renderizado agotado.')
                    time.sleep(.5)
            except BaseException:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                raise
            if process.returncode:
                errors.seek(0);raise RuntimeError('No se pudo generar el esqueleto: '+errors.read()[-500:])
    return output


def metrics_record(row):
    return {'sequence':row['sequence'],'offset_s':row['offset_s'],
        'source_frame_index':row.get('source_frame_index'),'source_pts_s':row.get('source_pts_s'),
        'timing_version':row.get('timing_version'),'persons_detected':row.get('persons_detected'),
        'selection_confidence':row.get('selection_confidence'),**flatten(row['metrics'],'metrics.')}


def prepare_run(job,folder,eid):
    rows=list(db.vision_results.find({'job_id':job['job_id']},{'_id':0}).sort('offset_s',1))
    with (folder/'data.json').open('w') as stream:
        json.dump({'job':clean(job),'samples':rows},stream,ensure_ascii=False,allow_nan=False)
    columns=list(dict.fromkeys(key for row in rows for key in metrics_record(row)))
    with (folder/'metrics.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns or ['sequence','offset_s'])
        writer.writeheader()
        for row in rows:writer.writerow(metrics_record(row))
    warnings=[]
    if job.get('preview_path') and inside(VISION,job['preview_path']).is_file():
        try:render_overlay(job,rows,folder,eid)
        except Exception as error:
            check(eid)
            (folder/'skeleton.mp4').unlink(missing_ok=True)
            warnings.append(str(error))
    else: warnings.append('No playback video available; skeleton video could not be rendered.')
    return len(rows),warnings


def process(record):
    eid=record['export_id'];workspace=inside(VISION,'exports/'+eid)
    shutil.rmtree(workspace,ignore_errors=True);workspace.mkdir(parents=True)
    temporary=inside(VISION,'exports/'+eid+'.tmp.zip')
    destination=inside(VISION,'exports/'+eid+'.zip')
    entries=[];warnings=[]
    try:
        with zipfile.ZipFile(temporary,'w',allowZip64=True) as archive:
            for index,jid in enumerate(record['job_ids'],1):
                check(eid)
                update(eid,stage=f'Preparando {index}/{len(record["job_ids"])}',progress=(index-1)/len(record['job_ids']))
                entry={'job_id':jid,'files':[],'warnings':[]}
                folder=workspace/'run';shutil.rmtree(folder,ignore_errors=True);folder.mkdir()
                try:
                    job=get_job(jid)
                    if job.get('origin')=='real':raise RuntimeError('Production iteration excluded from laboratory export.')
                    prefix=folder_name(index,job)
                    entry.update(name=job['name'],folder=prefix,status=job['status'],created_at=job['created_at'])
                    update(eid,stage=f'{index}/{len(record["job_ids"])} · {job["name"]}')
                    count,issues=prepare_run(job,folder,eid)
                    entry.update(samples=count);entry['warnings'].extend(issues)
                    for filename in ('data.json','metrics.csv','skeleton.mp4'):
                        file=folder/filename
                        if file.is_file():
                            archive.write(file,prefix+'/'+filename,compress_type=zipfile.ZIP_STORED if filename.endswith('.mp4') else zipfile.ZIP_DEFLATED)
                            entry['files'].append(filename)
                    try:
                        asset=get_asset(job['asset_id'])
                        if asset['status']!='ready':raise RuntimeError('Original recording is incomplete.')
                        original=asset_path(asset)
                        stat=original.stat()
                        filename='original'+original.suffix.lower()
                        archive.write(original,prefix+'/'+filename,compress_type=zipfile.ZIP_STORED)
                        if (original.stat().st_size,original.stat().st_mtime_ns)!=(stat.st_size,stat.st_mtime_ns):
                            raise RuntimeError('The original file changed during export.')
                        entry['files'].append(filename)
                    except Exception as error:entry['warnings'].append(str(error))
                except Exception as error:
                    check(eid);entry['warnings'].append(str(error))
                entries.append(entry)
                warnings.extend(f'{jid}: {message}' for message in entry['warnings'])
                update(eid,completed_runs=index,progress=index/len(record['job_ids']),warnings=warnings)
            manifest={'schema_version':'posture.vision-export.v1','export_id':eid,'created_at':now(),
                'runs':entries,'skipped_active_runs':record.get('skipped_runs',[]),
                'skeleton':'Stored native landmarks overlaid on the normalized video. No inference is rerun. '
                    'Each pose starts at the first real presentation timestamp at/after its sample; missing detections clear the overlay. '
                    'Existing analysis timing/assumptions are retained. Skeleton previews contain no audio.',
                'metrics':'metrics.csv uses seconds relative to video start and flattened metric columns; data.json retains complete pose/metrics/context.'}
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2),compress_type=zipfile.ZIP_DEFLATED)
            table=io.StringIO();writer=csv.DictWriter(table,fieldnames=['job_id','name','folder','status','created_at','samples','warnings'])
            writer.writeheader()
            for entry in entries:writer.writerow({k:json.dumps(entry[k],ensure_ascii=False) if k=='warnings' else entry.get(k) for k in writer.fieldnames})
            archive.writestr('runs.csv',table.getvalue(),compress_type=zipfile.ZIP_DEFLATED)
        check(eid);temporary.replace(destination)
        with destination.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        update(eid,status='completed',active=False,progress=1,stage='ZIP preparado',
            path=str(destination.relative_to(VISION)),size_bytes=destination.stat().st_size,sha256=digest,finished_at=now())
    except Exception as error:
        log.exception('Export %s',eid)
        temporary.unlink(missing_ok=True)
        update(eid,status='failed',active=False,stage='Revisar exportación',error=str(error)[:1000],finished_at=now())
    finally:
        shutil.rmtree(workspace,ignore_errors=True)
        if db.vision_exports.find_one({'_id':eid,'deleted':True}):destination.unlink(missing_ok=True)


def run():
    logging.basicConfig(level=logging.INFO)
    initialize_exports()
    db.vision_exports.update_many({'status':'running','deleted':{'$ne':True}},{'$set':{'status':'queued','stage':'Reanudando exportación'}})
    while True:
        record=db.vision_exports.find_one_and_update({'status':'queued','deleted':{'$ne':True}},
            {'$set':{'status':'running','started_at':now()}},sort=[('created_at',1)],return_document=ReturnDocument.AFTER)
        if record:process(record)
        else:time.sleep(1)


if __name__=='__main__':run()
