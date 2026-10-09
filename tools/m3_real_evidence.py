"""Real model draft evidence on a physical engineering copy; no teacher approvals.

Three original pages, two different current-audio portraits per path, one hidden
page. This is not the pending formal ten-page/three-minute validation.
"""
import copy
import json
import sys
import time
from pathlib import Path
import httpx

from mooc_m1.core import read_json, digest, stamp, write_json
from mooc_m2.content import current, add_version
from mooc_m2.store import Store
from mooc_m3.timeline import sentences


def public_audio(record):
    if not record:
        return record
    value = copy.deepcopy(record)
    for cue in value.get('captions', []):
        cue['text_sha256'] = __import__('hashlib').sha256(cue.pop('text').encode()).hexdigest()
    return value


root = Path(__file__).resolve().parents[1]
config = read_json(root/'config/m2.local.json')
store = Store(root/config['storage'])
source_id = read_json(root/'docs/evidence/M2/formal-lesson-review.json')['project_id']
evidence_path = root/'docs/evidence/M3/real-draft-media.json'
if evidence_path.is_file():
    evidence = read_json(evidence_path)
    pid = evidence['engineering_project_id']
    if any((data.get('result') or {}).get('export_version') != 2 for data in evidence['paths'].values()):
        evidence.setdefault('previous_runs', []).append({'reason': 'AAC concat timestamp normalization', 'paths': evidence['paths']})
        evidence['paths'] = {}
else:
    original = store.get(source_id)
    clone = store.clone(source_id)
    pid = clone['id']
    with store.edit(pid) as p:
        p.update(name='M3 真实模型工程样片 · 原页5–7摘句', engineering_only=True, category='development')
        p['config'].update(course_name=p['name'], resolution='720p')
        active = [s for s in p['scenes'] if not s['skipped']][:3]
        for s in p['scenes']:
            s['skipped'] = s not in active
        for i,s in enumerate(active):
            v = current(s)
            display, reading = sentences(v['display_text'])[0], sentences(v['reading_text'])[0]
            add_version(p,s,'manual',display,reading,{'engineering_excerpt':True,'from_version':v['id'],'source_page_ids':s['source_page_ids']})
            s['overrides'].update(show_teacher=i!=1, layout='sidebar' if i==2 else 'overlay',position='top-left' if i==0 else 'bottom-right',pause_before=.2,pause_after=.3)
    evidence = {'created_at':stamp(),'source_project_id':source_id,'engineering_project_id':pid,'scope':'real draft excerpts only; no teacher confirmation or formal snapshot',
                'quality_verified':False,'formal_validation_completed':False,'paths':{}}
    write_json(evidence_path,evidence)

with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=60) as client:
    client.post('/api/session',json={'token':store.token}).raise_for_status()
    for mode in ['photo','video']:
        old = evidence['paths'].get(mode)
        if old and old.get('state')=='completed':
            print(mode+' already completed',flush=True);continue
        p = store.get(pid)
        mapping = {s['id']:[{'display':current(s)['display_text'],'reading':current(s)['reading_text']}] for s in p['scenes'] if not s['skipped']}
        if old:
            response=client.get(f"/api/projects/{pid}/media-jobs/{old['job_id']}");response.raise_for_status();job=response.json()
            if job['state']=='failed':
                response=client.post(f"/api/projects/{pid}/media-jobs/{job['id']}/retry");response.raise_for_status();job=response.json()
        else:
            response=client.post(f'/api/projects/{pid}/media-jobs',json={'preview':True,'revision':p['revision'],'mode':mode,'subtitle_units':mapping})
            response.raise_for_status();job=response.json()
        evidence['paths'][mode]={'job_id':job['id'],'state':job['state']};write_json(evidence_path,evidence)
        previous=None
        while job['state'] in ['queued','running']:
            summary=(job['state'],job['stage'],job['progress']['valid'])
            if summary!=previous:
                print(json.dumps({'mode':mode,'state':summary,'progress':job['progress']},ensure_ascii=False),flush=True);previous=summary
            time.sleep(3)
            response=client.get(f"/api/projects/{pid}/media-jobs/{job['id']}");response.raise_for_status();job=response.json()
        internal = None
        with store.connection() as db:
            internal=json.loads(db.execute('SELECT data FROM jobs WHERE id=?',(job['id'],)).fetchone()[0])
        evidence['paths'][mode].update(state=job['state'],error=job['error'],result=job['result'],elapsed_seconds=job.get('elapsed_seconds'),recoveries=job['recoveries'],
            scenes=[{'scene_id':s['id'],'source_index':s['source_index'],'stage_states':s['stage_states'],'cache_hits':s['cache_hits'],
                     'audio':public_audio(s.get('tts')),'portrait':s.get('portrait'),'composition':s.get('compose')} for s in internal['scenes']])
        write_json(evidence_path,evidence)
        print(mode+' '+job['state'],flush=True)
        if job['state']!='completed':
            raise RuntimeError('Real path failed: '+json.dumps(job['error'],ensure_ascii=False))
    source=store.get(source_id)
    evidence.update(finished_at=stamp(),source_teacher_confirmed=sum(bool(s['confirmed']) for s in source['scenes'] if not s['skipped']))
    write_json(evidence_path,evidence)
print('Real draft evidence saved. Formal teacher approval remains pending.',flush=True)
