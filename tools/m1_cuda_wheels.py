"""Parallel ranged download of official Windows CUDA wheels, SHA-256 verified."""
import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote
import requests

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('target', choices=['gpt', 'sad', 'muse'])
args = p.parse_args()
versions = {'gpt': ('cu118', ['torch-2.5.1+cu118', 'torchvision-0.20.1+cu118', 'torchaudio-2.5.1+cu118']),
            'sad': ('cu113', ['torch-1.12.1+cu113', 'torchvision-0.13.1+cu113', 'torchaudio-0.12.1+cu113']),
            'muse': ('cu118', ['torch-2.0.1+cu118', 'torchvision-0.15.2+cu118', 'torchaudio-2.0.2+cu118'])}

def session():
    s = requests.Session()
    s.trust_env = False
    return s

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(4*1024*1024), b''):
            h.update(data)
    return h.hexdigest()

records = []
for package in versions[args.target][1]:
    channel = versions[args.target][0]
    name = package.split('-')[0]
    index = f'https://download.pytorch.org/whl/{channel}/{name}/'
    r = session().get(index, timeout=45)
    r.raise_for_status()
    filename = package + '-cp310-cp310-win_amd64.whl'
    links = re.findall(r'href="([^"]+)"', r.text)
    link = next(x for x in links if filename in unquote(x))
    url, fragment = link.split('#')
    expected = fragment.split('sha256=')[1]
    target = Path.home() / '.cache/mooc-m1-wheels/downloaded' / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or sha(target) != expected:
        response = session().get(url, headers={'Range': 'bytes=0-0'}, stream=True, timeout=40)
        if response.status_code != 206:
            raise RuntimeError('Server does not support bounded ranged downloads')
        size = int(response.headers['Content-Range'].split('/')[-1])
        response.close()
        parts = target.with_name(target.name + '.parts')
        parts.mkdir(exist_ok=True)
        chunk_size = 32*1024*1024
        count = (size+chunk_size-1)//chunk_size
        print('wheel', filename, size, 'chunks', count, flush=True)
        def fetch(i):
            start, end = i*chunk_size, min((i+1)*chunk_size,size)-1
            part = parts / f'{i:04d}'
            if part.exists() and part.stat().st_size == end-start+1:
                return part
            for attempt in range(3):
                try:
                    with session().get(url, headers={'Range': f'bytes={start}-{end}'}, stream=True, timeout=(30,45)) as r:
                        if r.status_code != 206 or r.headers['Content-Range'] != f'bytes {start}-{end}/{size}':
                            raise RuntimeError('Invalid range response')
                        with part.open('wb') as f:
                            for data in r.iter_content(1024*1024):
                                f.write(data)
                    if part.stat().st_size != end-start+1:
                        raise RuntimeError('Truncated wheel range')
                    print(filename, 'chunk', i+1, '/', count, flush=True)
                    return part
                except Exception as exc:
                    print('range failed', i, type(exc).__name__, attempt+1, flush=True)
                    if attempt == 2:
                        raise
        with ThreadPoolExecutor(max_workers=8) as pool:
            files = list(pool.map(fetch, range(count)))
        temp = target.with_name(target.name + '.partial')
        with temp.open('wb') as f:
            for part in files:
                with part.open('rb') as src:
                    for data in iter(lambda: src.read(4*1024*1024), b''):
                        f.write(data)
        if sha(temp) != expected:
            raise RuntimeError('Official CUDA wheel checksum mismatch')
        temp.replace(target)
        # Only remove the exact chunk files used after the full official hash passes.
        for part in files:
            if not part.resolve().is_relative_to(parts.resolve()):
                raise RuntimeError('Chunk cleanup outside owned directory')
            part.unlink()
        parts.rmdir()
    print('verified', filename, flush=True)
    records.append({'path': str(target), 'source': url, 'index': index, 'sha256': expected, 'bytes': target.stat().st_size})
    (ROOT / f'docs/evidence/M1/{args.target}-cuda-wheels.json').write_text(json.dumps({'wheels':records},indent=2),encoding='utf-8')
