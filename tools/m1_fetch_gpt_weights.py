"""Download a pinned official GPT-SoVITS v2 inference set; verify LFS hashes.

No teacher media is transmitted. This is separate from adapter preflight.
"""
import hashlib
import json
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / '.tools/models/GPT-SoVITS/GPT_SoVITS/pretrained_models'
records = []

def fetch(item):
    repo, revision, entry, target = item
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get('lfs', {}).get('sha256')
    def sha(path):
        h = hashlib.sha256()
        with path.open('rb') as f:
            for data in iter(lambda: f.read(1024*1024), b''):
                h.update(data)
        return h.hexdigest()
    if target.is_file() and target.stat().st_size == entry['size'] and (not expected or sha(target) == expected):
        print('verified existing', entry['rfilename'], flush=True)
    else:
        s = requests.Session()
        s.trust_env = False
        url = entry.get('url') or f"https://huggingface.co/{repo}/resolve/{revision}/{entry['rfilename']}"
        print('download', entry['rfilename'], entry['size'], flush=True)
        part = target.with_name(target.name + '.partial')
        for attempt in range(3):
            try:
                # Signed CDN URLs may have expired in intermediate caches.
                r = s.get(url, params={'download': 'true', 'm1': str(time.time_ns())}, stream=True, timeout=(30, 45))
                r.raise_for_status()
                size, last = 0, time.monotonic()
                with part.open('wb') as f:
                    for chunk in r.iter_content(1024*1024):
                        f.write(chunk)
                        size += len(chunk)
                        if time.monotonic() - last > 25:
                            print(entry['rfilename'], size, '/', entry['size'], flush=True)
                            last = time.monotonic()
                if size != entry['size'] or (expected and sha(part) != expected):
                    raise ValueError('Size or official LFS SHA-256 mismatch')
                part.replace(target)
                break
            except Exception as exc:
                print('download failure', entry['rfilename'], type(exc).__name__, 'attempt', attempt+1, flush=True)
                if attempt == 2:
                    return {'path': str(target), 'source': url, 'revision': revision, 'ready': False, 'error': type(exc).__name__}
    return {'path': str(target), 'source': entry.get('url') or f'https://huggingface.co/{repo}/blob/{revision}/{entry["rfilename"]}',
            'revision': revision, 'bytes': target.stat().st_size, 'sha256': sha(target), 'official_lfs_sha256': expected,
            'ready': True, 'usage_review': 'pending complete auxiliary license review'}

if __name__ == '__main__':
    plan = []

    meta = json.loads((ROOT / '.tools/lj1995-metadata.json').read_text())
    names = ['gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt', 'gsv-v2final-pretrained/s2G2333k.pth']
    for entry in meta['siblings']:
        if entry['rfilename'] in names or entry['rfilename'].startswith(('chinese-roberta-wwm-ext-large/', 'chinese-hubert-base/')):
            plan.append(('lj1995/GPT-SoVITS', meta['sha'], entry, DEST / entry['rfilename']))
    meta = json.loads((ROOT / '.tools/XXXXRT-metadata.json').read_text())
    entry = next(x for x in meta['siblings'] if x['rfilename'] == 'G2PWModel.zip')
    archive = ROOT / '.tools/G2PWModel.zip'
    plan.append(('XXXXRT/GPT-SoVITS-Pretrained', meta['sha'], entry, archive))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for record in pool.map(fetch, plan):
            records.append(record)
            (ROOT / 'docs/evidence/M1/gpt-weight-downloads.json').write_text(json.dumps({'records': records, 'generation_called': False}, indent=2), encoding='utf-8')
    if all(r['ready'] for r in records):
        dest = ROOT / '.tools/models/GPT-SoVITS/GPT_SoVITS/text'
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target = (dest / member.filename).resolve()
                if not target.is_relative_to(dest.resolve()):
                    raise ValueError('Unsafe archive member')
            z.extractall(dest)
        print('GPT v2 weights complete; license/runtime/generation still require validation', flush=True)
