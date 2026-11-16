"""Laboratory annotations, separate from observed telemetry and frozen metrics."""
import re

from fastapi import HTTPException

from .store import db, now

METADATA_VERSION = 1
HEIGHT = re.compile(r'(?<![\w.])(75|100|120)\s*(cm|mm)\b', re.IGNORECASE)


def title_metadata(name):
    """Known experiment labels used mm by mistake: retain the numeric value."""
    matches = list(HEIGHT.finditer(name))
    heights = {int(m[1]) for m in matches}
    return HEIGHT.sub(lambda m: m[1]+'cm', name), next(iter(heights)) if len(heights)==1 else None


def height_value(value):
    if value is None:
        return None
    if type(value) not in (int, float) or not 20 <= value <= 200 or int(value) != value:
        raise HTTPException(422, 'Altura de mesa en centímetros enteros, entre 20 y 200, o null.')
    return int(value)


def metadata(name, body):
    name, inferred = title_metadata(name)
    explicit = 'table_height_cm' in body
    height = height_value(body['table_height_cm']) if explicit else inferred
    return {'name':name, 'table_height_cm':height,
            'table_height_source':'manual' if explicit else 'title' if height is not None else 'unknown',
            'lab_metadata_version':METADATA_VERSION}


def migrate_laboratory_metadata():
    """Idempotent, journaled backfill; originals and pose/score records stay intact."""
    query = {'origin':{'$ne':'real'}, 'deleted':{'$ne':True}, 'lab_metadata_version':{'$ne':METADATA_VERSION}}
    for job in db.vision_jobs.find(query):
        values = metadata(job['name'], {k:job[k] for k in ('table_height_cm',) if k in job})
        stamp = now()
        db.metadata_corrections.update_one({'_id':'lab-height-v1:'+job['_id']}, {'$setOnInsert':{
            'kind':'laboratory_title_and_height', 'job_id':job['_id'], 'at':stamp,
            'before':{k:job.get(k) for k in values}, 'after':values,
            'reason':'User confirmed 75/100/120 mm in experiment titles means cm; height is an annotation.'}}, upsert=True)
        # Related writes are repeatable if startup is interrupted before marking the job.
        db.sessions.update_one({'_id':job['session_id']},{'$set':{'name':values['name'], 'table_height_cm':values['table_height_cm']}})
        db.studies.update_one({'_id':job['study_id']},{'$set':{'name':'Laboratorio · '+values['name'], 'table_height_cm':values['table_height_cm']}})
        db.vision_jobs.update_one({'_id':job['_id'], 'lab_metadata_version':{'$ne':METADATA_VERSION}}, {'$set':values})
    # Includes retained captures that have not yet been analysed. Never rename files.
    for asset in db.vision_assets.find({'origin':{'$ne':'real'}, 'deleted':{'$ne':True},
                                      'capture.analysis_options.name':{'$type':'string'},
                                      'capture.lab_metadata_version':{'$ne':METADATA_VERSION}}):
        options = asset['capture']['analysis_options']
        values = metadata(options['name'], options)
        db.metadata_corrections.update_one({'_id':'lab-height-asset-v1:'+asset['_id']},{'$setOnInsert':{
            'kind':'laboratory_capture_title_and_height', 'asset_id':asset['_id'], 'at':now(),
            'before':options, 'after':values}},upsert=True)
        db.vision_assets.update_one({'_id':asset['_id']},{'$set':{
            'capture.analysis_options.name':values['name'],
            'capture.analysis_options.table_height_cm':values['table_height_cm'],
            'capture.lab_metadata_version':METADATA_VERSION}})


def annotate_height(job, value, actor):
    height = height_value(value)
    values = {'table_height_cm':height, 'table_height_source':'manual', 'updated_at':now()}
    db.metadata_corrections.insert_one({'kind':'laboratory_height_edit', 'job_id':job['job_id'],
        'at':values['updated_at'], 'by':actor['username'],
        'before':{'table_height_cm':job.get('table_height_cm')}, 'after':values})
    db.vision_jobs.update_one({'_id':job['job_id']},{'$set':values})
    db.sessions.update_one({'_id':job['session_id']},{'$set':{'table_height_cm':height}})
    db.studies.update_one({'_id':job['study_id']},{'$set':{'table_height_cm':height}})
    # A future reanalysis of this original inherits the annotation.
    db.vision_assets.update_one({'_id':job['asset_id']},{'$set':{'capture.analysis_options.table_height_cm':height}})
    return {**job, **values}
