"""Finish real batches, prepare the chosen lesson and true draft auditions.

Teacher decisions stay pending. All authorized media remain in private storage.
"""
import sys,time,json,re
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from mooc_m1.core import read_json,write_json,stamp,digest
from mooc_m2.store import Store
from mooc_m2.content import current

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    out=ROOT/'docs/evidence/M2/course-ai-real.json'
    record=read_json(out);pid=record['project_id']
    c=httpx.Client(base_url='http://127.0.0.1:8765/api',timeout=300,trust_env=False)
    c.post('/session',json={'token':(ROOT/'storage/m2/.session-token').read_text().strip()}).raise_for_status()
    def get(path):
        for attempt in range(10):
            try:
                r=c.get(path);r.raise_for_status();return r.json()
            except httpx.TransportError:
                if attempt==9:raise
                time.sleep(2)
    def post(path,body=None):
        r=c.post(path,json=body or {});r.raise_for_status();return r.json()
    def wait(project_id):
        last=None
        while True:
            jobs=get(f'/projects/{project_id}/jobs')
            latest={}
            for j in jobs:
                if j['kind']=='ai':latest.setdefault(j['payload']['scene_id'],j)
            counts={state:sum(j['state']==state for j in latest.values()) for state in ['queued','running','completed','failed']}
            if project_id==pid:
                record.update(counts=counts,checked_at=stamp(),failures=[{'scene_id':j['payload']['scene_id'],'error':j['error']} for j in latest.values() if j['state']=='failed'])
                write_json(out,record)
            if counts!=last:print(project_id[:8],counts,flush=True);last=counts
            if not any(j['state'] in {'queued','running'} for j in jobs):return jobs
            time.sleep(3)
    wait(pid)
    # Apply the stronger Chinese-reading validation to early drafts while retaining
    # all original AI versions. Only deficient or failed pages are retried.
    p=get(f'/projects/{pid}');redo=[]
    for s in p['scenes']:
        v=current(s)
        dc=len(re.findall(r'[\u4e00-\u9fff]',v['display_text'])) if v else 0
        if not v or dc>20 and len(re.findall(r'[\u4e00-\u9fff]',v['reading_text']))<dc*.5:redo.append(s['id'])
    if redo:
        post(f'/projects/{pid}/ai-batches',{'revision':p['revision'],'scene_ids':redo});print('Retry deficient/failed',len(redo),flush=True);wait(pid)
    for attempt in range(2):
        p=get(f'/projects/{pid}');jobs=get(f'/projects/{pid}/jobs');latest={}
        for j in jobs:
            if j['kind']=='ai':latest.setdefault(j['payload']['scene_id'],j)
        if not any(j['state']=='failed' for j in latest.values()):break
        post(f'/projects/{pid}/ai-batches',{'revision':p['revision'],'retry_failed':True});wait(pid)
    p=get(f'/projects/{pid}')
    record.update(page_count=len(p['slides']),draft_versions=[{'scene_id':s['id'],'source_page_ids':s['source_page_ids'],'version_id':s['current_version'],'question_count':len(current(s)['checks']['questions']) if current(s) else 0,'pending_count':len(current(s)['checks']['pending']) if current(s) else 0,'teacher_confirmed':bool(s['confirmed']),'provenance':current(s)['provenance'] if current(s) else None} for s in p['scenes']])
    write_json(out,record)
    lesson=post(f'/projects/{pid}/copy');lid=lesson['id']
    # Local preparation metadata is deliberately outside teacher-review actions.
    store=Store(ROOT/'storage/m2')
    with store.edit(lid) as lesson:
        lesson['name']='无线接入与多址技术 · 第 5–14 页 · 待教师审核'
        lesson['config']['course_name']=lesson['name']
        lesson['formal_scope']={'first':5,'last':14,'title':'无线接入与多址技术','user_selected':True}
        selected={x['source_page_id'] for x in lesson['slides'] if 5<=x['source_index']<=14}
        for s in lesson['scenes']:
            s['skipped']=not bool(selected.intersection(s['source_page_ids']))
        lesson['course_review']='pending_teacher_review'
    lesson=get(f'/projects/{lid}')
    active=[s for s in lesson['scenes'] if not s['skipped']]
    evidence={'created_at':stamp(),'project_id':lid,'source_project_id':pid,'formal_scope':lesson['formal_scope'],'active_pages':10,'teacher_confirmed_count':0,'question_count':sum(len(current(s)['checks']['questions']) for s in active if current(s)),'questions':[],'pending_items':[],'auditions':[],'snapshot_created':False,'teacher_review':'pending'}
    # The detailed teacher packet is private, only counts/hashes enter Git.
    packet=['# 教师审核包：无线接入与多址技术（原页 5–14）','所有稿件、答案和读法均为 AI 草稿，需教师判断；未确认、未冻结。']
    for s in active:
        page=next(x for x in lesson['slides'] if x['source_page_id']==s['play_page_id']);v=current(s)
        if not v:continue
        packet.extend([f"\n## 原页 {page['source_index']}",v['display_text'],'\n读法稿：'+v['reading_text']])
        for q in v['checks']['questions']:
            packet.extend(['\n问题：'+q['question'],'答案：'+q['answer'],'来源：'+q['source_page_id']])
            evidence['questions'].append({'source_page_id':q['source_page_id'],'question_sha256':__import__('hashlib').sha256(q['question'].encode()).hexdigest()})
        for pending in v['checks']['pending']:
            packet.append('\n待审核：'+pending)
        evidence['pending_items'].append({'source_index':page['source_index'],'count':len(v['checks']['pending'])})
        post(f'/projects/{lid}/scenes/{s["id"]}/audition',{'revision':get(f'/projects/{lid}')['revision'],'draft_preview':True})
        jobs=wait(lid);j=jobs[0]
        evidence['auditions'].append({'source_index':page['source_index'],'state':j['state'],'error':j['error'],'output':j['result']})
        print('Draft audition',page['source_index'],j['state'],flush=True)
    packet_path=store.folder(lid)/'teacher-review-packet.md';packet_path.write_text('\n'.join(packet),encoding='utf-8')
    evidence['private_review_packet']={'path':str(packet_path),'sha256':digest(packet_path)}
    report=post(f'/projects/{lid}/preflight')
    evidence['preflight']={'ready':report['ready'],'blocker_counts':{code:sum(b['code']==code for b in report['blockers']) for code in {b['code'] for b in report['blockers']}}}
    r=c.post(f'/projects/{lid}/snapshots',json={'revision':get(f'/projects/{lid}')['revision']})
    evidence['unconfirmed_freeze_http_status']=r.status_code
    write_json(ROOT/'docs/evidence/M2/formal-lesson-review.json',evidence)
    print('Teacher packet prepared; confirmation and frozen snapshot pending',flush=True)

if __name__=='__main__':main()
