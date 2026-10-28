"""One CUDA worker for offline videos and bounded live-frame queues."""
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from pymongo import ReturnDocument

from .store import db, initialize, now, clean, MEDIA
from .vision_common import VISION, TERMINAL, inside, asset_path, telemetry
from .metrics import compute
from .video_timing import PresentationClock, TIMING_VERSION

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('posture.vision')


def normalized(frame):
    """Uniform resize + letterbox: same optical projection, no image stretching."""
    h,w = frame.shape[:2]
    ratio = min(1920/w,1080/h)
    nw,nh = round(w*ratio),round(h*ratio)
    output = np.zeros((1080,1920,3),dtype=np.uint8)
    x,y = (1920-nw)//2,(1080-nh)//2
    output[y:y+nh,x:x+nw] = cv2.resize(frame,(nw,nh),interpolation=cv2.INTER_AREA)
    return output


class Engine:
    def __init__(self):
        cv2.setNumThreads(2)
        ort.preload_dlls(directory='')
        if 'CUDAExecutionProvider' not in ort.get_available_providers():
            raise RuntimeError('ONNX Runtime no encuentra CUDA; no se permite sustituir silenciosamente por CPU.')
        from rtmlib import Wholebody
        self.model = Wholebody(det='/opt/vision-models/detector.onnx',det_input_size=(640,640),
            pose='/opt/vision-models/pose.onnx',pose_input_size=(192,256),
            to_openpose=False,backend='onnxruntime',device='cuda')
        # Validate actual sessions, not only the installed provider list.
        for tool in (self.model.det_model,self.model.pose_model):
            settings = ort.SessionOptions()
            settings.intra_op_num_threads = 2
            settings.inter_op_num_threads = 1
            settings.add_session_config_entry('session.intra_op.allow_spinning','0')
            tool.session = ort.InferenceSession(tool.onnx_model,sess_options=settings,
                providers=[('CUDAExecutionProvider',{'device_id':0})])
            session = getattr(tool,'session',None)
            if session is None or 'CUDAExecutionProvider' not in session.get_providers():
                raise RuntimeError('Una sesión del modelo no ha podido activar CUDA.')
        self.manifest = json.loads(Path('/opt/vision-models/manifest.json').read_text())
        self.predict(np.zeros((1080,1920,3),np.uint8))

    def predict(self,frame):
        start = time.perf_counter()
        boxes = self.model.det_model(frame)
        if boxes is None or len(boxes)==0:
            return [],[],0,0,None,(time.perf_counter()-start)*1000
        # Estimate all detected bodies, then rank reliable bodies by box area.
        points,scores = self.model.pose_model(frame,bboxes=boxes)
        if len(points)==0:
            return [],[],0,0,None,(time.perf_counter()-start)*1000
        confidence = np.nan_to_num(scores[:,:17].mean(axis=1),nan=0)
        areas = np.maximum(0,boxes[:,2]-boxes[:,0])*np.maximum(0,boxes[:,3]-boxes[:,1])
        eligible = [i for i in range(len(points)) if confidence[i]>=.2]
        choice = max(eligible,key=lambda i:(areas[i],confidence[i])) if eligible else int(np.argmax(confidence))
        return (np.nan_to_num(points[choice]).tolist(),np.clip(np.nan_to_num(scores[choice]),0,1).tolist(),
            len(points),float(confidence[choice]),boxes[choice,:4].tolist(),(time.perf_counter()-start)*1000)


def update(jid,**values):
    db.vision_jobs.update_one({'_id':jid},{'$set':{**values,'updated_at':now()}})


def interrupted(job):
    fresh = db.vision_jobs.find_one({'_id':job['job_id']})
    session = db.sessions.find_one({'_id':job['session_id']})
    return not fresh or fresh.get('deleted') or fresh.get('cancel_requested') or not session or session.get('deleted')


