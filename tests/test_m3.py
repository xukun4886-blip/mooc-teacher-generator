"""Engineering orchestration tests. Synthetic audio/portraits are never M3 quality evidence."""
import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest
import wave
from fastapi.testclient import TestClient
from PIL import Image

from mooc_m1.core import Failure, digest, run, stamp
from mooc_m2.api import create_app
from mooc_m2.content import new_scene, add_version, current, fingerprint
from mooc_m3.timeline import units, speech_runs, captions, course_timeline, srt, coalesce_punctuation


def test_punctuation_attachment_preserves_offsets_and_real_caption_coverage():
    version={'id':'legacy','display_text':'（数组[1,2,3]的说明。)','reading_text':'（数组[1,2,3]的说明。)','control_events':[]}
    original=units(version,[{'display':'（','reading':'（'},{'display':'数组[1,2,3]的说明。','reading':'数组[1,2,3]的说明。'},{'display':')','reading':')'}])
    paired=coalesce_punctuation(original)
    assert len(paired)==1 and paired[0]['start_offset']==0 and paired[0]['end_offset']==len(version['reading_text'])
    assert paired[0]['display']==version['display_text'] and original[0]['display']=='（'
    runs,groups=speech_runs(version,paired,0)
    assert runs[0]['text']==version['reading_text'] and len(runs)==2
    cues=captions(paired,groups,[{'segment_index':0,'text_sha256':'real','start_seconds':0,'end_seconds':3.2}])
    assert cues[0]['text']==version['display_text'] and cues[0]['end']==3.2
    assert coalesce_punctuation([{'display':'[1,2,3]','reading':'[1,2,3]'}])[0]['display']=='[1,2,3]'
    with pytest.raises(Failure,match='只有标点'):coalesce_punctuation([{'display':')','reading':')'}])
    from mooc_m3.pipeline import Pipeline
    assert not Pipeline.needs_punctuation_repair(None,{'state':'failed','scenes':[{'paired':[{'display':')','reading':')'}]}]})


def write_wave(path, samples, sr):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(sr)
        out.writeframes((np.asarray(samples)*32767).astype('<i2').tobytes())


@pytest.fixture
def rig(tmp_path):
    app = create_app({'storage': str(tmp_path/'storage'), 'm1_config': 'config/m1.local.json', 'limits_mb': {}, 'ai': {}}, worker=False)
    service, calls = app.state.service, []
    store, pipeline = service.store, service.m3
    p = store.create('M3 test only', {'resolution': '720p'})
    pid = p['id']
    folder = store.folder(pid)
    Image.new('RGB', (640, 480), '#ddaa55').save(folder/'page.png')
    Image.new('RGB', (180, 200), '#bb7755').save(folder/'photo.png')
    write_wave(folder/'reference.wav', np.sin(np.arange(16000)*.15)*.2, 16000)
    (folder/'original.pptx').write_bytes(b'test-only source, not a real lecture')
    with store.edit(pid) as p:
        for role, name in [('pptx','original.pptx'),('reference_audio','reference.wav'),('photo','photo.png')]:
            p['assets'][role] = {'id': role, 'selected': name, 'original': name, 'sha256': digest(folder/name), 'state': 'ready',
                                 'authorization': {'confirmed': True}, 'teacher_id': 'test-only', 'selection': {'transcript': '测试对应文字'}}
        p['slides'] = [{'source_page_id': 'test:1', 'source_index': 1, 'image': 'page.png', 'image_sha256': digest(folder/'page.png'), 'body': 'test', 'notes_original': '', 'anomalies': []}]
        p['scenes'] = [new_scene(['test:1']), new_scene(['test:1']), new_scene(['test:1'])]
        for i, scene in enumerate(p['scenes']):
            add_version(p, scene, 'manual', f'测试第{i+1}句。数组[1,2,3]。', f'测试第{i+1}句。{{{{pause:0.2}}}}数组一二三。')
            scene['overrides'] = {'show_teacher': i != 1, 'layout': 'sidebar' if i == 2 else 'overlay', 'position': 'top-left' if i == 0 else 'bottom-right'}
    p = store.get(pid)

    def fake(job, role, request):
        calls.append((role, request))
        pipeline.boundary(job)
        native_folder = folder / ('fake-' + __import__('uuid').uuid4().hex)
        native_folder.mkdir()
        if role == 'tts':
            arrays, timeline, offset, sr = [], [], 0, 16000
            pad = np.zeros(round(request['pause_before']*sr))
            arrays.append(pad); offset += len(pad)
            for index, segment in enumerate(request['speech_segments']):
                if segment['text'].strip():
                    tone = np.sin(np.arange(8000)*(.1+len(calls)*.005))*.2
                    arrays.append(tone)
                    timeline.append({'segment_index': index, 'start_seconds': offset/sr, 'end_seconds': (offset+len(tone))/sr, 'text_sha256': fingerprint(segment['text'])})
                    offset += len(tone)
                pad = np.zeros(round(segment['pause_after']*sr))
                arrays.append(pad); offset += len(pad)
            out = native_folder/'audio.wav'
            write_wave(out, np.concatenate(arrays), sr)
            info = pipeline.media.inspect(out, 'audio')
        else:
            out = native_folder/'portrait.mp4'
            duration = pipeline.media.inspect(request['audio'], 'audio')['duration_seconds']
            run([pipeline.media.ffmpeg, '-v','error','-y','-f','lavfi','-i','color=c=blue:s=96x128:r=25','-i',request['audio'],'-t',duration,'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',out],30)
            info = pipeline.media.inspect(out, 'video')
            timeline = []
        return {'state': 'media_ready', 'output': info, 'actual_provider': 'TEST_ONLY', 'request_id': str(len(calls)), 'code_revision': 'test',
                'actual_weight_version': 'test', 'native_model_record': {'speech_timeline': timeline}, 'elapsed_seconds': .01}
    pipeline.native = fake
    client = TestClient(app)
    client.post('/api/session', json={'token': store.token})
    return service, p, calls, client, fake


