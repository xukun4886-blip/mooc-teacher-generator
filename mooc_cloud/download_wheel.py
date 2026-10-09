"""Resume a pinned large wheel using bounded ranges; verify official SHA256.

No model/media generation. Used only to prepare the independent cloud runtime.
"""
import argparse
import concurrent.futures
import hashlib
import os
import re
import time
import threading
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--url', required=True)
parser.add_argument('--sha256', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--bytes', type=int, required=True)
parser.add_argument('--workers', type=int, default=16)
args = parser.parse_args()
if not args.url.startswith('https://') or not re.fullmatch('[0-9a-f]{64}', args.sha256) or not 1 <= args.workers <= 32:
    parser.error('HTTPS URL, SHA256 and 1–32 workers required')
output = Path(args.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
pieces = output.with_suffix('.pieces')
pieces.mkdir(exist_ok=True)
size = 4 * 1024**2
deadline = time.monotonic() + 900
stop = threading.Event()
def fetch(index):
    start, end = index * size, min((index+1)*size, args.bytes)-1
    piece = pieces / str(index)
    if piece.is_file() and piece.stat().st_size == end-start+1:
        return
    for attempt in range(3):
        if stop.is_set() or time.monotonic() > deadline:
            raise TimeoutError('wheel download timed out')
        try:
            request = urllib.request.Request(args.url, headers={'Range':f'bytes={start}-{end}'})
            with urllib.request.urlopen(request, timeout=90) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{args.bytes}':
                    raise ValueError('server did not honor exact range')
                data = response.read(end-start+2)
                if len(data) != end-start+1:
                    raise ValueError('partial range')
            temp = piece.with_suffix('.part')
            temp.write_bytes(data); temp.replace(piece)
            return
        except Exception:
            if attempt == 2:
                stop.set()
                raise
            time.sleep(1)
count = (args.bytes+size-1)//size
started = time.monotonic()
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
    for completed, _ in enumerate(pool.map(fetch, range(count)), 1):
        if completed % 20 == 0:
            print(f'{completed}/{count} ranges; {time.monotonic()-started:.1f}s', flush=True)
temp = output.with_suffix('.part')
sha = hashlib.sha256()
with temp.open('wb') as target:
    for index in range(count):
        data = (pieces / str(index)).read_bytes(); sha.update(data); target.write(data)
if sha.hexdigest() != args.sha256 or temp.stat().st_size != args.bytes:
    raise ValueError('official wheel SHA256 verification failed; file remains unpublished')
temp.replace(output)
print(f'Verified {output.name}: {args.bytes} bytes, {time.monotonic()-started:.1f}s', flush=True)
