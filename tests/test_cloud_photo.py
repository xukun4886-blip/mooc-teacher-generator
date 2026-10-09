"""Transport/recovery tests with synthetic media, never portrait quality evidence."""
import copy
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from mooc_cloud.adapter import RemotePhotoAdapter
from mooc_cloud.protocol import PROTOCOL, health, pinned, settings
from mooc_cloud.server import Worker, create_app
from mooc_m1.core import Failure, digest, run, write_json
from mooc_m2.content import fingerprint
from test_m3 import rig

MODEL = {'provider': 'SadTalker', 'code_revision': 'engineering-fixture', 'weight_version': 'test-only',
         'weights': [{'name': 'test', 'sha256': 'a'*64}], 'implementation_sha256': 'b'*64,
         'render': {'size': 256, 'preprocess': 'full', 'enhancer': None, 'fps': 25, 'frame_storage': 'detached_cpu_per_frame_v1'}}


class TestEngine:
    __test__ = False
    def __init__(self, config, model):
        self.config = config
        self.loaded = False
        self.calls = 0

    def generate(self, photo, audio, folder, batch, boundary):
        boundary()
        self.calls += 1
        was_loaded = self.loaded
        self.loaded = True
        output = folder / 'portrait.mp4'
        run([self.config['ffmpeg'], '-v','error','-y','-f','lavfi','-i','color=c=blue:s=96x128:r=25',
             '-i', audio, '-shortest', '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac', output], 30)
        return output, {'model_warm': was_loaded, 'photo_preprocess_cache_hit': was_loaded, 'engineering_only': True}


class Bridge(httpx.BaseTransport):
    def __init__(self, client):
        self.client = client
        self.fail_after_post = False
    def handle_request(self, request):
        response = self.client.request(request.method, request.url.raw_path.decode(),
                                       content=request.read(), headers=dict(request.headers))
        if self.fail_after_post and request.method == 'POST' and request.url.path.endswith('/jobs'):
            self.fail_after_post = False
            raise httpx.ReadError('simulated reply lost')
        return httpx.Response(response.status_code, content=response.content, headers=response.headers)


@pytest.fixture
def cloud(tmp_path, media, monkeypatch):
    monkeypatch.setenv('MOOC_CLOUD_TOKEN', 'test-only-token-01234567890123456789')
    config = {'storage': str(tmp_path / 'worker'), 'ffmpeg': media.ffmpeg, 'ffprobe': media.ffprobe,
              'price': {'hourly_rate': 0, 'currency': 'CNY'}}
    app = create_app(config, engine_factory=TestEngine, model=MODEL)
    with TestClient(app) as client:
        transport = Bridge(client)
        selected = settings({'mode': 'cloud', 'url': 'http://127.0.0.1:8787', 'allow_uploads': True}, loopback=True)
        selected = pinned(selected, health(selected, transport=transport))
        yield app.state.worker, client, transport, selected


def inputs(rig):
    service, p, *_ = rig
    folder = service.store.folder(p['id'])
    return {'photo': str(folder / 'photo.png'), 'audio': str(folder / 'reference.wav'),
            'authorized': True, 'authorization_record': 'test-only', 'operation_id': 'test-page-1', 'generation': 1}


def test_default_local_validation_and_missing_credentials(monkeypatch):
    assert settings({}) == {'mode': 'local'}
    for url in ['http://example.com', 'https://user:secret@example.com', 'https://example.com/?token=x']:
        with pytest.raises(Failure):
            settings({'mode': 'cloud', 'url': url})
    monkeypatch.delenv('MOOC_CLOUD_TOKEN', raising=False)
    with pytest.raises(Failure, match='MOOC_CLOUD_TOKEN'):
        health(settings({'mode': 'cloud', 'url': 'https://example.com'}))


def test_roundtrip_idempotency_current_inputs_and_resumed_download(cloud, rig, tmp_path):
    worker, client, transport, selected = cloud
    adapter = RemotePhotoAdapter(selected, rig[0].media, tmp_path/'requests', transport=transport)
    request = inputs(rig)
    first = adapter.generate(request)
    assert first['state'] == 'media_ready' and not first['quality_verified']
    assert first['native_driving']['audio_sha256'] == digest(request['audio'])
    assert worker.engine.calls == 1
    path = __import__('pathlib').Path(first['output']['path'])
    data = path.read_bytes()
    path.with_name('portrait.mp4.part').write_bytes(data[:101])
    path.unlink()
    second = adapter.generate(request)
    assert second['output']['sha256'] == first['output']['sha256']
    assert worker.engine.calls == 1
    request['operation_id'] = 'test-page-2'
    third = adapter.generate(request)
    assert third['native_model_record']['model_warm']
    assert worker.engine.calls == 2
    assert client.get('/v1/health').status_code == 401


def test_ambiguous_submission_queries_same_remote_job(cloud, rig, tmp_path):
    worker, _, transport, selected = cloud
    adapter = RemotePhotoAdapter(selected, rig[0].media, tmp_path/'requests', transport=transport)
    transport.fail_after_post = True
    request = inputs(rig)
    with pytest.raises(Failure) as error:
        adapter.generate(request)
    assert error.value.code == 'CLOUD_UNAVAILABLE'
    request['generation'] = 2
    result = adapter.generate(request)
    assert result['state'] == 'media_ready' and worker.engine.calls == 1
    with worker.db() as db:
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 1