def submit(rig, ids=None):
    service, p, _, _, _ = rig
    body = {'preview': True, 'revision': service.store.get(p['id'])['revision']}
    if ids is not None:
        body['scene_ids'] = ids
    return service.m3.submit(p['id'], body)


def execute(rig):
    service = rig[0]
    service.execute(service.store.claim())


def test_unreviewed_gate_draft_idempotency_cancel(rig):
    service, p, calls, c, _ = rig
    endpoint = f"/api/projects/{p['id']}/media-jobs"
    assert c.post(endpoint,json={}).status_code == 422
    body = {'preview':True,'revision':p['revision'],'scene_ids':[p['scenes'][0]['id']]}
    a=c.post(endpoint,json=body); b=c.post(endpoint,json=body)
    assert a.status_code == b.status_code == 202
    assert a.json()['id'] == b.json()['id'] and not calls
    assert c.post(endpoint+'/'+a.json()['id']+'/cancel').json()['state']=='canceled'
    assert c.post(endpoint+'/'+a.json()['id']+'/review',json={}).status_code==422
    assert c.post(endpoint+'/'+a.json()['id']+'/retry').status_code==422
    assert c.get(endpoint+'/'+a.json()['id']+'/exports/mp4').status_code==404


def test_duplicate_running_message_cannot_replace_execution_owner(rig):
    service,p,calls,c,_=rig
    j=submit(rig,[p['scenes'][0]['id']])
    claimed=service.store.claim()
    claimed['execution']='existing-owner'
    service.store.update_job(claimed)
    service.m3.execute(copy.deepcopy(claimed))
    assert not calls
    assert service.m3.get(p['id'],j['id'])['execution']=='existing-owner'
    service.m3.recover();execute(rig)
    assert service.m3.get(p['id'],j['id'])['state']=='completed'


def test_actual_encoded_exports_hidden_layout_and_timeline(rig):
    service,p,calls,c,_=rig
    job=submit(rig); execute(rig)
    j=service.m3.get(p['id'],job['id'])
    assert j['state']=='completed',j.get('error')
    assert j['result']['preview'] and j['result']['width']==1280 and j['result']['height']==720
    assert j['result']['video_start_seconds']==0
    assert j['result']['av_end_delta_seconds'] <= .1
    assert [role for role,_ in calls].count('photo')==2
    assert j['scenes'][1]['stage_states']['portrait']=='not_required'
    assert j['result']['timeline'][1]['start']==j['result']['timeline'][0]['end']
    frame=service.store.folder(p['id'])/'boundary.png'
    run([service.media.ffmpeg,'-v','error','-y','-ss',str(j['result']['timeline'][2]['start']),'-i',service.store.file(p['id'],j['result']['path']),'-frames:v','1',frame],30)
    with Image.open(frame) as image:
        r,g,b=image.getpixel((1100,360))[:3]
    assert b>200 and r<30  # Exact third-page boundary must show its blue sidebar portrait.
    for scene in j['scenes']:
        assert scene['tts']['captions'][0]['end']==.5
        assert scene['tts']['captions'][1]['start']==.7
        assert '数组[1,2,3]' in scene['tts']['captions'][1]['text']
    for kind in ['mp4','srt','script','manifest']:
        assert c.get(f"/api/projects/{p['id']}/media-jobs/{j['id']}/exports/{kind}").status_code==200
    text=c.get(f"/api/projects/{p['id']}/media-jobs/{j['id']}/exports/srt").text
    assert '{{pause:' not in text and '一二三' not in text and '[1,2,3]' in text
    # Tampered output is blocked at download, not silently exported.
    service.store.file(p['id'],j['result']['exports']['script']).write_text('changed')
    assert c.get(f"/api/projects/{p['id']}/media-jobs/{j['id']}/exports/script").status_code==422


