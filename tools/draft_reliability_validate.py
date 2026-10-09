"""Bounded real body-first validation in isolated storage; no teacher media upload."""
import copy
import json
import shutil
import sqlite3
import time
from pathlib import Path
from mooc_m1.core import stamp, digest
from mooc_m2.service import Service
from mooc_m2.content import new_scene, current, fingerprint

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/M2/draft-reliability-real.json'
CONFIG=ROOT/'storage/draft-reliability/validation-config.json'
sources=[('57866fdf-6350-400b-9911-8c9bd9cc407f',[7,9],'工程课件'),
         ('877fc5f9-cd0e-445f-b3f9-59c1e00cd1d5',[17,22],'Lecture 8'),
         ('11604689-6106-451f-b40b-95089e07b5b5',[1,11],'Lecture 9')]
cfg=json.loads((ROOT/'config/m2.local.json').read_text(encoding='utf-8'))
cfg['storage']='storage/draft-reliability/validation'
cfg['ai']['pipeline']={'enabled':True,'text_model':'glm-4.7-flash','request_options':{'max_tokens':2048}}
CONFIG.parent.mkdir(parents=True,exist_ok=True)
CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
svc=Service(cfg,ROOT)
result=json.loads(OUT.read_text(encoding='utf-8')) if OUT.exists() else {'started_at':stamp(),'isolated_storage':cfg['storage'],'cases':[],'sources':[],'automatic_extra_batches':0}


def save():
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if not result['sources']:
    original=sqlite3.connect('file:storage/m2/content.sqlite3?mode=ro',uri=True)
    original.execute('PRAGMA query_only=ON')
    for pid,indices,label in sources:
        p=json.loads(original.execute('SELECT data FROM projects WHERE id=?',(pid,)).fetchone()[0])
        target=svc.store.create('分阶段真实验证 · '+label,{'target_seconds':12})
        with svc.store.edit(target['id']) as edited:
            edited['category']='development'
            selected=[copy.deepcopy(s) for s in p['slides'] if s['source_index'] in indices]
            edited['slides']=selected
            edited['scenes']=[new_scene([s['source_page_id']]) for s in selected]
            for s,scene in zip(selected,edited['scenes']):
                if s['source_index'] in {1,22}:scene['kind']='intro' if s['source_index']==1 else 'summary'
                src=ROOT/'storage/m2/projects'/pid/s['image']
                dst=svc.store.file(target['id'],s['image']);dst.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(src,dst)
        result['sources'].append({'source_project_id':pid,'label':label,'project_id':target['id'],'source_indices':indices})
    save()

for round_index in (1,2):
    for src in result['sources']:
        p=svc.store.get(src['project_id'])
        for scene in p['scenes']:
            slide=next(s for s in p['slides'] if s['source_page_id'] in scene['source_page_ids'])
            case_key=f"{round_index}:{p['id']}:{scene['id']}"
            if any(c['case_key']==case_key and c.get('finished_at') for c in result['cases']):continue
            case=next((c for c in result['cases'] if c['case_key']==case_key),None)
            if case:
                job=next(j for j in svc.store.jobs(p['id']) if j['id']==case['job_id'])
            else:
                latest=svc.store.get(p['id'])
                job=svc.queue_ai(p['id'],latest['revision'],[scene['id']])['jobs'][0]
                case={'case_key':case_key,'round':round_index,'source_label':src['label'],'source_index':slide['source_index'],'job_id':job['id']}
                result['cases'].append(case);save()
            job.update(state='running',stage='starting');svc.store.update_job(job)
            started=time.monotonic();svc.execute(job)
            run=svc.drafts.get_run(job)
            v=current(next(s for s in svc.store.get(p['id'])['scenes'] if s['id']==scene['id']))
            case.update(finished_at=stamp(),wall_seconds=round(time.monotonic()-started,3),state=job['state'],error=job.get('error'),
                        result=job.get('result'),stage_states={k:s['state'] for k,s in run['stages'].items()},
                        run_id=run['id'],attempts={k:s.get('attempts',[]) for k,s in run['stages'].items()},
                        vision_reused=bool(run['stages'].get('vision',{}).get('reused_from_run')),
                        version_id=v['id'] if v else None,body_sha256=fingerprint(v['display_text']) if v else None,
                        teaching_check_state=v.get('teaching_check_state') if v else None,
                        pending=v['checks']['pending'] if v else None)
            if v:
                for s in run['stages'].values():
                    if s.get('response'):
                        assert digest(svc.store.file(p['id'],s['response']['path']))==s['response']['response_sha256']
                assert ''.join(u['display'] for u in v['provenance']['sentence_pairs'])==v['display_text']
                assert ''.join(u['reading'] for u in v['provenance']['sentence_pairs'])==v['reading_text']
                assert not v['teacher_review']
            save();print(json.dumps({k:case[k] for k in ('source_label','source_index','round','state','teaching_check_state','wall_seconds')},ensure_ascii=False),flush=True)
result['finished_at']=stamp()
result['summary']={'cases':len(result['cases']),'body_ready':sum(c['version_id'] is not None for c in result['cases']),
                   'checks_ready':sum(c['teaching_check_state']=='completed' for c in result['cases']),
                   'failed':sum(c['state']=='failed' for c in result['cases']),
                   'vision_reused':sum(c['vision_reused'] for c in result['cases']),
                   'scope':'real structure/body/pronunciation-rule verification; teacher quality and full-course generation not certified'}
save();print(json.dumps(result['summary'],ensure_ascii=False),flush=True)
