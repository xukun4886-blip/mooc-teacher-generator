"""Validate real draft files, current audio provenance, docs and pending gates."""
import copy
import json
import re
import wave
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import numpy as np
from mooc_m1.core import digest, read_json, run, stamp, write_json
from mooc_m2.service import Service

root=Path(__file__).resolve().parents[1]
service=Service(read_json(root/'config/m2.local.json'))
evidence_path=root/'docs/evidence/M3/real-draft-media.json'
evidence=read_json(evidence_path)
pid=evidence['engineering_project_id']
record={'created_at':stamp(),'quality_verified':False,'formal_validation_completed':False,'paths':{}}


def pcm(path,target):
    run([service.media.ffmpeg,'-nostdin','-v','error','-y','-i',path,'-map','0:a:0','-ac','1','-ar','16000','-c:a','pcm_s16le',target],60)
    with wave.open(str(target),'rb') as wav:
        return np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(float)


for mode,data in evidence['paths'].items():
    job=service.m3.get(pid,data['job_id'])
    assert job['state']=='completed' and job['payload']['preview'] and job['result']['export_version']==2
    assert job['result']['video_start_seconds']==0
    exports={}
    for kind,relative in job['result']['exports'].items():
        path=service.m3.verify(pid,relative,job['result']['file_hashes'][kind])
        exports[kind]={'path':str(path),'sha256':digest(path),'size_bytes':path.stat().st_size}
    output=service.media.inspect(service.store.file(pid,job['result']['path']),'video',expected_duration=11.16)
    service.media.inspect(service.store.file(pid,job['result']['path']),'audio',expected_duration=11.16)
    native=[]
    verification=service.store.folder(pid)/'m3/verification';verification.mkdir(parents=True,exist_ok=True)
    for scene in job['scenes']:
        assert scene['state']=='valid'
        if not scene['portrait']:
            assert scene['stage_states']['portrait']=='not_required';continue
        audio,portrait=scene['tts'],scene['portrait']
        assert portrait['audio_sha256']==audio['sha256'] and portrait['mode']==mode
        a=pcm(service.store.file(pid,audio['path']),verification/f'{mode}-{scene["id"]}-driver.wav')
        b=pcm(service.store.file(pid,portrait['path']),verification/f'{mode}-{scene["id"]}-portrait.wav')
        n=min(len(a),len(b));correlation=float(np.corrcoef(a[:n],b[:n])[0,1])
        assert correlation>.98
        native.append({'scene_id':scene['id'],'source_index':scene['source_index'],'request_id':portrait['request_id'],'provider':portrait['provider'],
            'current_audio_sha256':audio['sha256'],'portrait_sha256':portrait['sha256'],'zero_offset_waveform_correlation':correlation,
            'scope':'acoustic track correspondence only; identity, timbre and mouth synchronization require human review',
            'native_driving':portrait.get('native_driving'),'native_loads':portrait.get('native_loads'),'resources':portrait.get('resources')})
    assert len({n['current_audio_sha256'] for n in native})==2
    assert len({n['portrait_sha256'] for n in native})==2
    record['paths'][mode]={'job_id':job['id'],'exports':exports,'video_start_seconds':0,'duration_seconds':output['duration_seconds'],
                          'pages':job['result']['timeline'],'native_portraits':native,'all_stages_valid':True}
    # Earlier packet-copy exports and original bytes remain available in controlled
    # history, but no longer masquerade as the corrected usable task result.
    for previous in evidence.get('previous_runs',[]):
        old_data=previous['paths'].get(mode)
        if old_data and old_data['job_id']!=job['id']:
            old=service.m3.get(pid,old_data['job_id'])
            if old['state']=='completed':
                old.update(state='failed',stage='superseded_timestamp_export',superseded_result=old['result'],result=None,
                    superseded_by=job['id'],error={'code':'TIMELINE_MISMATCH','message':'旧拼接输出存在 AAC 封装偏移；已保留历史并由零起点新版替代'})
                service.store.update_job(old)
            old_data['invalidated_for_timeline']=True

