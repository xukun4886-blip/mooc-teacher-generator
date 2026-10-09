"""One-click workflow behavior; model quality is covered by separate real evidence."""
import copy
import json
from test_m3 import rig, execute
from mooc_m1.core import Failure
from mooc_m2.content import add_version, current, find_scene


def test_corrected_punctuation_mapping_creates_one_new_bounded_run_and_keeps_legacy_failure(rig):
    from mooc_m3.timeline import units
    from mooc_m2.content import fingerprint
    service,p,_,client,_=rig;pid=p['id'];path=f'/api/projects/{pid}'
    with service.store.edit(pid) as edited:
        edited['assets']['photo']['metadata']=service.media.inspect(service.store.file(pid,'photo.png'),'photo')
        add_version(edited,edited['scenes'][0],'manual','示例（正文。)')
    first=client.post(path+'/generate').json();execute(rig)
    coordinator=service.course.get(pid,first['id'])
    legacy=service.m3.get(pid,coordinator['result']['media_job_id'])
    legacy['scenes'][0]['paired']=units(legacy['scenes'][0]['version'])
    legacy['payload']['input_key']='legacy-uncoalesced-input'
    legacy.update(state='failed',generation=3,error={'code':'RUN_FAILED','source':'tts','message':'Inconsistent native sample rates'})
    service.store.update_job(legacy);before=fingerprint(legacy)
    versions=[s['current_version'] for s in service.store.get(pid)['scenes']]
    public=client.get(path+'/generation').json();assert public['retry_allowed']
    fresh=client.post(path+f"/generation/{first['id']}/retry").json()
    assert fresh['id']!=first['id'] and fresh['generation']==1
    assert client.post(path+'/generate').json()['id']==fresh['id']
    execute(rig)
    new=service.course.get(pid,fresh['id']);media=service.m3.get(pid,new['result']['media_job_id'])
    assert len(media['scenes'][0]['paired'])==1 and media['payload']['input_key']!=legacy['payload']['input_key']
    assert fingerprint(service.m3.get(pid,legacy['id']))==before
    assert [s['current_version'] for s in service.store.get(pid)['scenes']]==versions
    assert media['generation']==1


def test_complete_unreviewed_course_and_explicit_bound_confirmation(rig):
    service, p, calls, client, _ = rig
    pid = p['id']
    path = f'/api/projects/{pid}'
    with service.store.edit(pid) as edited:
        edited['assets']['photo']['metadata'] = service.media.inspect(service.store.file(pid, 'photo.png'), 'photo')
    p = service.store.get(pid)
    a = client.post(path + '/generate')
    b = client.post(path + '/generate')
    assert a.status_code == b.status_code == 202
    assert a.json()['id'] == b.json()['id']
    jid = a.json()['id']
    assert client.post(path + f'/generation/{jid}/confirm', json={'confirmed': True}).status_code == 422
    assert client.post(path + '/commands', json={'revision':p['revision'], 'action':'config','data':{'speed':1.1}}).status_code == 409
    execute(rig)  # Coordinator hands off to the existing queue.
    queued = client.get(path + '/generation').json()
    assert queued['state'] == 'queued' and queued['media']['preview'] is True
    execute(rig)  # Existing TTS / portraits / compose / exports, with test adapters.
    done = client.get(path + '/generation').json()
    assert done['state'] == 'completed' and done['teacher_confirmation'] is None
    assert all(not s['confirmed'] and not current(s)['teacher_review'] for s in service.store.get(pid)['scenes'])
    assert client.post(path + '/snapshots', json={'revision':service.store.get(pid)['revision']}).status_code == 422
    assert client.get(path + f"/media-jobs/{done['media']['id']}/exports/mp4").status_code == 200
    response = client.post(path + f'/generation/{jid}/confirm', json={'confirmed':True})
    assert response.status_code == 200 and response.json()['formal_acceptance'] is False
    assert client.get(path+'/generation').json()['teacher_confirmation']['sha256'] == done['media']['result']['sha256']
    assert client.post(path+'/generate').json()['id'] == jid
    with service.store.edit(pid) as edited:
        add_version(edited, edited['scenes'][0], 'manual', '修改后的讲解。')
    assert client.get(path+'/generation').json()['is_current'] is False
    assert client.post(path+f'/generation/{jid}/confirm',json={'confirmed':True}).status_code == 409
    assert service.m3.review.get('course:'+done['media']['id'])  # History preserved.