def test_upload_and_budget_guard_before_any_upload(cloud, rig, tmp_path):
    worker, _, transport, selected = cloud
    config = {**selected, 'allow_uploads': False}
    with pytest.raises(Failure) as error:
        RemotePhotoAdapter(config, rig[0].media, tmp_path, transport=transport).generate(inputs(rig))
    assert error.value.code == 'CLOUD_UPLOAD_NOT_AUTHORIZED'
    assert not (worker.root/'blobs').exists()
    observed = {'price': {'hourly_rate': 2, 'currency': 'CNY'}, 'ready': True}
    with pytest.raises(Failure) as error:
        pinned(selected, observed)
    assert error.value.code == 'CLOUD_BUDGET_BLOCKED'


def test_model_change_blocks_generation(cloud, rig, tmp_path):
    worker, _, transport, selected = cloud
    worker.model = {**worker.model, 'code_revision': 'changed'}
    adapter = RemotePhotoAdapter(selected, rig[0].media, tmp_path, transport=transport)
    assert not adapter.health()['ready']
    with pytest.raises(Failure) as error:
        adapter.generate(inputs(rig))
    assert error.value.code == 'MODEL_CHANGED' and not (worker.root/'blobs').exists()


def test_hash_upload_rejection_and_no_cross_audio_result(cloud, rig, tmp_path):
    worker, client, transport, selected = cloud
    headers = {'Authorization':'Bearer test-only-token-01234567890123456789', 'X-Content-Bytes':'3'}
    response = client.put('/v1/blobs/'+'a'*64+'?kind=audio',content=b'bad',headers=headers)
    assert response.status_code==422 and not worker.blob('a'*64).exists()
    adapter = RemotePhotoAdapter(selected, rig[0].media, tmp_path/'requests', transport=transport)
    request=inputs(rig)
    result=adapter.generate(request)
    jid=result['remote_receipt']['id']
    with worker.db() as db:
        job=worker.get(jid,db);job['audio_sha256']='f'*64;worker.save(job,db)
    with pytest.raises(Failure) as error:
        adapter.generate(request)
    assert error.value.code=='CLOUD_INPUT_MISMATCH'


def test_web_config_revision_busy_history_and_original_signature(rig, monkeypatch):
    service, p, _, client, _ = rig
    endpoint = f"/api/projects/{p['id']}/photo-server"
    original = service.course.signature(p)
    original_review = service.m3.review.binding(p)
    assert client.put(endpoint, json={'revision':p['revision'], 'settings':{'mode':'local'}}).status_code == 200
    assert service.course.signature(service.store.get(p['id'])) == original
    assert client.put(endpoint, json={'revision':p['revision'], 'settings':{'mode':'local'}}).status_code == 409
    import mooc_cloud.protocol as protocol
    monkeypatch.setattr(protocol, 'health', lambda c: {'ready':True,'model':MODEL,'model_key':fingerprint(MODEL),'price':{'hourly_rate':0,'currency':'CNY'},'protocol':PROTOCOL})
    rev = service.store.get(p['id'])['revision']
    setting = {'mode':'cloud','url':'https://worker.example','allow_uploads':True}
    response = client.put(endpoint, json={'revision':rev, 'settings':setting})
    assert response.status_code == 200
    assert 'token' not in response.json()['photo_execution']
    assert service.course.signature(response.json()) != original
    assert service.m3.review.binding(response.json()) != original_review
    job = service.m3.submit(p['id'], {'preview':True,'revision':response.json()['revision'],'scene_ids':[p['scenes'][0]['id']]})
    full = service.m3.get(p['id'],job['id'])
    assert full['payload']['models']['photo']['model_key'] == fingerprint(MODEL)
    response = client.put(endpoint, json={'revision':service.store.get(p['id'])['revision'], 'settings':{'mode':'local'}})
    assert response.status_code == 409
    service.m3.cancel(p['id'],job['id'])
    cloned = service.store.clone(p['id'])
    assert cloned['photo_execution']['mode'] == 'local'
    assert len(service.store.get(p['id'])['photo_execution_history']) == 2


def test_cancel_late_result_and_worker_restart_preserve_history(cloud, rig):
    worker, _, _, selected = cloud
    request = inputs(rig)
    for key in ['photo','audio']:
        path = __import__('pathlib').Path(request[key])
        dest = worker.blob(digest(path)); dest.parent.mkdir(exist_ok=True); dest.write_bytes(path.read_bytes())
    body = {'idempotency_key':'1'*64,'photo_sha256':digest(request['photo']), 'audio_sha256':digest(request['audio']),
            'model_key':selected['model_key'],'batch_size':1,'max_seconds':1800,'allow_paid':False,'max_cost':0}
    # Stop the asynchronous claimant and inject a stale running attempt.
    worker.close()
    job = worker.submit(body)
    job.update(state='running', execution='old-worker')
    with worker.db() as db:
        worker.save(job,db)
    worker.cancel(job['id'])
    worker.stop.clear()
    worker.execute(job)
    assert worker.get(job['id'])['state'] == 'canceled'
    body['idempotency_key']='2'*64
    recovery = worker.submit(body); recovery.update(state='running',execution='interrupted')
    with worker.db() as db:
        worker.save(recovery,db)
    replacement = Worker(worker.config, TestEngine, MODEL)
    replacement.start()
    try:
        deadline = time.monotonic()+15
        while replacement.get(recovery['id'])['state'] in {'queued','running'} and time.monotonic()<deadline:
            time.sleep(.1)
        restored = replacement.get(recovery['id'])
        assert restored['state']=='completed' and restored['recoveries']==1
        assert restored['history'][0]['execution']=='interrupted'
        assert replacement.get(job['id'])['state']=='canceled'
    finally:
        replacement.close()
