"""Activate at a persisted, GPU-free composition boundary; preserve course inputs.

This is a single local maintenance operation, not a recurring monitor. Isolated
speech samples run while the original serial worker is stopped, then that worker
resumes its immutable media job from validated caches.
"""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time
import httpx
from mooc_m1.core import read_json, write_json, stamp, digest
from mooc_m2.content import current, fingerprint, effective
from mooc_m2.service import Service
from mooc_m3.timeline import units, speech_runs, captions, srt

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/M2/draft-reliability-activation.json'
MID='a7376062-d076-4bbb-a728-c48ce85d1344'
PID='877fc5f9-cd0e-445f-b3f9-59c1e00cd1d5'
if OUT.exists():raise SystemExit('Activation already recorded; inspect evidence before any new action')
record={'started_at':stamp(),'original_media_job':MID,'events':[],'speech_samples':[]}
def event(name,**data):
    record['events'].append({'at':stamp(),'event':name,**data});write_json(OUT,record)
    print(json.dumps(record['events'][-1],ensure_ascii=False),flush=True)
def read_job():
    with sqlite3.connect('file:storage/m2/content.sqlite3?mode=ro',uri=True,timeout=5) as db:
        return json.loads(db.execute('SELECT data FROM jobs WHERE id=?',(MID,)).fetchone()[0])
def listener():
    ps="$taskListener=Get-NetTCPConnection -State Listen -LocalPort 8765; $taskProcess=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskListener.OwningProcess); @{id=$taskProcess.ProcessId;cmd=$taskProcess.CommandLine}|ConvertTo-Json -Compress"
    value=json.loads(subprocess.check_output(['powershell','-NoProfile','-Command',ps],text=True,encoding='utf-8'))
    assert '-m mooc_m2' in value['cmd'];return value['id']

kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
nt=ctypes.WinDLL('ntdll');nt.NtSuspendProcess.argtypes=[wintypes.HANDLE];nt.NtResumeProcess.argtypes=[wintypes.HANDLE]
handle=kernel.OpenProcess(0x0800|0x0001|0x1000,False,listener())
assert handle
suspended=False;stopped=False
try:
    deadline=time.monotonic()+1800
    event('waiting_for_saved_portrait_boundary')
    while time.monotonic()<deadline:
        j=read_job()
        safe=j['state']=='running' and j['stage']=='composing_original_page'
        if safe:
            assert nt.NtSuspendProcess(handle)==0;suspended=True
            j=read_job()
            active=[s for s in j['scenes'] if s.get('active_stage')=='compose' and s['state']=='running']
            if j['stage']=='composing_original_page' and active and all(s['stage_states']['portrait']=='valid' or not s['config']['show_teacher'] for s in active):break
            assert nt.NtResumeProcess(handle)==0;suspended=False
        if j['state'] in {'completed','failed','canceled'}:
            with sqlite3.connect('file:storage/m2/content.sqlite3?mode=ro',uri=True) as db:
                idle=not db.execute("SELECT 1 FROM jobs WHERE state IN ('running','queued')").fetchone()
            if idle:
                assert nt.NtSuspendProcess(handle)==0;suspended=True;break
        time.sleep(.15)
    else:raise RuntimeError('No safe boundary reached; original worker preserved')
    # Checkpoint backup and input/media hashes before stopping this exact server.
    backup=ROOT/'storage/draft-reliability/before-activation.sqlite3'
    with sqlite3.connect(ROOT/'storage/m2/content.sqlite3',timeout=5) as db,sqlite3.connect(backup) as target:
        db.backup(target)
        projects={r[0]:fingerprint(json.loads(r[1])) for r in db.execute('SELECT id,data FROM projects')}
    media=[]
    for scene in j['scenes']:
        for layer in ('tts','portrait','compose'):
            value=scene.get(layer)
            if scene['stage_states'].get(layer)=='valid' and value:
                path=ROOT/'storage/m2/projects'/PID/value['path']
                assert digest(path)==value['sha256'];media.append({'layer':layer,'path':str(path.relative_to(ROOT)),'sha256':value['sha256']})
    record.update(project_hashes_before=projects,input_key=j['payload']['input_key'],snapshot_sha256=fingerprint(j['payload']['snapshot']),
                  original_generation=j['generation'],validated_media=media)
    event('safe_checkpoint_captured',valid_scenes=sum(s['state']=='valid' for s in j['scenes']),stage=j['stage'])
    assert kernel.TerminateProcess(handle,0);stopped=True;suspended=False
    event('original_worker_stopped_after_portrait_saved')
finally:
    if suspended:nt.NtResumeProcess(handle)
    kernel.CloseHandle(handle)