def test_layout_only_reuses_media_script_change_invalidates_local(rig):
    service,p,calls,c,_=rig
    j=submit(rig);execute(rig); first=service.m3.get(p['id'],j['id'])
    calls.clear()
    with service.store.edit(p['id']) as doc:
        doc['scenes'][0]['overrides']['position']='bottom-left'
    j=submit(rig);execute(rig); second=service.m3.get(p['id'],j['id'])
    assert second['state']=='completed',second['error']
    assert not calls
    assert second['scenes'][0]['cache_hits']['tts']['hit']
    assert second['scenes'][0]['cache_hits']['portrait']['hit']
    assert not second['scenes'][0]['cache_hits']['compose']['hit']
    assert second['scenes'][2]['cache_hits']['compose']['hit']
    with service.store.edit(p['id']) as doc:
        add_version(doc,doc['scenes'][0],'manual','新句。数组[1,2,3]。','新句。数组一二三。')
        doc['scenes'][0]['overrides']['pause_after']=.9
    j=submit(rig);execute(rig); third=service.m3.get(p['id'],j['id'])
    assert [role for role,_ in calls]==['tts','photo']
    assert third['scenes'][2]['cache_hits']['compose']['hit']
    assert third['result']['timeline'][1]['start']>second['result']['timeline'][1]['start']


def test_failure_retry_and_cancel_late_result_fenced(rig):
    service,p,calls,c,fake=rig
    count=0
    def failing(job,role,request):
        if role=='photo':
            raise Failure('RESOURCE_INSUFFICIENT','injected GPU exhaustion')
        return fake(job,role,request)
    service.m3.native=failing
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    job=service.m3.get(p['id'],j['id'])
    assert job['state']=='failed' and job['result'] is None and job['scenes'][0]['tts']
    service.m3.retry(p['id'],j['id']);service.m3.native=fake;calls.clear();execute(rig)
    job=service.m3.get(p['id'],j['id'])
    assert job['state']=='completed' and job['generation']==2
    assert [role for role,_ in calls]==['photo']
    with service.store.edit(p['id']) as doc:
        doc['scenes'][0]['overrides']['speed']=1.2
    def cancel_during(job,role,request):
        result=fake(job,role,request)
        service.m3.cancel(p['id'],job['id'])
        return result
    service.m3.native=cancel_during
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    job=service.m3.get(p['id'],j['id'])
    assert job['state']=='canceled' and job['result'] is None


def test_worker_recovery_preserves_validated_cache_and_fences_old_generation(rig):
    service,p,calls,c,fake=rig
    def stop_after_audio(job,role,request):
        if role=='photo':
            raise Failure('WORKER_INTERRUPTED','injected process stop')
        return fake(job,role,request)
    service.m3.native=stop_after_audio
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    job=service.m3.get(p['id'],j['id'])
    assert job['state']=='queued' and job['scenes'][0]['tts']
    old=copy.deepcopy(job); old['execution']='old';old['_started']=__import__('time').perf_counter()
    service.m3.native=fake; calls.clear(); execute(rig)
    assert service.m3.get(p['id'],j['id'])['state']=='completed'
    assert [r for r,_ in calls]==['photo']
    with pytest.raises(Failure,match='旧工作进程'):
        service.m3.save(old)


def test_review_draft_persists_and_no_agent_confirmation(rig):
    service,p,_,c,_=rig
    endpoint=f"/api/projects/{p['id']}/m1-review"
    state=c.get(endpoint).json()
    body={'binding':state['binding'],'checks':{k:None for k in state['criteria']},'note':'测试记录：待教师评审','completed':False}
    assert c.post(endpoint,json=body).status_code==200
    assert c.get(endpoint).json()['saved']['completed'] is False
    assert c.post(endpoint,json={**body,'completed':True}).status_code==422
    with service.store.edit(p['id']) as doc:
        doc['assets']['photo']['selection']={'box':[1,1,50,50]}
    assert c.get(endpoint).json()['stale'] is True
    assert c.post(endpoint,json=body).status_code==409


