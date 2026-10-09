"""Read-only final integrity audit; retain all earlier phase evidence."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import httpx
from mooc_m1.core import digest, read_json, stamp, write_json
from mooc_m2.content import fingerprint
from mooc_m2.store import Store


def main():
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'docs/evidence/M3'
    output = evidence / 'one-click-final-check.json'
    write_json(output, {'state': 'checking'})
    errors = []
    files = [root / 'AGENTS.md', root / 'README.md']
    files += list((root / 'specs').glob('*.md')) + list((root / 'docs').rglob('*.md'))
    files += list((root / '.agents/skills').glob('*/SKILL.md'))
    links = 0
    for file in files:
        text = file.read_text(encoding='utf-8-sig')
        if '\ufffd' in text:
            errors.append(f'Invalid text: {file.relative_to(root)}')
        for match in re.finditer(r'\[[^\]\n]*\]\(([^\)]+)\)', text):
            target = match.group(1).strip().strip('<>')
            if target.startswith(('http:', 'https:', '#', 'mailto:', 'codex:')):
                continue
            links += 1
            if not (file.parent / unquote(target.split('#')[0])).exists():
                errors.append(f'Missing link: {file.relative_to(root)} -> {target}')
    state = (root / 'docs/PROJECT_STATUS.md').read_text(encoding='utf-8')
    ids = re.findall(r'^\| (M[1-4]-F\d\d) \|', state, re.M)
    assert len(ids) == 24 and set(ids) == {f'M{i}-F{j:02d}' for i in range(1, 5) for j in range(1, 7)}
    tracking = (root / 'specs/TRACEABILITY.md').read_text(encoding='utf-8')
    for prefix, count in [('FR', 20), ('NFR', 8), ('AC', 18)]:
        assert set(re.findall(r'^\| ('+prefix+r'\d\d)\b', tracking, re.M)) == {f'{prefix}{i:02d}' for i in range(1, count+1)}
    for spec in (root / 'specs').glob('M*-*.spec.md'):
        assert '- [x]' not in spec.read_text(encoding='utf-8').lower()
    test_results = {}
    for name in ['one-click-final-tests.xml', 'one-click-coordinator-final.xml']:
        suite = ET.parse(evidence / name).getroot().find('testsuite')
        assert int(suite.attrib['failures']) == int(suite.attrib['errors']) == 0
        test_results[name] = {k: suite.attrib[k] for k in ['tests', 'failures', 'errors', 'time']}
    store = Store(root / 'storage/m2')
    real = read_json(evidence / 'one-click-real.json')
    source = store.get(real['source_project_id'])
    assert fingerprint(source) == real['source_digest_before']
    assert sum(bool(s['confirmed']) for s in source['scenes']) == 0
    assert not source.get('snapshot')
    browser = read_json(evidence / 'one-click-browser.json')
    assert browser['teacher_confirmation_submitted'] is False
    media = {}
    for mode in ['saved_photo', 'saved_video']:
        entry = real['paths'][mode]
        result = entry['status']['media']['result']
        assert entry['status']['state'] == 'completed' and result['preview'] and not result['quality_verified']
        assert result['width'] == 1920 and result['height'] == 1080
        assert result['video_start_seconds'] == 0 and result['audio_check']['silence_ratio'] == 0
        assert entry['four_exports_verified']
        scenes = entry['real_scenes']
        assert len(scenes) == 2 and len({s['portrait']['sha256'] for s in scenes}) == 2
        for scene in scenes:
            assert set(scene['stage_states'].values()) == {'valid'}
            assert scene['portrait']['audio_sha256'] == scene['tts']['sha256']
            assert scene['tts']['provider'] == 'GPT-SoVITS'
            assert scene['portrait']['provider'] == ('SadTalker' if mode.endswith('photo') else 'MuseTalk')
        downloaded = Path(browser['media'][mode]['download'])
        assert digest(downloaded) == result['sha256']
        assert digest(store.file(entry['project_id'], result['path'])) == result['sha256']
        media[mode] = {'project_id': entry['project_id'], 'sha256': result['sha256'],
                       'duration_seconds': result['duration_seconds'], 'download_sha256_verified': True,
                       'media_generation': entry['media_generation'], 'attempts': entry['media_attempts']}
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False) as client:
        response = client.get('/')
        assert response.status_code == 200 and 'index-CiNvWKcN.js' in response.text
        assert response.headers['cache-control'] == 'no-store'
    implementation = ['frontend/src/OneClick.vue', 'frontend/src/App.vue', 'frontend/src/style.css',
                      'frontend/src/main.js', 'frontend/dist/index.html', 'mooc_m2/course.py',
                      'mooc_m2/service.py', 'mooc_m2/api.py', 'mooc_m3/pipeline.py', 'mooc_m3/render.py',
                      'tools/course_reference_asr.py', 'tests/test_one_click.py']
    report = {'checked_at': stamp(), 'scope': 'one-click engineering and short real draft media; not formal acceptance',
              'tests': test_results, 'documents': len(files), 'local_links_checked': links, 'errors': errors,
              'traceability': {'work_items':24, 'FR':20, 'NFR':8, 'AC':18}, 'source_unchanged': True,
              'source_teacher_confirmation_count': 0, 'formal_snapshot_count': len(source.get('snapshots', [])),
              'source_documents': {str(p.relative_to(root)): digest(p) for p in root.glob('*.docx')},
              'browser_evidence': 'one-click-browser.json', 'media': media,
              'fresh_upload_auto_ai_complete': False, 'fresh_upload_blocker': 'AI_RATE_LIMITED / HTTP429',
              'html_no_store_verified': True, 'implementation_sha256': {p: digest(root / p) for p in implementation}}
    write_json(output, report)
    print({'tests':test_results, 'documents':len(files), 'links':links, 'errors':errors,
           'source_unchanged':True, 'real_drafts_verified':list(media), 'fresh_auto_ai_complete':False})
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
