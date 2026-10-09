"""Read-only runtime checks and consolidation of actual browser evidence."""
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.store import Store
from mooc_m2.content import fingerprint

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/M4'


def main():
    fresh = read_json(ROOT / 'docs/evidence/M3/fresh-ai-validation.json')
    browser = read_json(EVIDENCE / 'browser-fresh-ai.json')
    for mode, entry in fresh['paths'].items():
        observed = browser['paths'][mode]
        assert entry['status']['state'] == 'completed'
        assert entry['versions_before_generate'] == 0
        assert observed['project_id'] == entry['project_id']
        assert observed['played_from_zero_to_ended']
        assert observed['refresh_restored_completed_result']
        assert not observed['teacher_checkbox_checked'] and not observed['confirm_enabled']
        downloaded_hash = digest(observed['download'])
        assert downloaded_hash == entry['exports']['mp4']['sha256']
        observed['download_sha256'] = downloaded_hash
        observed['download_sha256_verified'] = True
    browser['checked_at'] = stamp()
    write_json(EVIDENCE / 'browser-fresh-ai.json', browser)

    decision = read_json(EVIDENCE / 'ai-alternative-decision.json')
    decision.setdefault('course_schema_initial_observations', decision['course_schema_compatible'])
    decision['course_schema_compatible'] = {
        'photo': 'Two complete new-upload AI drafts validated; first incomplete reading body rejected, generation 2 completed; one page recovered pairs only from complete equal sentence boundaries',
        'video': 'Two actual new-upload AI drafts validated and native original video sequence media completed, generation 1'}
    decision['full_chain_completed'] = True
    decision['functional_chain_checked_at'] = stamp()
    decision['functional_chain_scope'] = 'Both two-page new-upload chains; not formal ten-page/three-minute acceptance or human quality'
    decision['functional_chain_projects'] = {mode: entry['project_id'] for mode, entry in fresh['paths'].items()}
    decision['teacher_quality_verified'] = False
    decision['format_note'] = 'Valid JSON probe; punctuation exact check remains false. Subsequent full two-page course schema and actual media/browser checks completed for both modes; human quality remains unverified.'
    write_json(EVIDENCE / 'ai-alternative-decision.json', decision)

    repairs = read_json(EVIDENCE / 'validation-tool-repairs.json')
    repairs['repairs'][1]['recheck'] = 'Both ten-page native requests and both two-page AI native requests verified; video feature-driving required, photo feature measurement null'
    if not any(r['tool'] == 'inline_browser_download_hash_check' for r in repairs['repairs']):
        repairs['repairs'].append({'tool': 'inline_browser_download_hash_check', 'first_error': 'UnicodeDecodeError from Windows default GBK',
            'reason': 'Evidence JSON was read without explicit UTF-8', 'repair': 'Use explicit UTF-8 for JSON evidence',
            'recheck': 'Three actual video advanced downloads matched saved export hashes; no media task submitted'})
    write_json(EVIDENCE / 'validation-tool-repairs.json', repairs)

    store = Store(ROOT / 'storage/m2')
    old = read_json(ROOT / 'docs/evidence/M3/long-course-validation.json')
    assert fingerprint(store.get(old['source_project_id'])) == old['source_digest_before']
    with store.connection() as db:
        active = db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=15) as client:
        health = client.get('/api/health')
        health.raise_for_status()
        assert health.json()['application'] == 'mooc-workbench' and health.json()['worker_alive']
        root = client.get('/')
        assert root.status_code == 200 and 'id="app"' in root.text
    assert active == 0
    result = {'checked_at': stamp(), 'scope': 'M4 preacceptance closeout, not formal acceptance',
        'health': health.json(), 'root_http_status': root.status_code, 'active_jobs': active,
        'original_project_unchanged': True, 'browser_fresh_downloads_verified': True,
        'teacher_confirmation_submitted': False, 'formal_passed': False, 'metrics_frozen': False,
        'browser_long_evidence_sha256': digest(EVIDENCE / 'browser-long-courses.json'),
        'browser_fresh_evidence_sha256': digest(EVIDENCE / 'browser-fresh-ai.json'),
        'result_screenshot': str(EVIDENCE / 'browser-final-result.png'),
        'result_screenshot_sha256': digest(EVIDENCE / 'browser-final-result.png')}
    write_json(EVIDENCE / 'closeout-check.json', result)
    print('Healthy local workbench; no active jobs; original project unchanged; browser downloads verified')


if __name__ == '__main__':
    main()
