"""Finish this authorized real repair only after the original immutable media is idle.

No retry loops: observe the existing run, make one bounded short-page AI job,
then submit the normal one-click course for the changed input. Preserve history.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx
from mooc_m1.core import read_json, write_json, stamp
from mooc_m2.service import Service
from mooc_m2.content import current
from mooc_m2.ai_draft import DRAFT_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
PID = '11604689-6106-451f-b40b-95089e07b5b5'
MID = '89055bfa-566c-4e86-b4e9-969073b1a9ae'
OUT = ROOT / 'docs/evidence/M2/lecture9-short-reading-real.json'
svc = Service(read_json(ROOT / 'config/m2.local.json'))
record = {'started_at': stamp(), 'original_media_job': MID, 'events': [],
          'paid_allowed': False, 'automatic_retries': 0, 'teacher_confirmation': False}
reuse_server = '--reuse-ready-server' in sys.argv
if reuse_server and OUT.exists():
    record = read_json(OUT)


def event(name, **values):
    record['events'].append({'at': stamp(), 'event': name, **values})
    write_json(OUT, record)
    print(json.dumps(record['events'][-1], ensure_ascii=False), flush=True)


def wait_terminal(jid, timeout=21600):
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        job = next(j for j in svc.store.jobs(PID) if j['id'] == jid)
        state = (job['state'], job['stage'], sum(s['state'] == 'valid' for s in job.get('scenes', [])))
        if state != previous:
            print(json.dumps({'observed_job': jid, 'state': state}, ensure_ascii=False), flush=True)
            previous = state
        if job['state'] in {'completed', 'failed', 'canceled'}:
            return job
        time.sleep(20)
    raise RuntimeError('Observation deadline; no restart or retry issued')


old = wait_terminal(MID)
preserved = ROOT / 'docs/evidence/M3/lecture9-media-before-short-repair.json'
if preserved.exists():
    assert read_json(preserved) == old
else:
    write_json(preserved, old)
event('original_media_terminal', state=old['state'], generation=old['generation'], error=old.get('error'))
if old['state'] != 'completed':
    sys.exit(2)
with svc.store.connection() as db:
    assert db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0] == 0
# Exact current server only, and only with an idle database. Hidden replacement
# keeps the same configuration, session token, port and native worker policy.
ps = """$ErrorActionPreference='Stop'
$taskListener=Get-NetTCPConnection -State Listen -LocalPort 8765
$taskProcess=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $taskListener.OwningProcess)
if($taskProcess.CommandLine -notmatch '-m mooc_m2'){throw 'Unexpected listener; preserved'}
Stop-Process -Id $taskListener.OwningProcess
Start-Process -FilePath 'D:\\XuTao_Task\\.venv-m1\\Scripts\\python.exe' -ArgumentList '-m','mooc_m2','--port','8765' -WorkingDirectory 'D:\\XuTao_Task' -WindowStyle Hidden -RedirectStandardOutput 'D:\\XuTao_Task\\storage\\lecture9-final.stdout.log' -RedirectStandardError 'D:\\XuTao_Task\\storage\\lecture9-final.stderr.log'
"""
if not reuse_server:
    # A detached server can inherit the launcher pipes after PowerShell exits.
    # Do not wait for pipe EOF from that long-running descendant.
    subprocess.run(['powershell', '-NoProfile', '-Command', ps], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=60) as client:
    for _ in range(30):
        try:
            health = client.get('/api/health')
            if health.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        raise RuntimeError('Replacement server unavailable; no AI job issued')
    client.post('/api/session', json={'token': (svc.store.root / '.session-token').read_text().strip()}).raise_for_status()
    assert health.json()['worker_alive'] is True
    assert svc.config['ai']['allow_paid'] is False
    assert svc.config['ai']['model'] == 'glm-4.1v-thinking-flash'
    event('ready_server_reused' if reuse_server else 'idle_server_restarted', health_status=health.status_code, draft_contract=DRAFT_CONTRACT)
    p = svc.store.get(PID)
    page = next(s for s in p['scenes'] if s['source_page_ids'] == [p['slides'][23]['source_page_id']])
    record['old_page24_version'] = current(page)
    old_version_ids = [v['id'] for v in page['versions']]
    batch = svc.queue_ai(PID, p['revision'], [page['id']], course_draft=True)
    aid = batch['jobs'][0]['id']
    event('single_bounded_ai_job_queued', job_id=aid, scene_id=page['id'])
    ai_job = wait_terminal(aid, 900)
    record['ai_job'] = ai_job
    event('ai_job_terminal', state=ai_job['state'], error=ai_job.get('error'))
    if ai_job['state'] != 'completed':
        sys.exit(3)
    page = next(s for s in svc.store.get(PID)['scenes'] if s['id'] == page['id'])
    assert all(vid in [v['id'] for v in page['versions']] for vid in old_version_ids)
    assert current(page)['id'] != record['old_page24_version']['id']
    record['new_page24_version'] = current(page)
    record['old_versions_retained'] = True
    response = client.post(f'/api/projects/{PID}/generate')
    response.raise_for_status()
    record['new_course'] = response.json()
    event('changed_input_one_click_submitted', course_id=record['new_course']['id'], status=response.status_code)
