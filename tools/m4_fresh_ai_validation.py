"""Fresh three-file uploads with the verified free vision model, not old scripts."""
import time
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, stamp, digest
from mooc_m2.content import fingerprint
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/M3/fresh-ai-validation.json'


def main():
    store = Store(ROOT / 'storage/m2')
    base = read_json(ROOT / 'docs/evidence/M3/long-course-validation.json')
    old = read_json(ROOT / 'docs/evidence/M3/one-click-real.json')
    decision = read_json(ROOT / 'docs/evidence/M4/ai-alternative-decision.json')
    assert decision['basic_json_options_compatible']
    result = read_json(OUT) if OUT.exists() else {'created_at': stamp(), 'source_project_id': base['source_project_id'],
        'source_digest_before': base['source_digest_before'], 'scope': 'New three uploads, two-page functional AI chain; not formal ten-page/three-minute acceptance',
        'ai_model': 'glm-4.1v-thinking-flash', 'teacher_confirmation_submitted': False, 'metrics_frozen': False, 'paths': {}}
    with httpx.Client(base_url='http://127.0.0.1:8765', timeout=180, trust_env=False) as client:
        client.post('/api/session', json={'token': store.token}).raise_for_status()
        assert client.get('/api/settings').json()['ai']['model'] == result['ai_model']
        for mode in ['photo', 'video']:
            source = store.get(old['paths'][mode]['project_id'])
            if mode not in result['paths']:
                response = client.post('/api/projects', json={'name': '新上传AI全链路复验 · 免费视觉备选 · ' + mode,
                    'config': {'mode': mode, 'resolution': '1080p', 'layout': 'sidebar', 'target_seconds': 12}})
                response.raise_for_status()
                result['paths'][mode] = {'project_id': response.json()['id'], 'source_upload_project_id': source['id'],
                    'source_upload_project_digest_before': fingerprint(source), 'upload_jobs': [], 'scope': 'two-page functional verification only'}
                write_json(OUT, result)
            entry = result['paths'][mode]
            pid = entry['project_id']
            for role in [mode, 'pptx', 'reference_audio']:
                if store.get(pid)['assets'].get(role, {}).get('state') == 'ready':
                    continue
                path = store.file(source['id'], source['assets'][role]['original'])
                with path.open('rb') as stream:
                    response = client.post(f'/api/projects/{pid}/quick-assets/{role}', data={'revision': store.get(pid)['revision']},
                                           files={'file': (path.name, stream, 'application/octet-stream')})
                response.raise_for_status()
                entry['upload_jobs'].append({'role': role, 'source_sha256': digest(path), 'response': response.json(), 'at': stamp()})
                write_json(OUT, result)
                deadline = time.monotonic() + 180
                while store.busy(pid) and time.monotonic() < deadline:
                    time.sleep(.5)
                assert not store.busy(pid) and store.get(pid)['assets'][role]['state'] == 'ready'
            entry['versions_before_generate'] = sum(bool(s['versions']) for s in store.get(pid)['scenes'])
            assert entry['versions_before_generate'] == 0
            write_json(OUT, result)
        # Finish all uploads before queuing GPU work, preserving the sole worker.
        for mode, entry in result['paths'].items():
            if entry.get('course_job_id'):
                continue
            response = client.post(f"/api/projects/{entry['project_id']}/generate")
            response.raise_for_status()
            entry.update(course_job_id=response.json()['id'], submitted_at=stamp(), status=response.json())
            write_json(OUT, result)
            print({'mode': mode, 'project_id': entry['project_id'], 'state': response.json()['state']}, flush=True)


if __name__ == '__main__':
    main()
