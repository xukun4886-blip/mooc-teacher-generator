"""Preserve the user's first failures, then inspect a real bounded repair run."""
import json
import sys
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.store import Store
from mooc_m2.content import current, fingerprint

ROOT = Path(__file__).resolve().parents[1]
PID = '11604689-6106-451f-b40b-95089e07b5b5'
FIRST = '0eaf6185-d796-4be2-95a7-8a3218c75fb6'
OUT = ROOT / 'docs/evidence/M2/lecture9-format-first.json'


def main():
    store = Store(ROOT / 'storage/m2')
    p = store.get(PID)
    jobs = store.jobs(PID)
    first = next(j for j in jobs if j['id'] == FIRST)
    if sys.argv[1] == 'prepare':
        if OUT.exists():
            raise RuntimeError('First failure evidence already exists')
        attempts = []
        for a in first.get('ai_attempts', []):
            entry = dict(a)
            record = a.get('provider_record') or (first.get('provider_record') if a == first['ai_attempts'][-1] else None)
            if record:
                body = read_json(store.file(PID, record['path']))
                choice = body['choices'][0]
                try:
                    obj = json.loads(choice['message']['content'], strict=False)
                    entry.update(output_type=type(obj).__name__, output_items=len(obj) if isinstance(obj, list) else None)
                except ValueError:
                    entry['output_type'] = 'invalid-json'
                entry.update(finish_reason=choice.get('finish_reason'), usage=body.get('usage'),
                             response_sha256=digest(store.file(PID, record['path'])))
            attempts.append(entry)
        write_json(OUT, {'recorded_at': stamp(), 'project_id': PID, 'course_name': p['name'],
            'original_job_id': FIRST, 'original_job_sha256': fingerprint(first), 'page_count': len(p['slides']),
            'state': first['state'], 'generation': first['generation'], 'error': first['error'],
            'scripts_ready': sum(bool(current(s)) for s in p['scenes']), 'ai_attempts': attempts,
            'preserved_versions': {s['id']: fingerprint(s['versions']) for s in p['scenes'] if s['versions']},
            'input_hashes': {role: {k: a.get(k) for k in ['sha256', 'selected_sha256', 'state']} for role, a in p['assets'].items()},
            'teacher_confirmations': sum(bool(s['confirmed']) for s in p['scenes']),
            'scope': 'Original user course failure, no teacher or model self-rating; full responses remain protected'})
        config_path = ROOT / 'config/m2.local.json'
        cfg = read_json(config_path)
        backup = ROOT / 'storage/m4-review/lecture9-config-before-format-fix.json'
        if backup.exists():
            raise RuntimeError('Config backup exists')
        write_json(backup, cfg)
        assert cfg['ai']['allow_paid'] is False and cfg['ai']['model'] == 'glm-4.1v-thinking-flash'
        cfg['ai']['request_options']['max_tokens'] = 8000
        write_json(config_path, cfg)
        print({'first_failure_preserved': True, 'ready_scripts': 2, 'free_model_output_budget': 8000})
        return
    evidence = read_json(OUT)
    assert fingerprint(first) == evidence['original_job_sha256']
    import sqlite3
    with sqlite3.connect(ROOT / 'storage/m4-review/lecture9-before-v3.sqlite3') as db:
        original = json.loads(db.execute('SELECT data FROM projects WHERE id=?', (PID,)).fetchone()[0])
    for sid, old in evidence['preserved_versions'].items():
        history = next(s for s in original['scenes'] if s['id'] == sid)['versions']
        present = next(s for s in p['scenes'] if s['id'] == sid)['versions']
        assert fingerprint(history) == old == fingerprint(present[:len(history)])
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=30) as client:
        client.post('/api/session', json={'token': store.token}).raise_for_status()
        if sys.argv[1] == 'ticket':
            ticket = client.post('/api/session/launch-ticket').json()['ticket']
            print(f'http://127.0.0.1:8765/?project={PID}#launch={ticket}')
            return
        latest = client.get(f'/api/projects/{PID}/generation').json()
    result = {'checked_at': stamp(), 'project_id': PID, 'state': latest['state'], 'stage': latest['stage'],
              'scripts_ready': sum(bool(current(s)) for s in p['scenes']), 'total': len(p['scenes']),
              'latest': latest, 'first_failure_unchanged': True, 'first_two_original_version_histories_preserved': True,
              'teacher_confirmations': sum(bool(s['confirmed']) for s in p['scenes'])}
    newest = next(j for j in jobs if j['kind'] == 'course')
    result['ai_attempts'] = newest.get('ai_attempts', [])
    result['new_job_id'] = newest['id']
    result['source_versions'] = [{
        'source_page_ids': s['source_page_ids'], 'version_id': current(s)['id'],
        'display_sha256': fingerprint(current(s)['display_text']),
        'reading_sha256': fingerprint(current(s)['reading_text']),
        'provenance': current(s)['provenance'], 'teacher_review': bool(current(s)['teacher_review'])
    } for s in p['scenes'] if current(s)]
    target = ROOT / 'docs/evidence/M2/lecture9-format-latest.json'
    write_json(target, result)
    print({k: result[k] for k in ['state', 'stage', 'scripts_ready', 'total', 'first_failure_unchanged']})


if __name__ == '__main__':
    main()
