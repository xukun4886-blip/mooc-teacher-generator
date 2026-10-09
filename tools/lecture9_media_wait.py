"""Bounded read-only live observation of this real media job (no retries)."""
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

root = Path(__file__).resolve().parents[1] / 'storage/m2'
job_id = sys.argv[1] if len(sys.argv) > 1 else '89055bfa-566c-4e86-b4e9-969073b1a9ae'
deadline = time.monotonic() + 21600
while time.monotonic() < deadline:
    with sqlite3.connect(root / 'content.sqlite3') as db:
        j = json.loads(db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()[0])
    active = next((s for s in j['scenes'] if s['state'] == 'running'), None)
    record = {'state': j['state'], 'stage': j['stage'], 'generation': j['generation'],
        'valid_pages': sum(s['state'] == 'valid' for s in j['scenes']), 'error': j.get('error')}
    if active:
        record.update(active_page=active['source_index'], speech_seconds=(active.get('tts') or {}).get('duration_seconds'))
        logs = sorted((root / 'projects' / j['project_id'] / 'm3/native/requests').glob('*/native.log'), key=lambda f: f.stat().st_mtime)
        if logs:
            frames = re.findall(r'Face Renderer::[^\r\n]*', logs[-1].read_text(encoding='utf-8', errors='replace'))
            if frames:
                record['actual_renderer_log'] = frames[-1]
    print(json.dumps(record, ensure_ascii=False), flush=True)
    if j['state'] in {'completed', 'failed', 'canceled'}:
        break
    time.sleep(50)
