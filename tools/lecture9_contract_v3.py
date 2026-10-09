"""Inspect the bounded real course, preserve previous records, verify real exports."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import httpx
from mooc_m1.core import stamp, write_json, read_json, digest
from mooc_m2.content import current

ROOT = Path(__file__).resolve().parents[1]
PID = '11604689-6106-451f-b40b-95089e07b5b5'
OUT = ROOT / 'docs/evidence/M2/lecture9-contract-v3-latest.json'


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    root = ROOT / 'storage/m2'
    with sqlite3.connect(root / 'content.sqlite3') as db:
        p = json.loads(db.execute('SELECT data FROM projects WHERE id=?', (PID,)).fetchone()[0])
        jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE project_id=? ORDER BY rowid DESC', (PID,))]
    before = read_json(ROOT / 'docs/evidence/M2/lecture9-contract-v3-before.json')
    assert all(sha(next(j for j in jobs if j['id'] == jid)) == old for jid, old in before['old_jobs'].items())
    # Human editing may append versions while this long real run is observed.
    # Preserve and compare the exact original history prefix, not a mutable list.
    with sqlite3.connect(ROOT / 'storage/m4-review/lecture9-before-v3.sqlite3') as db:
        original_project = json.loads(db.execute('SELECT data FROM projects WHERE id=?', (PID,)).fetchone()[0])
    additions = []
    for sid, old in before['old_versions'].items():
        original = next(s for s in original_project['scenes'] if s['id'] == sid)['versions']
        present = next(s for s in p['scenes'] if s['id'] == sid)['versions']
        assert sha(original) == old == sha(present[:len(original)])
        if len(present) > len(original):
            additions.append({'scene_id': sid, 'appended_versions': present[len(original):]})
    assert sha(p['assets']) == before['assets_sha256']
    physical_assets = {}
    for role, asset in p['assets'].items():
        if not asset:
            continue
        folder = root / 'projects' / PID
        assert digest(folder / asset['original']) == asset['sha256']
        if asset.get('selected'):
            assert digest(folder / asset['selected']) == asset.get('selected_sha256', asset['sha256'])
        physical_assets[role] = {'original_sha256_verified': True, 'selected_sha256_verified': bool(asset.get('selected'))}
    j = next(j for j in jobs if j['kind'] == 'course')
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=60) as c:
        c.post('/api/session', json={'token': (root / '.session-token').read_text().strip()}).raise_for_status()
        response = c.get(f'/api/projects/{PID}/generation'); response.raise_for_status()
        state = response.json()
        page11 = next(s for s in p['scenes'] if s['id'] == 'd02c3e35-c42f-4541-b4d7-0955788242e9')
        result = {'checked_at': stamp(), 'state': state, 'saved_scripts': sum(bool(current(s)) for s in p['scenes']),
            'old_jobs_unchanged': True, 'old_ten_original_script_histories_preserved': True, 'appended_original_page_versions': additions, 'assets_unchanged': True,
            'teacher_confirmations': sum(bool(s['confirmed']) for s in p['scenes']),
            'ai_attempts': j.get('ai_attempts', []), 'failed_generations': j.get('attempts', []),
            'page11_version': current(page11), 'metrics_frozen': False, 'scope': '24-page actual user photo course; unreviewed draft'}
        result['physical_assets'] = physical_assets
        prior_media_path = ROOT / 'docs/evidence/M3/lecture9-media-before-short-repair.json'
        if prior_media_path.is_file():
            prior = read_json(prior_media_path)
            assert next(x for x in jobs if x['id'] == prior['id']) == prior
            for kind, file_path in prior['result']['exports'].items():
                assert digest(root / 'projects' / PID / file_path) == prior['result']['file_hashes'][kind]
            result['initial_complete_media_preserved'] = {'job_id': prior['id'], 'all_four_exports_sha256_verified': True}
        result['course_history'] = [{k: x.get(k) for k in ('id', 'state', 'generation', 'created_at', 'finished_at', 'draft_recipe', 'error', 'attempts', 'ai_attempts', 'result')}
                                   for x in jobs if x['kind'] == 'course']
        result['page24_version'] = current(p['scenes'][23])
        if j.get('result'):
            media = next(x for x in jobs if x['id'] == j['result']['media_job_id'])
            result['media_checkpoints'] = {'job_id': media['id'], 'state': media['state'], 'stage': media['stage'],
                'generation': media['generation'], 'started_at': media.get('started_at'), 'finished_at': media.get('finished_at'),
                'elapsed_seconds': media.get('elapsed_seconds'), 'error': media.get('error'),
                'exports': media.get('result'),
                'history': media.get('attempts', []), 'recoveries': media.get('recoveries'),
                'scenes': [{'source_index': s['source_index'], 'scene_id': s['id'], 'state': s['state'],
                    'stage_states': s['stage_states'], 'error': s.get('error'),
                    'cache_hits': s.get('cache_hits'),
                    'tts': {k: s['tts'].get(k) for k in ('sha256', 'duration_seconds', 'provider', 'request_id', 'elapsed_seconds', 'code_revision', 'weight_version', 'native_model')} if s.get('tts') else None,
                    'portrait': {k: s['portrait'].get(k) for k in ('sha256', 'audio_sha256', 'duration_seconds', 'provider', 'request_id', 'elapsed_seconds', 'native_driving', 'native_model', 'native_loads', 'code_revision', 'weight_version')} if s.get('portrait') else None,
                    'compose': s.get('compose'), 'captions': (s.get('tts') or {}).get('captions'),
                    'script_version': s['version']['id']} for s in media['scenes']]}
        if 'verify' in sys.argv and state['state'] == 'completed':
            from mooc_m2.service import Service
            svc = Service(read_json(ROOT / 'config/m2.local.json'))
            media = svc.m3.get(PID, state['media']['id']); r = media['result']
            folder = root / 'projects' / PID
            video = folder / r['path']
            md = svc.media.inspect(video, 'video')
            result['real_media_check'] = {'metadata': md, 'full_video_decode': True,
                'audio': svc.media.inspect(video, 'audio'), 'downloads': {}}
            for kind in r['exports']:
                res = c.get(f"/api/projects/{PID}/media-jobs/{media['id']}/exports/{kind}");res.raise_for_status()
                got = hashlib.sha256(res.content).hexdigest()
                assert got == r['file_hashes'][kind] == digest(folder / r['exports'][kind])
                result['real_media_check']['downloads'][kind] = {'status': res.status_code, 'bytes': len(res.content), 'sha256': got}
            assert all(s['state'] == 'valid' and s['portrait']['audio_sha256'] == s['tts']['sha256'] for s in media['scenes'])
            result['real_media_check']['all_scenes_valid_current_audio_driven'] = True
            result['real_media_check']['preview'] = r['preview']
            from mooc_m3.timeline import course_timeline, srt
            pages, cues, duration = course_timeline(media['scenes'])
            assert (folder / r['exports']['srt']).read_text(encoding='utf-8') == srt(cues)
            manifest = read_json(folder / r['exports']['manifest'])
            assert manifest['timeline'] == pages == r['timeline']
            assert [s['version']['id'] for s in manifest['scenes']] == [s['version']['id'] for s in media['scenes']]
            assert [current(s)['id'] for s in p['scenes'] if not s['skipped']] == [s['version']['id'] for s in media['scenes']]
            assert manifest['project_revision'] == media['payload']['snapshot']['revision']
            assert abs(duration - md['duration_seconds']) < .05
            result['real_media_check']['same_version_manifest_and_measured_subtitles'] = True
            result['real_media_check']['caption_intervals'] = len(cues)
        write_json(OUT, result)
    print(json.dumps({'state': state['state'], 'stage': state['stage'], 'scripts': result['saved_scripts'],
        'generation': state['generation'], 'error': state['error'], 'media_progress': (state.get('media') or {}).get('progress'),
        'page11_saved': bool(current(page11)), 'preservation_passed': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