def sample(engine,job,frame,sequence,offset,source_frame_index=None,source_pts_s=None):
    key = f'{job["job_id"]}:{sequence}'
    old = db.vision_results.find_one({'_id':key})
    if old: return old
    if interrupted(job): return None
    points,scores,persons,confidence,box,elapsed = engine.predict(frame)
    if interrupted(job): return None
    payload = telemetry(job,sequence,round(offset,6),points,scores)
    # Identical internal contract and durable FIWARE/archive path as ROS, no fake robot.
    from .app import ingest_message
    previous = db.inbox.find_one({'_id':key})
    if previous:
        payload = previous['payload']
    else:
        ingest_message(payload,context=job['context'],association={**job,'pose_source':'server'})
    metrics = compute(payload,job['context'])
    parents={k:job[k] for k in ('shift_id','iteration_id','origin') if k in job}
    if parents:
        metrics.update(**parents,pose_source='server')
    relative = hashlib.sha256(key.encode()).hexdigest()+'.jpg'
    ok,jpeg = cv2.imencode('.jpg',frame,[cv2.IMWRITE_JPEG_QUALITY,82])
    if not ok: raise RuntimeError('No se ha podido guardar el fotograma.')
    raw = jpeg.tobytes()
    temp = MEDIA/(relative+'.tmp')
    temp.write_bytes(raw);temp.replace(MEDIA/relative)
    db.frames.update_one({'_id':key},{'$set':{'path':relative,'status':'available',
        'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw),'expires_at':None}})
    row = {'_id':key,**parents,'job_id':job['job_id'],'session_id':job['session_id'],'sequence':sequence,
        'offset_s':round(offset,6),'persons_detected':persons,'selection_confidence':round(confidence,4),
        'selected_box':box,'inference_ms':round(elapsed,2),'keypoints':points,'scores':scores,
        'joints':payload['pose']['joints'],'metrics':metrics,'processed_at':now()}
    if source_frame_index is not None:
        row.update(source_frame_index=source_frame_index,source_pts_s=source_pts_s,
                   timing_version=TIMING_VERSION)
    db.vision_results.replace_one({'_id':key},row,upsert=True)
    db.vision_jobs.update_one({'_id':job['job_id']},{'$inc':{'processed_frames':1,
        'evaluable_frames':int(metrics['rula'] is not None)},'$set':{'last_offset_s':offset,
        'last_inference_ms':round(elapsed,2),'updated_at':now()}})
    return row


def process_live(engine):
    active = list(db.vision_jobs.find({'mode':'live','status':{'$in':['capturing','finalizing']},
        'deleted':{'$ne':True},'cancel_requested':False},{'_id':1}))
    if not active: return False
    item = db.vision_live.find_one_and_update({'job_id':{'$in':[j['_id'] for j in active]},'status':'pending'},
        {'$set':{'status':'processing'}},sort=[('created_at',1)],return_document=ReturnDocument.AFTER)
    if not item: return False
    job = db.vision_jobs.find_one({'_id':item['job_id']})
    path = inside(VISION,item['path'])
    try:
        frame = cv2.imread(str(path))
        if frame is None: raise RuntimeError('Fotograma de cámara ilegible.')
        sample(engine,job,frame,item['sequence'],item['offset_s'])
        db.vision_live.update_one({'_id':item['_id']},{'$set':{'status':'completed'}})
    except Exception as error:
        db.vision_live.update_one({'_id':item['_id']},{'$set':{'status':'failed','error':str(error)[:500]}})
        raise
    finally:
        path.unlink(missing_ok=True)
    return True


def close_job(job,status,error=None):
    jid = job['job_id']
    count = db.vision_results.count_documents({'job_id':jid})
    valid = db.vision_results.count_documents({'job_id':jid,'metrics.rula':{'$ne':None}})
    maxima = list(db.vision_results.aggregate([{'$match':{'job_id':jid}}, {'$group':{'_id':None,
        'rula_max':{'$max':'$metrics.rula'},'reba_max':{'$max':'$metrics.reba'},
        'mean_inference_ms':{'$avg':'$inference_ms'},'detection_frames':{'$sum':{'$cond':[{'$gt':['$persons_detected',0]},1,0]}}}}]))
    summary = {k:v for k,v in (maxima[0] if maxima else {}).items() if k!='_id'}
    update(jid,status=status,error=error,stage={'completed':'Análisis terminado','cancelled':'Cancelado','failed':'Revisar incidencia'}[status],
        finished_at=now(),processed_frames=count,evaluable_frames=valid,summary=summary,progress=1 if status=='completed' else job.get('progress',0))
    db.sessions.update_one({'_id':job['session_id'],'deleted':{'$ne':True}},
        {'$set':{'status':'closed','ended_at':now()}})


def preview(job):
    asset = db.vision_assets.find_one({'_id':job['asset_id'],'deleted':{'$ne':True}})
    if not asset or asset['status']!='ready': raise RuntimeError('No está disponible el vídeo original.')
    folder = VISION/'jobs'/job['job_id']
    folder.mkdir(parents=True,exist_ok=True)
    output,temp = folder/'preview.mp4',folder/'preview.tmp.mp4'
    webm,webm_temp = folder/'preview.webm',folder/'preview.tmp.webm'
    update(job['job_id'],stage='Preparando reproducción sincronizada')
    command = ['ffmpeg','-hide_banner','-loglevel','error','-nostdin','-y','-i',str(asset_path(asset)),
        '-an','-vf','setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
        '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-threads','4','-bf','0','-movflags','+faststart',
        '-fps_mode','passthrough','-enc_time_base','1:1000','-video_track_timescale','1000000','-use_editlist','0',str(temp),
        '-an','-vf','setpts=PTS-STARTPTS,scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1',
        '-c:v','libvpx-vp9','-deadline','realtime','-cpu-used','6','-crf','34','-b:v','0','-pix_fmt','yuv420p','-threads','4',
        '-fps_mode','passthrough','-enc_time_base','1:1000',str(webm_temp)]
    with subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE) as process:
        start = time.time()
        while process.poll() is None:
            if interrupted(job) or time.time()-start>600:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
                temp.unlink(missing_ok=True)
                webm_temp.unlink(missing_ok=True)
                if interrupted(job): return False
                raise RuntimeError('Tiempo de transcodificación agotado.')
            time.sleep(.2)
        error = process.stderr.read().decode(errors='replace')
        if process.returncode:
            temp.unlink(missing_ok=True)
            webm_temp.unlink(missing_ok=True)
            raise RuntimeError('No se pudo preparar el vídeo: '+error[-600:])
    temp.replace(output)
    webm_temp.replace(webm)
    metadata = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration',
        '-of','json',str(output)],text=True))
    update(job['job_id'],preview_path=str(output.relative_to(VISION)),preview_webm_path=str(webm.relative_to(VISION)),
        duration_s=float(metadata['format']['duration']))
    return True


