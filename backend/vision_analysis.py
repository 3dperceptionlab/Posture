"""Read-only comparisons of retained laboratory analyses; no pose inference."""
from collections import Counter
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request

from . import auth
from .store import db, digest

router = APIRouter(prefix='/api/v1/vision', tags=['Laboratory analytics'])
DIMENSIONS = {'table_height_cm', 'operator_id', 'camera_index', 'condition', 'day'}


def distribution(counts, maximum, threshold):
    counts = {int(k):v for k,v in counts.items() if type(k) is int and 1 <= k <= maximum}
    total = sum(counts.values())
    median = None
    accumulated = 0
    for score in sorted(counts):
        accumulated += counts[score]
        if accumulated >= (total+1)//2:
            median = score
            break
    return {'counts':[counts.get(i,0) for i in range(1,maximum+1)], 'valid_samples':total,
        'median':median, 'peak':max(counts) if total else None,
        'threshold':threshold, 'above_threshold_pct':round(100*sum(n for k,n in counts.items() if k>=threshold)/total,2) if total else None}


def robot_condition(name):
    """Explicit title annotation only; unknown is a genuine third category."""
    name = name.casefold()
    if 'sin robot' in name or 'sin ur' in name:
        return 'without_robot'
    if 'robot' in name or 'con ur' in name:
        return 'with_robot'
    return 'unknown'


def aggregate(jobs, assets, buckets, dimensions):
    by_id = {j['job_id']:j for j in jobs}
    runs = {}
    for bucket in buckets:
        key = bucket['_id']; job = by_id[key['job_id']]
        # Revision alone is insufficient when a context was edited outside the API.
        compatibility = (key.get('algorithm'), key.get('revision'), digest(job.get('context',{})),
            key.get('geometry'), job.get('estimator'), job.get('options',{}).get('sample_fps'),
            job.get('options',{}).get('confidence'))
        rid = (job['job_id'], compatibility)
        if rid not in runs:
            asset = assets.get(job['asset_id'], {})
            capture = asset.get('capture',{})
            runs[rid] = {'job_id':job['job_id'], 'name':job['name'], 'created_at':job['created_at'],
                'operator_id':job.get('operator_id'), 'table_height_cm':job.get('table_height_cm'),
                'table_height_source':job.get('table_height_source','unknown'),
                'camera_index':capture.get('camera_index',1),
                'condition':robot_condition(job['name']), 'day':job['created_at'][:10],
                'capture_id':capture.get('group_id') or job['asset_id'],
                'asset_id':job['asset_id'], 'compatibility':compatibility,
                'context_revision':key.get('revision'), 'algorithm_version':key.get('algorithm'),
                'geometry':key.get('geometry'), 'estimator':job.get('estimator'),
                'sample_fps':job.get('options',{}).get('sample_fps'),
                'confidence':job.get('options',{}).get('confidence'),
                '_rula':Counter(), '_reba':Counter(), 'samples':0}
        run = runs[rid]; run['samples'] += bucket['count']
        for metric in ('rula','reba'):
            value=key.get(metric)
            if type(value) is int:
                run['_'+metric][value] += bucket['count']
    groups = {}
    for run in runs.values():
        values = {dim:run[dim] for dim in dimensions}
        gid = (tuple(values.items()),run['compatibility'])
        if gid not in groups:
            groups[gid] = {**values, **{k:run[k] for k in ('context_revision','algorithm_version','geometry','estimator','sample_fps','confidence')},
                'context_signature':run['compatibility'][2][:12],
                'job_ids':set(), 'capture_ids':set(), '_rula':Counter(), '_reba':Counter(), 'samples':0}
        group = groups[gid]
        group['job_ids'].add(run['job_id']); group['capture_ids'].add(run['capture_id'])
        group['samples'] += run['samples']
        for metric in ('rula','reba'):
            group['_'+metric].update(run['_'+metric])
    for item in [*runs.values(), *groups.values()]:
        for metric, maximum, threshold in (('rula',7,5),('reba',15,8)):
            item[metric] = distribution(item.pop('_'+metric),maximum,threshold)
        item.pop('compatibility',None)
        if 'job_ids' in item:
            item['analyses'] = len(item['job_ids']); item['captures'] = len(item.pop('capture_ids'))
            item['job_ids'] = sorted(item['job_ids'])
    return list(runs.values()), list(groups.values())