# No classroom text in committed evidence: full scripts stay in controlled outputs.
def redact(value):
    if isinstance(value,dict):
        if 'method' in value and 'text' in value:
            value['text_sha256']=__import__('hashlib').sha256(value.pop('text').encode()).hexdigest()
        for child in value.values():redact(child)
    elif isinstance(value,list):
        for child in value:redact(child)
redact(evidence)
write_json(evidence_path,evidence)
source=service.store.get(evidence['source_project_id'])
active=[s for s in source['scenes'] if not s['skipped']]
with service.store.connection() as db:
    snapshots=db.execute('SELECT COUNT(*) FROM snapshots WHERE project_id=?',(source['id'],)).fetchone()[0]
assert len(active)==10 and sum(bool(s['confirmed']) for s in active)==0 and snapshots==0
assert service.m3.review.get('m1:'+source['id']) is None
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=60) as client:
    client.post('/api/session',json={'token':service.store.token}).raise_for_status()
    record['actual_export_http'] = {}
    for mode,data in record['paths'].items():
        record['actual_export_http'][mode] = {}
        for kind,file in data['exports'].items():
            download=client.get(f'/api/projects/{pid}/media-jobs/{data["job_id"]}/exports/{kind}')
            assert download.status_code==200
            assert __import__('hashlib').sha256(download.content).hexdigest()==file['sha256']
            record['actual_export_http'][mode][kind] = {'status':200,'sha256':file['sha256']}
    response=client.post(f'/api/projects/{source["id"]}/media-jobs',json={})
    assert response.status_code==422 and response.json()['error']['code']=='SNAPSHOT_REQUIRED'
    freeze=client.post(f'/api/projects/{source["id"]}/snapshots',json={'revision':source['revision']})
    assert freeze.status_code==422
record['formal_gates']={'active_pages':10,'teacher_confirmed':0,'snapshots':snapshots,'m1_human_review_saved':False,'formal_submit_http':422,'m2_freeze_http':422}
tests=ET.parse(root/'docs/evidence/M3/tests.xml').getroot()
record['tests']={'count':len(tests.findall('.//testcase')),'failures':len(tests.findall('.//failure')),'errors':len(tests.findall('.//error'))}
assert record['tests']['count']>=70 and record['tests']['failures']==record['tests']['errors']==0
files=[root/p for p in ['docs/PROJECT_STATUS.md','docs/M3_RUNBOOK.md','docs/evidence/M3/README.md','specs/M3-media-contract.md','specs/M3-media-pipeline.spec.md','specs/M2-content-contract.md','specs/TRACEABILITY.md']]
broken=[]
for file in files:
    content=file.read_text(encoding='utf-8')
    assert '\ufffd' not in content
    for target in re.findall(r'\]\(([^)]+)\)',content):
        if ':' in target.split('/')[0] or target.startswith('#'):continue
        target=target.split('#')[0]
        if target and not (file.parent/target).exists():broken.append({'file':str(file),'target':target})
assert not broken,broken
record['documents']={'checked':len(files),'broken_links':broken,'source_requirement_files_modified':False}
record['source_hashes']={str(p.relative_to(root)):digest(p) for p in [*files,*sorted((root/'mooc_m3').glob('*.py')),*sorted((root/'frontend/src').glob('*')),root/'mooc_m2/api.py',root/'mooc_m2/service.py',root/'mooc_m2/store.py',root/'mooc_m2/content.py',root/'mooc_m1/adapters.py',root/'mooc_m1/core.py',root/'mooc_m1/model_worker.py',root/'tests/test_m3.py',root/'docs/evidence/M3/tests.xml',root/'frontend/dist/index.html']}
record['limits']=['short draft excerpts only; formal ten-page/three-minute paths not run','all human quality decisions pending','no model warm-process or long-course resource claims','engineering fault tests use synthetic media; no formal GPU long-course restart claim']
write_json(root/'docs/evidence/M3/final-check.json',record)
print(json.dumps({'paths':{k:v['duration_seconds'] for k,v in record['paths'].items()},'tests':record['tests'],'formal_gates':record['formal_gates'],'document_links':'valid'},ensure_ascii=False))