def process_file(engine,job):
    asset = db.vision_assets.find_one({'_id':job['asset_id'],'deleted':{'$ne':True}})
    if not asset: raise RuntimeError('Original eliminado.')
    source = asset_path(asset)
    initial_stat = source.stat()
    with source.open('rb') as stream:
        source_digest = hashlib.file_digest(stream,'sha256').hexdigest()
    if job.get('processed_frames',0) and job.get('timing_version')!=TIMING_VERSION:
        raise RuntimeError('El análisis parcial usa el reloj anterior. Vuelve a analizar el original para aplicar la sincronización corregida.')
    if job.get('processed_frames',0) and job.get('source_sha256')!=source_digest:
        raise RuntimeError('El original cambió desde el procesamiento anterior. Crea un análisis nuevo.')
    update(job['job_id'],source_sha256=source_digest,source_size_bytes=initial_stat.st_size)
    capture = cv2.VideoCapture(str(source))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        total = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not capture.isOpened() or not math.isfinite(fps) or fps<=0 or fps>240:
            raise RuntimeError('No se puede decodificar el vídeo o su frecuencia no es válida.')
        job.update(source_fps=fps)
        update(job['job_id'],duration_s=None,source_fps=fps,source_width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            source_height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),normalization='letterbox_1920x1080',
            stage='Detectando cuerpo y manos',model_manifest=engine.manifest,provider='CUDAExecutionProvider',
            timing_version=TIMING_VERSION,timestamp_source='decoder_presentation_timestamp')
        effective_fps = min(fps,job['options']['sample_fps'])
        clock = PresentationClock(effective_fps)
        index,sequence,last_offset = 0,0,0.
        while True:
            if interrupted(job): close_job(job,'cancelled');return
            # Camera jobs get service even during a long offline video.
            process_live(engine)
            ok,frame = capture.read()
            if not ok: break
            source_index = index
            source_pts = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            offset,selected = clock.observe(source_pts * 1000)
            index += 1
            last_offset = offset
            if offset>3600: raise RuntimeError('El laboratorio admite clips de hasta una hora.')
            if not selected: continue
            sample(engine,job,normalized(frame),sequence,offset,source_index,source_pts)
            sequence += 1
            if sequence>25000: raise RuntimeError('Límite de fotogramas alcanzado.')
            update(job['job_id'],progress=min(.96,index/total*.96) if total>0 else 0)
        if sequence==0: raise RuntimeError('El archivo no contiene fotogramas decodificables.')
        # Frame count metadata can be derived from a false nominal FPS in VFR
        # recordings, so it must not be used as a corruption/timing check.
        update(job['job_id'],duration_s=last_offset+1/fps,decoded_frames=index,
            source_pts_origin_s=clock.origin_s,last_source_offset_s=last_offset,
            source_average_fps=(index-1)/last_offset if last_offset>0 else fps)
    finally:
        capture.release()
    if (source.stat().st_size,source.stat().st_mtime_ns)!=(initial_stat.st_size,initial_stat.st_mtime_ns):
        raise RuntimeError('El original cambió durante el análisis; vuelve a importarlo para analizar la nueva versión.')
    if interrupted(job) or not preview(job): close_job(job,'cancelled');return
    close_job(job,'completed')


