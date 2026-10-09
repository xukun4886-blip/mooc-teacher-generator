"""M4 engineering fault checks; no synthetic evidence claims model quality."""
import os
import sys
import json
import httpx
import pytest
from mooc_m1.core import Failure, run
from test_m2 import app, client, seed
from test_m2_batch_review import provider
from test_m3 import rig, submit, execute, write_wave
import numpy as np


def test_free_vision_allowlist_rejects_paid_names_and_other_endpoints(app, monkeypatch):
    svc = app.state.service
    monkeypatch.setenv('M4_FREE_VISION_TEST_KEY', 'fixture-key')
    svc.config['ai'] = {'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'model': 'glm-4.1v-thinking-flash', 'api_key_env': 'M4_FREE_VISION_TEST_KEY',
        'allow_external': True, 'allow_paid': False}
    assert svc.ai_health()['ready']
    for model in ['glm-4.1v-thinking-flashx', 'glm-4.6v', 'glm-4.6v-flash-unknown']:
        svc.config['ai']['model'] = model
        assert not svc.ai_health()['ready']
    svc.config['ai'].update(model='glm-4.1v-thinking-flash', base_url='https://other.invalid/api/paas/v4')
    assert not svc.ai_health()['ready']
    svc.config['ai'].update(base_url='https://open.bigmodel.cn/api/paas/v4', allow_external=False)
    assert not svc.ai_health()['ready']


@pytest.mark.skipif(os.name != 'nt', reason='Windows process fencing regression')
def test_short_process_fencing_stress():
    # Immediate exit used to race AssignProcessToJobObject.
    for _ in range(40):
        assert run([sys.executable, '-c', 'print("completed")'], 10)['stdout'].strip() == 'completed'


def test_rate_limit_retains_attempts_and_retry_after(app, client, monkeypatch):
    p = seed(app)
    svc, sent = provider(app, monkeypatch)
    original = httpx.Client.post
    count = 0
    def limited(self, url, **kw):
        nonlocal count
        if str(url).startswith('http://127.0.0.1:9999/'):
            count += 1
            return httpx.Response(429, headers={'retry-after': '7'}, request=httpx.Request('POST', url))
        return original(self, url, **kw)
    waits = []
    monkeypatch.setattr('httpx.Client.post', limited)
    monkeypatch.setattr(svc.stop, 'wait', lambda seconds: waits.append(seconds) or False)
    svc.queue_ai(p['id'], p['revision'], [p['scenes'][0]['id']])
    svc.execute(svc.store.claim())
    j = svc.store.jobs(p['id'])[0]
    assert j['state'] == 'failed' and j['error']['code'] == 'AI_RATE_LIMITED'
    assert count == 4 and waits == [7, 15, 30]
    assert [a['status'] for a in j['ai_attempts']] == [429] * 4
    assert not svc.store.get(p['id'])['scenes'][0]['versions']


@pytest.mark.parametrize('reading,ok', [('第一句。第二句。', True), ('只有一句。', False)])
def test_invalid_pairing_recovers_only_complete_sentence_mapping(app, client, monkeypatch, reading, ok):
    p = seed(app)
    def reply(req):
        draft = {'display_text': '第一句。第二句。', 'reading_text': reading,
                 'knowledge_points': [], 'questions': [], 'terms': [], 'pending': [], 'extensions': [],
                 'sentence_pairs': [{'display': '第一句。', 'reading': '第一句。'}]}
        return httpx.Response(200, json={'id': 'pairing-fixture', 'choices': [{'message': {'content': json.dumps(draft)}}]},
                              request=httpx.Request('POST', 'http://localhost'))
    svc, _ = provider(app, monkeypatch, reply)
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    if ok:
        svc.generate_ai(j)
        v = svc.store.get(p['id'])['scenes'][0]['versions'][-1]
        assert v['display_text'] == v['reading_text'] == '第一句。第二句。'
        assert len(v['provenance']['sentence_pairs']) == 2
        assert v['provenance']['pairing_method'] == 'complete_text_sentence_boundaries'
    else:
        with pytest.raises(Failure) as exc:
            svc.generate_ai(j)
        assert exc.value.code == 'AI_FORMAT_INVALID'
        assert not svc.store.get(p['id'])['scenes'][0]['versions']
    assert svc.store.jobs(p['id'])[0]['ai_attempts'][0]['format_error'] == 'SUBTITLE_MAPPING_REQUIRED'


def test_portrait_service_failure_preserves_voice_without_success(rig):
    svc, p, calls, client, native = rig
    def fail_portrait(job, role, request):
        if role == 'photo':
            raise Failure('RUN_FAILED', 'Injected portrait service failure')
        return native(job, role, request)
    svc.m3.native = fail_portrait
    j = submit(rig, [p['scenes'][0]['id']])
    execute(rig)
    failed = svc.m3.get(p['id'], j['id'])
    assert failed['state'] == 'failed' and failed['result'] is None
    assert failed['scenes'][0]['stage_states']['tts'] == 'valid'
    assert failed['scenes'][0]['stage_states']['portrait'] == 'failed'
    assert client.get(f"/api/projects/{p['id']}/media-jobs/{j['id']}/exports/mp4").status_code == 404
    svc.m3.native = native
    svc.m3.retry(p['id'], j['id'])
    calls.clear()
    execute(rig)
    recovered = svc.m3.get(p['id'], j['id'])
    assert recovered['state'] == 'completed' and recovered['attempts'][0]['error']['code'] == 'RUN_FAILED'
    assert [role for role, _ in calls] == ['photo']


def test_decodable_silent_output_never_published_as_success(rig):
    svc, p, _, client, native = rig
    def silent(job, role, request):
        result = native(job, role, request)
        if role == 'tts':
            # Valid WAV headers and duration, but actual samples are all zero.
            write_wave(result['output']['path'], np.zeros(20800), 16000)
        return result
    svc.m3.native = silent
    j = submit(rig, [p['scenes'][0]['id']])
    execute(rig)
    failed = svc.m3.get(p['id'], j['id'])
    assert failed['state'] == 'failed' and failed['error']['code'] == 'ABNORMAL_SILENCE'
    assert failed['result'] is None
    with svc.store.connection() as db:
        assert not db.execute('SELECT 1 FROM m3_cache WHERE project_id=?', (p['id'],)).fetchone()
    assert not list(svc.store.folder(p['id']).rglob('*.tmp'))


def test_restart_cleans_only_unpublished_project_media(rig):
    svc, p, _, _, _ = rig
    j = submit(rig, [p['scenes'][0]['id']])
    svc.store.claim()
    paths = ['m3/cache/compose/test/publishing.mp4', 'm3/cache/tts/test/audio.tmp',
             'm3/jobs/test/publishing-course.mp4', 'm3/native/requests/test/native.log',
             'm3/cache/compose/test/page.mp4']
    for relative in paths:
        path = svc.store.file(p['id'], relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'evidence or unfinished output')
    svc.m3.recover()
    assert svc.m3.get(p['id'], j['id'])['state'] == 'queued'
    assert all(not svc.store.file(p['id'], relative).exists() for relative in paths[:3])
    assert all(svc.store.file(p['id'], relative).is_file() for relative in paths[3:])
