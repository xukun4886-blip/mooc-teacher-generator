"""One bounded recovery sample per selected failure; retain initial evidence."""
import json
from pathlib import Path
from mooc_m1.core import read_json, write_json, stamp
from mooc_m2.content import current, fingerprint
from mooc_m2.service import Service

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/M2/draft-reliability-recovery.json'
if OUT.exists():
    raise SystemExit('Recovery sample already recorded; no automatic extra batch')
svc=Service(read_json(ROOT/'storage/draft-reliability/validation-config.json'),ROOT)
initial=read_json(ROOT/'docs/evidence/M2/draft-reliability-real.json')
record={'started_at':stamp(),'initial_evidence':'draft-reliability-real.json','samples':[],
        'scope':'one bounded teaching-only retry and one failed-body retry; initial failures retained'}
targets=[('工程课件',9,'teaching'),('Lecture 9',11,'ai')]
for label,index,kind in targets:
    src=next(s for s in initial['sources'] if s['label']==label)
    p=svc.store.get(src['project_id'])
    slide=next(s for s in p['slides'] if s['source_index']==index)
    scene=next(s for s in p['scenes'] if slide['source_page_id'] in s['source_page_ids'])
    before=current(scene)
    body_before=fingerprint(before['display_text']) if before else None
    job=svc.queue_teaching(p['id'],scene['id'],p['revision']) if kind=='teaching' else svc.queue_ai(p['id'],p['revision'],[scene['id']])['jobs'][0]
    job.update(state='running',stage='starting');svc.store.update_job(job);svc.execute(job)
    after=current(next(s for s in svc.store.get(p['id'])['scenes'] if s['id']==scene['id']))
    run=svc.store.draft_run(job['payload']['draft_run_id']) if kind=='teaching' else svc.drafts.get_run(job)
    body_after=fingerprint(after['display_text']) if after else None
    if kind=='teaching':assert body_before==body_after
    sample={'label':label,'page':index,'kind':kind,'job_id':job['id'],'state':job['state'],
            'error':job.get('error'),'result':job.get('result'),'body_before':body_before,'body_after':body_after,
            'attempts_this_job':{k:[a for a in s.get('attempts',[]) if a['budget'].startswith(job['id']+':')] for k,s in run['stages'].items()}}
    record['samples'].append(sample);write_json(OUT,record)
    print(json.dumps({k:sample[k] for k in ('label','page','kind','state','error')},ensure_ascii=False),flush=True)
record['finished_at']=stamp();write_json(OUT,record)
