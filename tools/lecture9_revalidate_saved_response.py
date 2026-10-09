"""One-off strict recovery of a real saved response after the whitespace fix.

No HTTP model call, no failed-job rewrite, no missing-body reconstruction.
The original hash, input, base version and current revision fence this append.
"""
import copy
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mooc_m1.core import digest, read_json, write_json, stamp
from mooc_m2.ai_draft import parse_draft, DRAFT_CONTRACT
from mooc_m2.content import add_version, current, find_scene, fingerprint
from mooc_m2.service import Service

ROOT = Path(__file__).resolve().parents[1]
PID = '11604689-6106-451f-b40b-95089e07b5b5'
SOURCE_JOB = '7b59d596-4cb1-4546-a421-72d38e1f7249'
EXPECTED_RESPONSE = '4b3b167e1b916942daab20b961012b684e27843618024432bd7c37143b0056aa'
OUT = ROOT / 'docs/evidence/M2/lecture9-saved-response-revalidation.json'
svc = Service(read_json(ROOT / 'config/m2.local.json'))
jobs = svc.store.jobs(PID)
source = next(j for j in jobs if j['id'] == SOURCE_JOB)
assert source['kind'] == 'ai' and source['state'] == 'failed'
assert svc.config['ai']['allow_paid'] is False
data = source['payload']
attempt = next(a for a in source['ai_attempts'] if a['attempt'] == 2)
assert attempt['status'] == 200 and attempt['finish_reason'] == 'stop'
provider = attempt['provider_record']
assert provider['response_sha256'] == EXPECTED_RESPONSE
path = svc.store.file(PID, provider['path'])
assert digest(path) == EXPECTED_RESPONSE
body = read_json(path)
assert body['id'] == provider['response_id']
assert body['model'] == 'glm-4.1v-thinking-flash'
p = svc.store.get(PID)
s = find_scene(p, data['scene_id'])
obj, parsed = parse_draft(body, s, course=True)
assert parsed['pairing_method'] == 'complete_text_identical_except_whitespace'
old_history = copy.deepcopy(s['versions'])
old_job_hash = fingerprint(source)
existing = next((v for v in s['versions'] if v['provenance'].get('revalidated_from_job') == SOURCE_JOB), None)
if existing:
    version = existing
    assert OUT.is_file()
else:
    assert s['current_version'] == data['base_version'] and not s['confirmed']
    assert current(s)['mode'] == 'ai'
    assert svc.ai_input(p, s)['input_key'] == data['input_key']
    record = {'at': stamp(), 'operation': 'strict_saved_provider_revalidation',
              'source_failed_job': SOURCE_JOB, 'source_attempt': 2,
              'provider_record': provider, 'contract': DRAFT_CONTRACT,
              'parsed': parsed, 'http_model_calls': 0, 'teacher_confirmation': False,
              'paid_allowed': False, 'old_version_ids': [v['id'] for v in old_history]}
    write_json(OUT, record)
    with svc.store.edit(PID, p['revision']) as project:
        with svc.store.connection() as db:
            assert db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] == 0
        scene = find_scene(project, s['id'])
        assert scene['current_version'] == data['base_version']
        assert svc.ai_input(project, scene)['input_key'] == data['input_key']
        provenance = {'model': body['model'], 'provider': urlparse(svc.config['ai']['base_url']).hostname,
                      'response_id': body['id'], 'usage': body.get('usage'),
                      'provider_record': provider, 'context_sha256': fingerprint(data['context']),
                      'source_page_ids': scene['source_page_ids'],
                      'image_sha256': [x.get('image_sha256') for x in data['source_slides']],
                      'extensions': obj['extensions'], 'draft_contract': DRAFT_CONTRACT,
                      'sentence_pairs': obj['sentence_pairs'], 'pairing_method': parsed['pairing_method'],
                      'revalidated_from_job': SOURCE_JOB, 'revalidated_from_attempt': 2,
                      'revalidation_operation': 'strict_saved_provider_revalidation',
                      'input_key': data['input_key'], 'expanded_current_source_count': parsed['expanded_current_source_count']}
        version = add_version(project, scene, 'ai', obj['display_text'], obj['reading_text'], provenance,
                              {k: obj[k] for k in ('knowledge_points', 'questions', 'terms', 'pending')})
        version['author'] = 'ai:' + body['model']
        assert version['display_text'] == obj['display_text'] and version['reading_text'] == obj['reading_text']
        assert scene['versions'][:-1] == old_history and not scene['confirmed']
    assert fingerprint(next(j for j in svc.store.jobs(PID) if j['id'] == SOURCE_JOB)) == old_job_hash
    record.update(new_version=version, old_versions_retained=True, failed_job_unchanged=True,
                  full_bodies_unchanged=True, input_compatible=True)
    write_json(OUT, record)
with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=60) as client:
    client.post('/api/session', json={'token': (svc.store.root / '.session-token').read_text().strip()}).raise_for_status()
    response = client.post(f'/api/projects/{PID}/generate')
    response.raise_for_status()
    record = read_json(OUT)
    record['course'] = response.json()
    write_json(OUT, record)
    print('Validated original full bodies; appended version:', version['id'])
    print('Normal one-click course:', record['course']['id'], response.status_code)