def test_script_failure_retry_and_worker_recovery_reuse_finished_pages(rig, monkeypatch):
    service, p, _, client, _ = rig
    pid=p['id']; path=f'/api/projects/{pid}'
    with service.store.edit(pid) as edited:
        for s in edited['scenes']:
            s['current_version']=None; s['versions']=[]
    generated=[]
    def ai(job):
        sid=job['payload']['scene_id']
        if len(generated)==1:
            raise Failure('AI_SERVICE_FAILED','讲稿服务连接失败，请重试')
        with service.store.edit(pid) as edited:
            add_version(edited,find_scene(edited,sid),'ai','真实测试稿。')
        generated.append(sid)
    monkeypatch.setattr(service,'generate_ai',ai)
    jid=client.post(path+'/generate').json()['id']; execute(rig)
    failed=client.get(path+'/generation').json()
    assert failed['state']=='failed' and failed['scripts_ready']==1
    assert client.post(path+f'/generation/{jid}/retry').status_code==202
    running=service.store.claim()
    service.store.recover(); service.course.recover()
    restored=service.course.get(pid,jid)
    assert restored['state']=='queued'
    def success(job):
        sid=job['payload']['scene_id']
        with service.store.edit(pid) as edited:
            add_version(edited,find_scene(edited,sid),'ai','真实测试稿。')
        generated.append(sid)
    monkeypatch.setattr(service,'generate_ai',success)
    execute(rig)
    queued=client.get(path+'/generation').json()
    assert queued['scripts_ready']==3 and queued['media']['progress']['total']==3
    assert len(generated)==len(set(generated))==3
    assert all(s['confirmed'] is None for s in service.store.get(pid)['scenes'])


def test_missing_assets_are_chinese_and_do_not_queue(rig):
    service,p,_,client,_=rig
    with service.store.edit(p['id']) as edited:
        edited['assets'].pop('reference_audio')
    response=client.post(f"/api/projects/{p['id']}/generate")
    assert response.status_code==422
    assert '参考语音' in response.json()['error']['message']
    assert service.course.latest(p['id']) is None


def test_actual_process_death_recovers_same_course_job(rig):
    import subprocess
    import sys
    service,p,_,client,_=rig
    jid=client.post(f"/api/projects/{p['id']}/generate").json()['id']
    process=subprocess.run([sys.executable,'-c',
        "import sys,os; from pathlib import Path; from mooc_m2.store import Store; s=Store(Path(sys.argv[1])); j=s.claim(); print(j['id'],flush=True); os._exit(9)",
        str(service.store.root)],capture_output=True,text=True,timeout=30)
    assert process.returncode==9 and jid in process.stdout
    assert service.course.get(p['id'],jid)['state']=='running'
    service.store.recover();service.course.recover()
    restored=service.course.get(p['id'],jid)
    assert restored['state']=='queued' and restored['id']==jid
    execute(rig)
    assert service.course.latest(p['id'])['media']['state']=='queued'


def test_cancelled_media_can_be_generated_again(rig):
    service,p,_,client,_=rig
    path=f"/api/projects/{p['id']}"
    first=client.post(path+'/generate').json()['id'];execute(rig)
    media=client.get(path+'/generation').json()['media']
    service.m3.cancel(p['id'],media['id'])
    new=client.post(path+'/generate')
    assert new.status_code==202 and new.json()['id']!=first


def test_quick_upload_reuses_teacher_and_keeps_previous_asset(rig):
    service,p,_,client,_=rig
    pid=p['id']
    response=client.post(f'/api/projects/{pid}/quick-assets/photo',
        data={'revision':p['revision']},files={'file':('new.png',service.store.file(pid,'photo.png').read_bytes(),'image/png')})
    assert response.status_code==200
    edited=service.store.get(pid)
    assert edited['assets']['photo']['teacher_id']==edited['assets']['reference_audio']['teacher_id']=='test-only'
    assert edited['asset_history'][-1]['sha256']==p['assets']['photo']['sha256']
    assert service.store.file(pid,'photo.png').is_file()


def test_retry_after_input_revision_creates_current_draft(rig):
    service,p,_,client,_=rig
    path=f"/api/projects/{p['id']}"
    jid=client.post(path+'/generate').json()['id'];execute(rig)
    old=client.get(path+'/generation').json()['media']['id']
    service.m3.cancel(p['id'],old)
    with service.store.edit(p['id']) as edited:
        edited['config']['speed']=1.1
    retried=client.post(path+f'/generation/{jid}/retry')
    assert retried.status_code==202 and retried.json()['id']!=jid
    execute(rig)
    latest=client.get(path+'/generation').json()
    assert latest['is_current'] is True and latest['media']['id']!=old
