"""POSTURE ROS bridge example. Dependency: httpx. No robot-control code.

Keep lifecycle messages, stable client IDs and files in the ROS local queue until
acknowledged. This synchronous helper belongs in a network worker, not a control callback.
"""
import argparse
import hashlib
import json
import logging
import os
import time
from pathlib import Path

import httpx


class PostureClient:
    def __init__(self,base_url,token=None,attempts=5):
        self.http=httpx.Client(base_url=base_url.rstrip('/'),timeout=30,
            headers={'Authorization':'Bearer '+token} if token else {})
        self.attempts=attempts
        self.auth_warning_shown=False

    def request(self,method,path,**kwargs):
        for attempt in range(self.attempts):
            try:
                response=self.http.request(method,'/api/v1'+path,**kwargs)
                warning=response.headers.get('X-POSTURE-Auth-Warning')
                if warning and not self.auth_warning_shown:
                    logging.getLogger(__name__).warning(warning)
                    self.auth_warning_shown=True
                retry=response.status_code in (408,429,500,502,503,504) or (
                    response.status_code==409 and 'retry-after' in response.headers)
                if not retry or attempt==self.attempts-1:
                    response.raise_for_status()
                    return response.json()
                delay=float(response.headers.get('retry-after',min(2**attempt,15)))
            except httpx.TransportError:
                if attempt==self.attempts-1: raise
                delay=min(2**attempt,15)
            time.sleep(min(max(delay,.1),30))

    def start_shift(self,payload):
        return self.request('POST','/shifts',json=payload)

    def start_iteration(self,payload):
        return self.request('POST','/iterations',json=payload)

    def update_sample(self,iteration_id,metadata,jpeg_bytes):
        return self.request('POST',f'/iterations/{iteration_id}/update_sample',
            data={'metadata':json.dumps(metadata,allow_nan=False)},
            files={'image':('frame.jpg',jpeg_bytes,'image/jpeg')})

    def summary(self,iteration_id,payload):
        return self.request('POST',f'/iterations/{iteration_id}/summary',json=payload)

    def upload_video(self,iteration_id,filename,recorded_at):
        path=Path(filename)
        with path.open('rb') as stream:
            sha=hashlib.file_digest(stream,'sha256').hexdigest()
            manifest={'size_bytes':path.stat().st_size,'sha256':sha,'recorded_at':recorded_at}
            upload=self.request('POST',f'/iterations/{iteration_id}/video/uploads',json=manifest)
            offset=upload['uploaded_bytes']
            while offset<manifest['size_bytes']:
                stream.seek(offset);block=stream.read(4*1024**2)
                if not block: raise RuntimeError('El archivo cambió durante la subida.')
                result=self.request('PUT',f'/iterations/{iteration_id}/video?offset={offset}',
                    content=block,headers={'Content-Type':'video/mp4'})
                offset=result['uploaded_bytes']
        return self.request('POST',f'/iterations/{iteration_id}/video/complete')

    def end_shift(self,shift_id,payload):
        return self.request('POST',f'/shifts/{shift_id}/end',json=payload)

    def close(self):
        self.http.close()


def main():
    parser=argparse.ArgumentParser(description='Cliente de ejemplo POSTURE HMI/ROS')
    parser.add_argument('--url',default=os.getenv('POSTURE_URL','http://localhost:8080'))
    parser.add_argument('--token-env',default='POSTURE_INGEST_TOKEN')
    command=parser.add_subparsers(dest='command',required=True)
    command.add_parser('forms')
    for name in ('start-shift','start-iteration'):
        sub=command.add_parser(name);sub.add_argument('json_file')
    for name in ('summary','end-shift'):
        sub=command.add_parser(name);sub.add_argument('id',type=int);sub.add_argument('json_file')
    sub=command.add_parser('sample');sub.add_argument('iteration_id',type=int);sub.add_argument('json_file');sub.add_argument('jpeg')
    sub=command.add_parser('video');sub.add_argument('iteration_id',type=int);sub.add_argument('mp4');sub.add_argument('--recorded-at',required=True)
    args=parser.parse_args();token=os.environ.get(args.token_env)
    client=PostureClient(args.url,token)
    try:
        if args.command=='forms':result=client.request('GET','/assessment-forms')
        elif args.command=='video':result=client.upload_video(args.iteration_id,args.mp4,args.recorded_at)
        else:
            payload=json.loads(Path(args.json_file).read_text())
            if args.command=='start-shift':result=client.start_shift(payload)
            elif args.command=='start-iteration':result=client.start_iteration(payload)
            elif args.command=='summary':result=client.summary(args.id,payload)
            elif args.command=='end-shift':result=client.end_shift(args.id,payload)
            else:result=client.update_sample(args.iteration_id,payload,Path(args.jpeg).read_bytes())
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:client.close()


if __name__=='__main__':main()