if stopped:
    try:
        svc=Service(read_json(ROOT/'storage/draft-reliability/validation-config.json'),ROOT)
        original=sqlite3.connect(backup)
        p=json.loads(original.execute('SELECT data FROM projects WHERE id=?',(PID,)).fetchone()[0]);original.close()
        ref=p['assets']['reference_audio']
        src=ROOT/'storage/m2/projects'/PID/ref['selected']
        assert digest(src)==ref['selected_sha256']
        real=read_json(ROOT/'docs/evidence/M2/draft-reliability-real.json')
        for label,index in [('工程课件',7),('Lecture 8',17)]:
            chosen=next(s for s in real['sources'] if s['label']==label)
            project=svc.store.get(chosen['project_id'])
            slide=next(s for s in project['slides'] if s['source_index']==index)
            scene=next(s for s in project['scenes'] if slide['source_page_id'] in s['source_page_ids'])
            v=current(scene);cfg=effective(project,scene)
            copied=svc.store.file(project['id'],'validation-reference.wav');shutil.copy2(src,copied)
            paired=units(v,v['provenance']['sentence_pairs']);runs,groups=speech_runs(v,paired,cfg['pause_after'])
            result=svc.adapter('tts',project['id']).generate({'purpose':'audition','draft_preview':True,'script_confirmed':False,
                'authorized':True,'authorization_record':'authorized local reliability sample; source course '+PID,
                'text':v['reading_text'],'speech_segments':runs,'pause_before':cfg['pause_before'],'speed_factor':cfg['speed'],
                'reference_audio':str(copied),'reference_transcript':ref['selection']['transcript']})
            sample={'label':label,'page':index,'version_id':v['id'],'display_sha256':fingerprint(v['display_text']),
                    'reading_sha256':fingerprint(v['reading_text']),'state':result['state'],'error':result.get('error'),
                    'result':result,'teacher_review':False,'word_alignment_verified':False}
            if result['state']=='media_ready':
                cues=captions(paired,groups,result['native_model_record']['speech_timeline'])
                assert ''.join(c['text'].replace('\n','').replace(' ','') for c in cues)==v['display_text'].replace('\n','').replace(' ','')
                assert all(0<=c['start']<c['end']<=result['output']['duration_seconds']+.05 for c in cues)
                target=svc.store.file(project['id'],f"reliability-{index}.srt");target.write_text(srt(cues),encoding='utf-8')
                sample.update(captions=cues,srt_path=str(target.relative_to(ROOT)),srt_sha256=digest(target),
                              complete_display_coverage=True,measured_timeline_valid=True)
            record['speech_samples'].append(sample);event('speech_sample_completed',label=label,page=index,state=result['state'])
    except Exception as exc:
        event('speech_sample_exception',type=type(exc).__name__)
    finally:
        ps="Start-Process -FilePath 'D:\\XuTao_Task\\.venv-m1\\Scripts\\python.exe' -ArgumentList '-m','mooc_m2','--port','8765' -WorkingDirectory 'D:\\XuTao_Task' -WindowStyle Hidden -RedirectStandardOutput 'D:\\XuTao_Task\\storage\\draft-reliability\\server.stdout.log' -RedirectStandardError 'D:\\XuTao_Task\\storage\\draft-reliability\\server.stderr.log'"
        subprocess.run(['powershell','-NoProfile','-Command',ps],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=30)
        event('replacement_server_launched')
        with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=10) as client:
            for _ in range(60):
                try:
                    health=client.get('/api/health');health.raise_for_status()
                    if health.json()['worker_alive']:break
                except httpx.HTTPError:pass
                time.sleep(1)
            else:raise RuntimeError('Replacement server did not become ready')
            token=(ROOT/'storage/m2/.session-token').read_text().strip()
            client.post('/api/session',json={'token':token}).raise_for_status()
        resumed=read_job()
        with sqlite3.connect(ROOT/'storage/m2/content.sqlite3') as db:
            after={r[0]:fingerprint(json.loads(r[1])) for r in db.execute('SELECT id,data FROM projects')}
        assert all(after[k]==v for k,v in projects.items() if k==PID)
        assert resumed['payload']['input_key']==record['input_key']
        assert fingerprint(resumed['payload']['snapshot'])==record['snapshot_sha256']
        assert resumed['generation']==record['original_generation']
        assert all(digest(ROOT/m['path'])==m['sha256'] for m in media)
        record.update(project_hashes_after=after,worker_health=health.json(),resumed_state=resumed['state'],
                      resumed_stage=resumed['stage'],recovery_history=resumed.get('recovery_history'),
                      original_course_preserved=True,finished_at=stamp())
        event('activated_and_original_course_resumed',state=resumed['state'],stage=resumed['stage'])