def test_old_model_samples_cannot_be_reapproved_for_changed_inputs(rig):
    service,p,_,c,_=rig
    state=service.m3.review.state(p['id'])
    service.m3.review.gallery=lambda pid:[{'baseline_sample':True,'compatible_with_current':False,'id':'test','kind':'video'}]
    with pytest.raises(Failure,match='不兼容'):
        service.m3.review.save(p['id'],{'binding':state['binding'],'checks':{k:True for k in state['criteria']},'note':'isolated test only','completed':True})


def test_sentence_mapping_never_uses_character_time():
    v={'id':'test','display_text':'E=mc²。下一句。','reading_text':'能量等于质量乘以光速平方。下一个句子。','control_events':[]}
    pair=units(v);runs,groups=speech_runs(v,pair,0)
    cues=captions(pair,groups,[{'segment_index':0,'text_sha256':'x','start_seconds':.2,'end_seconds':4.7},{'segment_index':1,'text_sha256':'y','start_seconds':5,'end_seconds':6}])
    assert cues[0]['end']==4.7 and cues[0]['text']=='E=mc²。'
    with pytest.raises(Failure):
        units({**v,'reading_text':'合并为一句。'})
    explicit=units({**v,'reading_text':'合并为一句。'},[{'display':v['display_text'],'reading':'合并为一句。'}])
    assert len(explicit)==1
    with pytest.raises(Failure):
        units(v,[{'display':'删句。','reading':v['reading_text']}])


def test_control_events_at_trailing_whitespace_and_eof_are_not_lost():
    version={'id':'test','display_text':'数组[1,2,3]。','reading_text':'数组一二三。  ',
             'control_events':[{'offset':7,'seconds':2},{'offset':len('数组一二三。  '),'seconds':9}]}
    paired=units(version)
    runs,groups=speech_runs(version,paired,10)
    assert sum(r['pause_after'] for r in runs)==21
    assert all(r['pause_after']<=10 for r in runs)
    assert len(runs)==len(groups)


def test_identity_layout_breaks_keep_original_spans_and_measured_timing():
    v={'id':'identity','display_text':'第一\n句。第二句。  ', 'reading_text':'第一句。\n 第二\n句。  ', 'control_events':[]}
    paired=units(v)
    assert len(paired)==2
    assert ''.join(p['display'] for p in paired)==v['display_text']
    assert ''.join(p['reading'] for p in paired)==v['reading_text']
    runs,groups=speech_runs(v,paired,0)
    cues=captions(paired,groups,[{'segment_index':0,'text_sha256':'x','start_seconds':.3,'end_seconds':2.1},
                              {'segment_index':1,'text_sha256':'y','start_seconds':3.4,'end_seconds':5.8}])
    assert [(c['start'],c['end']) for c in cues]==[(.3,2.1),(3.4,5.8)]


def test_reference_and_model_cache_invalidation(rig):
    service,p,calls,c,_=rig
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    original=service.m3.get(p['id'],j['id'])['scenes'][0]['cache_hits']['tts']['key']
    with service.store.edit(p['id']) as doc:
        doc['assets']['reference_audio']['selection']['transcript']='新的参考对应'
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    assert service.m3.get(p['id'],j['id'])['scenes'][0]['cache_hits']['tts']['key']!=original
    service.m1['models']['tts']['code_revision']='test-new-version'
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    assert not service.m3.get(p['id'],j['id'])['scenes'][0]['cache_hits']['tts']['hit']


def test_formal_sample_gates_and_snapshot_independence(rig):
    service,p,calls,c,_=rig
    with service.store.edit(p['id']) as doc:
        for scene in doc['scenes']:
            scene['confirmed']=scene['current_version']
            current(scene)['teacher_review']={'test_only': True}
            scene['audition']={'human_review':{'test_only':True}}
    frozen=service.store.snapshot(service.store.get(p['id']),{'ready':True,'test_only':True})
    endpoint=f"/api/projects/{p['id']}/media-jobs"
    body={'snapshot_id':frozen['snapshot_id']}
    assert c.post(endpoint,json=body).json()['error']['code']=='M1_REVIEW_REQUIRED'
    service.m3.review.ready=lambda p:True  # test only; never persisted as teacher decision
    assert c.post(endpoint,json=body).json()['error']['code']=='SAMPLE_REVIEW_REQUIRED'
    sample=c.post(endpoint,json={**body,'scene_ids':[p['scenes'][0]['id']]}).json();execute(rig)
    assert service.m3.get(p['id'],sample['id'])['state']=='completed'
    checks={k:True for k in ['identity_voice','lipsync_seams','subtitles_timing','layout_no_obstruction']}
    assert c.post(endpoint+'/'+sample['id']+'/review',json={'checks':checks,'note':'isolated test only'}).status_code==200
    with service.store.edit(p['id']) as doc:
        add_version(doc,doc['scenes'][0],'manual','新未审核内容。')
    for item in service.m3.layouts(p['id'], frozen['snapshot_id']):
        service.m3.save_layout(p['id'], frozen['snapshot_id'], {'scene_id': item['scene_id'], 'binding': item['binding'], 'no_obstruction': True, 'note': 'isolated test only'})
    course=c.post(endpoint,json=body)
    assert course.status_code==202,course.text
    execute(rig)
    completed=service.m3.get(p['id'],course.json()['id'])
    assert completed['state']=='completed' and completed['payload']['snapshot']['scenes'][0]['current_version']==frozen['scenes'][0]['current_version']


