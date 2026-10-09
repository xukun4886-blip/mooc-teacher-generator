"""Record an actual browser PPT replacement without generating or confirming."""
import sys
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.content import fingerprint, effective
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/M4/ppt-reselect-real.json'


def main():
    store = Store(ROOT / 'storage/m2')
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=30) as client:
        health = client.get('/api/health').json()
        assert health['application'] == 'mooc-workbench' and health['worker_alive']
        client.post('/api/session', json={'token': store.token}).raise_for_status()
        if sys.argv[1] == 'prepare':
            source_id = read_json(ROOT / 'docs/evidence/M3/fresh-ai-validation.json')['paths']['video']['project_id']
            source = store.get(source_id)
            record = {'prepared_at': stamp(), 'source_project_id': source_id,
                'source_fingerprint_before': fingerprint(source), 'source_page_count': len(source['slides']),
                'input_ppt_path': str(ROOT / 'storage/m4-validation/lecture2-pages5-14.pptx'),
                'input_ppt_sha256': digest(ROOT / 'storage/m4-validation/lecture2-pages5-14.pptx'),
                'source_generation': client.get(f'/api/projects/{source_id}/generation').json(),
                'scope': 'Actual browser reselect and original-page rendering; no new AI/media generation or teacher confirmation'}
            if not OUT.exists():
                write_json(OUT, record)
            ticket = client.post('/api/session/launch-ticket').json()['ticket']
            print(f'http://127.0.0.1:8765/?project={source_id}#launch={ticket}')
            return
        record = read_json(OUT)
        browser = read_json(ROOT / 'docs/evidence/M4/ppt-reselect-browser.json')
        new = store.get(browser['new_project_id'])
        source = store.get(record['source_project_id'])
        assert fingerprint(source) == record['source_fingerprint_before']
        assert new['source_project_id'] == source['id'] and new['id'] != source['id']
        assert new['assets']['pptx']['state'] == 'ready' and len(new['slides']) == 10
        assert all(not s['versions'] and not s['confirmed'] for s in new['scenes'])
        mode = effective(source, {'overrides': {}})['mode']
        for role in [mode, 'reference_audio']:
            old, asset = source['assets'][role], new['assets'][role]
            assert asset['state'] == 'ready' and asset['teacher_id'] == old['teacher_id']
            assert asset['selection'] == old['selection']
            for field in ['original', 'selected']:
                assert digest(store.file(new['id'], asset[field])) == digest(store.file(source['id'], old[field]))
        assert client.get(f"/api/projects/{new['id']}/generation").json() is None
        old_generation = record['source_generation']
        result = client.get(f"/api/projects/{source['id']}/media-jobs/{old_generation['media']['id']}/exports/mp4")
        result.raise_for_status()
        assert __import__('hashlib').sha256(result.content).hexdigest() == old_generation['media']['result']['sha256']
        record.update(checked_at=stamp(), state='passed', new_project_id=new['id'], source_unchanged=True,
            new_page_count=len(new['slides']), new_script_versions=0, inherited_inputs_owned=True, selected_person_mode=mode,
            old_mp4_download_sha256_verified=True, old_teacher_confirmation_unchanged=True,
            browser=browser, new_jobs=[{'id':j['id'], 'kind':j['kind'], 'state':j['state']} for j in store.jobs(new['id'])],
            code_sha256={str(p.relative_to(ROOT)):digest(p) for p in [ROOT/'mooc_m2/store.py', ROOT/'mooc_m2/service.py', ROOT/'mooc_m2/api.py', ROOT/'frontend/src/OneClick.vue']})
        write_json(OUT, record)
        print('Actual 2-page to 10-page browser replacement passed; old course/export unchanged; no generation or confirmation added')


if __name__ == '__main__':
    main()
