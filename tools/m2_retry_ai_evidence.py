"""Retry the existing real batch; preserve history and use current service config."""
import sys,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mooc_m1.core import read_json,write_json,stamp
from mooc_m2.content import current
record=read_json(ROOT/'docs/evidence/M2/course-ai-real.json');pid=record['project_id']
with httpx.Client(base_url='http://127.0.0.1:8765/api',trust_env=False,timeout=120) as c:
    c.post('/session',json={'token':(ROOT/'storage/m2/.session-token').read_text().strip()}).raise_for_status()
    for attempt in range(4):
        p=c.get(f'/projects/{pid}').json()
        jobs=c.get(f'/projects/{pid}/jobs').json();latest={}
        for j in jobs:
            if j['kind']=='ai':latest.setdefault(j['payload']['scene_id'],j)
        if not any(j['state']=='failed' for j in latest.values()):break
        r=c.post(f'/projects/{pid}/ai-batches',json={'revision':p['revision'],'retry_failed':True});r.raise_for_status()
        while True:
            jobs=c.get(f'/projects/{pid}/jobs').json();latest={}
            for j in jobs:
                if j['kind']=='ai':latest.setdefault(j['payload']['scene_id'],j)
            counts={s:sum(j['state']==s for j in latest.values()) for s in ['queued','running','completed','failed']}
            record.update(counts=counts,checked_at=stamp(),failures=[{'scene_id':j['payload']['scene_id'],'error':j['error']} for j in latest.values() if j['state']=='failed'])
            write_json(ROOT/'docs/evidence/M2/course-ai-real.json',record)
            if not counts['queued'] and not counts['running']:print(counts,flush=True);break
            time.sleep(3)
    p=c.get(f'/projects/{pid}').json()
    record['draft_versions']=[{'scene_id':s['id'],'source_page_ids':s['source_page_ids'],'version_id':s['current_version'],'question_count':len(current(s)['checks']['questions']) if current(s) else 0,'pending_count':len(current(s)['checks']['pending']) if current(s) else 0,'teacher_confirmed':bool(s['confirmed']),'provenance':current(s)['provenance'] if current(s) else None} for s in p['scenes']]
    record['native_json_mode']=True
    record['history_counts']={s:sum(j['state']==s for j in jobs if j['kind']=='ai') for s in ['queued','running','completed','failed']}
    record['stage_passed']=False
    write_json(ROOT/'docs/evidence/M2/course-ai-real.json',record)