@pytest.mark.parametrize('code',['TIMEOUT','ABNORMAL_SILENCE','RUN_FAILED'])
def test_required_stage_failure_never_completes_and_retry_is_bounded(rig,code):
    service,p,calls,c,_=rig
    def broken(job,role,request):
        raise Failure(code,'injected required stage failure')
    service.m3.native=broken
    j=submit(rig,[p['scenes'][0]['id']]);execute(rig)
    for _ in range(2):
        failed=service.m3.get(p['id'],j['id'])
        assert failed['state']=='failed' and failed['result'] is None and failed['error']['code']==code
        service.m3.retry(p['id'],j['id']);execute(rig)
    with pytest.raises(Failure,match='最多三代'):
        service.m3.retry(p['id'],j['id'])


def test_abrupt_owner_death_restarts_sqlite_job_and_kills_owned_native_tree(rig,tmp_path):
    import os
    import subprocess
    import sys
    import time
    from mooc_m1.adapters import LocalModelAdapter
    service,p,calls,c,_=rig
    submit(rig);execute(rig)
    assert service.m3.list(p['id'])[0]['state']=='completed'
    calls.clear()
    with service.store.edit(p['id']) as doc:
        doc['scenes'][0]['overrides']['position']='bottom-left'
    job=submit(rig)
    marker=tmp_path/'native-pid.txt'
    child_code="import os,time;from pathlib import Path;Path("+repr(str(marker))+").write_text(str(os.getpid()));time.sleep(120)"
    child=tmp_path/'crash-worker.py'
    child.write_text('''import sys
from pathlib import Path
from mooc_m2.service import Service
from mooc_m1.core import run
service=Service(CONFIG)
original=service.m3.process_scene
def pause_after_validated_scene(job,scene):
    original(job,scene)
    run([sys.executable,'-c',CHILD_CODE],timeout=180)
service.m3.process_scene=pause_after_validated_scene
service.execute(service.store.claim())
'''.replace('CONFIG',repr(service.config)).replace('CHILD_CODE',repr(child_code)),encoding='utf-8')
    environment=dict(os.environ,PYTHONPATH=str(Path(__file__).resolve().parents[1]),PYTHONUTF8='1')
    process=subprocess.Popen([sys.executable,str(child)],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:
        limit=time.monotonic()+30
        while not marker.is_file() and process.poll() is None and time.monotonic()<limit:
            time.sleep(.1)
        assert marker.is_file(),process.communicate(timeout=1)
        owned_pid=int(marker.read_text())
        process.kill()  # Only owner: Windows Job Object must terminate its own descendants.
        process.communicate(timeout=10)
        if os.name=='nt':
            limit=time.monotonic()+10
            while LocalModelAdapter._pid_alive(owned_pid) and time.monotonic()<limit:
                time.sleep(.1)
            assert not LocalModelAdapter._pid_alive(owned_pid)
        else:
            os.kill(owned_pid,15)
        interrupted=service.m3.get(p['id'],job['id'])
        assert interrupted['state']=='running' and interrupted['scenes'][0]['state']=='valid'
        service.store.recover();service.m3.recover()
        assert service.m3.get(p['id'],job['id'])['state']=='queued'
        execute(rig)
        recovered=service.m3.get(p['id'],job['id'])
        assert recovered['state']=='completed' and recovered['recoveries']==1
        assert not calls  # All verified speech/portrait stages survived actual owner death.
        assert all(s['cache_hits']['tts']['hit'] for s in recovered['scenes'])
    finally:
        if process.poll() is None:
            process.kill();process.communicate(timeout=10)
