"""One real generation-time restart. Only the verified 8765 workbench is stopped."""
import json
import time
import sys
import subprocess
import httpx
from pathlib import Path
from mooc_m1.core import read_json, write_json, run, stamp, digest
from mooc_m1.adapters import LocalModelAdapter
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/M4/real-generation-restart.json'


def main():
    global OUT
    if '--native' in sys.argv:
        OUT = ROOT / 'docs/evidence/M4/real-model-restart.json'
    resume = '--resume' in sys.argv
    if OUT.exists() and not resume:
        raise RuntimeError('Restart evidence exists; do not inject repeated interruptions')
    store = Store(ROOT / 'storage/m2')
    pid = read_json(ROOT / 'docs/evidence/M3/external-long-courses.json')['paths']['photo']['project_id']
    jobs = [j for j in store.jobs(pid) if j['kind'] == 'm3']
    before = jobs[0]
    valid = [s for s in before['scenes'] if s['state'] == 'valid']
    assert valid
    if resume:
        record = read_json(OUT)
        process = record['processes']
        record['first_startup_failure'] = {'code': 'TIMEOUT', 'reason': 'Background service inherited short-command Job Object; retained first interruption'}
    else:
        assert before['state'] == 'running'
        if '--native' in sys.argv:
            assert before['stage'] == 'photo_native_generation' and before['recoveries'] < 3
        live = run(['powershell.exe', '-NoProfile', '-Command',
        "$listener=Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 8765; $p=Get-CimInstance Win32_Process -Filter \"ProcessId = $($listener.OwningProcess)\"; if($p.CommandLine -notlike '*-m mooc_m2*'){throw 'Unexpected owner'}; $all=Get-CimInstance Win32_Process; $parents=@($p.ProcessId); $owned=@(); do { $children=@($all | Where-Object { $_.ParentProcessId -in $parents }); $owned+= $children; $parents=@($children.ProcessId) } while($children.Count -gt 0); @{server_pid=$p.ProcessId; child_pids=@($owned | ForEach-Object ProcessId); native_model_pids=@($owned | Where-Object {$_.CommandLine -like '*mooc_m1.model_worker*'} | ForEach-Object ProcessId)} | ConvertTo-Json -Compress"], 15)
        process = json.loads(live['stdout'])
        if '--native' in sys.argv:
            assert process['native_model_pids']
        record = {'started_at': stamp(), 'project_id': pid, 'job_id': before['id'], 'before':
        {'stage': before['stage'], 'state': before['state'], 'recoveries': before['recoveries'], 'valid_scenes': len(valid),
         'completed_media': [{'scene_id': s['id'], 'tts_sha256': s['tts']['sha256'], 'portrait_sha256': s['portrait']['sha256'], 'compose_sha256': s['compose']['sha256']} for s in valid]},
        'processes': process, 'teacher_confirmation_submitted': False}
        write_json(OUT, record)
        run(['powershell.exe', '-NoProfile', '-Command', f"Stop-Process -Id {int(process['server_pid'])}"], 15)
    # A persistent service must not inherit the short-command kill-on-close job.
    with (ROOT / 'storage/m4-workbench-restart.stdout.log').open('ab') as stdout, (ROOT / 'storage/m4-workbench-restart.stderr.log').open('ab') as stderr:
        subprocess.Popen([str(ROOT / '.venv-m1/Scripts/python.exe'), '-m', 'mooc_m2', '--port', '8765'],
                         cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    child_pids = [x for x in process.get('child_pids', []) if x]
    if isinstance(child_pids, int):
        child_pids = [child_pids]
    deadline = time.monotonic() + 15
    while any(LocalModelAdapter._pid_alive(x) for x in child_pids) and time.monotonic() < deadline:
        time.sleep(.2)
    assert all(not LocalModelAdapter._pid_alive(x) for x in child_pids)
    record['owned_children_exited'] = True
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=10) as c:
        for _ in range(100):
            try:
                if c.get('/api/health').json().get('worker_alive'):
                    break
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(.2)
        c.post('/api/session', json={'token': store.token}).raise_for_status()
        state = c.get(f'/api/projects/{pid}/generation').json()
    after = next(j for j in store.jobs(pid) if j['id'] == before['id'])
    assert after['id'] == record['job_id'] and after['recoveries'] > record['before']['recoveries']
    for s in valid:
        for layer in ['tts', 'portrait', 'compose']:
            assert digest(store.file(pid, s[layer]['path'])) == s[layer]['sha256']
    record.update(after={'state': state['state'], 'stage': state['stage'], 'recoveries': after['recoveries'],
                         'same_job_id': True, 'completed_media_hashes_unchanged': True}, finished_at=stamp())
    write_json(OUT, record)
    print({'restart': 'passed', 'recoveries': after['recoveries'], 'owned_children_exited': True, 'valid_scenes_before': len(valid)})


if __name__ == '__main__':
    main()