def date_bound(value, end=False):
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        return (parsed+timedelta(days=int(end))).isoformat()+'T00:00:00.000Z'
    except (ValueError, OverflowError):
        raise HTTPException(422,'Fecha inválida; usa YYYY-MM-DD (UTC).')


@router.get('/analysis',summary='Filter and group laboratory score distributions')
def analysis(request:Request, group_by:str='table_height_cm', operator_id:str='', table_height_cm:str='',
             camera_index:str='', condition:str='', context_revision:str='', since:str='', until:str='', latest:bool=True):
    auth.admin(request)
    dimensions = list(dict.fromkeys(group_by.split(',')))
    if not dimensions or any(d not in DIMENSIONS for d in dimensions):
        raise HTTPException(422,'Agrupación no admitida.')
    start, end = date_bound(since), date_bound(until,True)
    if start and end and start>=end:
        raise HTTPException(422,'El inicio debe ser anterior al final.')
    if table_height_cm and table_height_cm!='none':
        try:
            if not 20 <= int(table_height_cm) <= 200: raise ValueError()
        except ValueError:
            raise HTTPException(422,'Altura inválida; usa centímetros o none.')
    if camera_index not in ('','1','2') or condition not in ('','with_robot','without_robot','unknown'):
        raise HTTPException(422,'Filtro de cámara o condición inválido.')
    all_jobs=[]; seen=set()
    sessions=set(d['_id'] for d in db.sessions.find({'deleted':{'$ne':True}},{'_id':1}))
    for job in db.vision_jobs.find({'deleted':{'$ne':True},'origin':{'$ne':'real'},'status':'completed'}).sort('created_at',-1):
        if job['session_id'] not in sessions or latest and job['asset_id'] in seen: continue
        seen.add(job['asset_id']); all_jobs.append(job)
    assets={a['_id']:a for a in db.vision_assets.find({'_id':{'$in':[j['asset_id'] for j in all_jobs]},'deleted':{'$ne':True}},
        {'capture':1})}
    all_jobs=[j for j in all_jobs if j['asset_id'] in assets]
    def matches(job):
        height=job.get('table_height_cm'); capture=assets[job['asset_id']].get('capture',{})
        return ((not operator_id or job.get('operator_id')==operator_id)
            and (not table_height_cm or (height is None if table_height_cm=='none' else height==int(table_height_cm)))
            and (not camera_index or capture.get('camera_index',1)==int(camera_index))
            and (not condition or robot_condition(job['name'])==condition)
            and (not context_revision or str(job.get('context',{}).get('revision'))==context_revision)
            and (not start or job['created_at']>=start) and (not end or job['created_at']<end))
    selected=[j for j in all_jobs if matches(j)]
    buckets=db.vision_results.aggregate([
        {'$match':{'job_id':{'$in':[j['job_id'] for j in selected]}}},
        {'$group':{'_id':{'job_id':'$job_id', 'rula':'$metrics.rula', 'reba':'$metrics.reba',
            'algorithm':'$metrics.algorithm_version','revision':'$metrics.context_revision','geometry':'$metrics.geometry'}, 'count':{'$sum':1}}}])
    runs, groups=aggregate(selected,assets,buckets,dimensions)
    return {'group_by':dimensions, 'latest':latest, 'runs':runs, 'groups':groups,
        'totals':{'analyses':len({r['job_id'] for r in runs}), 'captures':len({r['capture_id'] for r in runs}),
                  'samples':sum(r['samples'] for r in runs), 'without_results':len(selected)-len({r['job_id'] for r in runs})},
        'available':{'heights':sorted({j['table_height_cm'] for j in all_jobs if j.get('table_height_cm') is not None}),
            'operators':sorted({j.get('operator_id') for j in all_jobs if j.get('operator_id')}),
            'revisions':sorted({str(j.get('context',{}).get('revision','unknown')) for j in all_jobs})}}