def cleanup():
    for job in db.vision_jobs.find({'status':{'$nin':list(TERMINAL)}}):
        if interrupted(job):
            close_job(job,'cancelled')
        elif job['mode']=='live' and job['status']=='capturing' and time.time()-job.get('last_capture_ts',0)>120:
            # No endless recording jobs after browser crashes. Keep original partial bytes for recovery.
            if time.time()-__import__('datetime').datetime.fromisoformat(job['created_at'].replace('Z','+00:00')).timestamp()>120:
                close_job(job,'failed','La cámara dejó de enviar capturas. El original parcial se conserva en Subidas.')
    for job in db.vision_jobs.find({'deleted':{'$ne':True}}):
        if not db.sessions.find_one({'_id':job['session_id'],'deleted':{'$ne':True}}):
            db.vision_jobs.update_one({'_id':job['_id']},{'$set':{'deleted':True,'cancel_requested':True}})
    for job in db.vision_jobs.find({'deleted':True,'vision_purged':{'$ne':True}}):
        folder = inside(VISION,'jobs/'+job['job_id'])
        shutil.rmtree(folder,ignore_errors=True)
        shutil.rmtree(inside(VISION,'live/'+job['job_id']),ignore_errors=True)
        db.vision_results.delete_many({'job_id':job['job_id']})
        db.vision_live.delete_many({'job_id':job['job_id']})
        db.vision_jobs.update_one({'_id':job['_id']},{'$set':{'vision_purged':True}})


def run():
    initialize()
    db.system.update_one({'_id':'vision'},{'$set':{'status':'loading','error':None,'heartbeat_ts':time.time(),'heartbeat':now()}},upsert=True)
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(5):
            try: db.system.update_one({'_id':'vision'},{'$set':{'heartbeat_ts':time.time(),'heartbeat':now()}})
            except Exception: log.exception('Vision heartbeat')
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        engine = Engine()
        gpu = subprocess.check_output(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],text=True).strip()
        db.system.update_one({'_id':'vision'},{'$set':{'status':'ready','gpu':gpu,'provider':'CUDAExecutionProvider',
            'model_manifest':engine.manifest,'error':None}})
        # One worker instance is configured. Retry deterministic per-frame jobs after restart.
        db.vision_jobs.update_many({'mode':'file','status':'running'},{'$set':{'status':'queued','stage':'Reanudando tras reinicio'}})
        db.vision_live.update_many({'status':'processing'},{'$set':{'status':'pending'}})
        log.info('Vision ready on %s',gpu)
        while True:
            cleanup()
            if process_live(engine): continue
            live = db.vision_jobs.find_one({'mode':'live','status':'finalizing','deleted':{'$ne':True},'cancel_requested':False},sort=[('created_at',1)])
            if live:
                try:
                    if preview(live): close_job(live,'completed')
                    else: close_job(live,'cancelled')
                except Exception as error:
                    log.exception('Live finalization');close_job(live,'failed',str(error)[:1000])
                continue
            job = db.vision_jobs.find_one_and_update({'mode':'file','status':'queued','deleted':{'$ne':True},'cancel_requested':False},
                {'$set':{'status':'running','started_at':now()}},sort=[('created_at',1)],return_document=ReturnDocument.AFTER)
            if job:
                try: process_file(engine,job)
                except Exception as error:
                    log.exception('Video %s',job['job_id']);close_job(job,'failed',str(error)[:1000])
            else: time.sleep(.15)
    except Exception as error:
        db.system.update_one({'_id':'vision'},{'$set':{'status':'failed','error':str(error)[:1000]}})
        raise
    finally:
        stop.set()


if __name__=='__main__':
    if '--health' in sys.argv:
        state = db.system.find_one({'_id':'vision'}) or {}
        sys.exit(0 if state.get('status')=='ready' and time.time()-state.get('heartbeat_ts',0)<45 else 1)
    run()
