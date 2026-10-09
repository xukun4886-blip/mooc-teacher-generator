"""Load final code through the documented launcher, only when queue is idle."""
import json
import subprocess
import time
import sys
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.content import fingerprint
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/M4/final-startup.json'


def ps(command):
    command = '[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); ' + command
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                          cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()


def main():
    resume = '--resume' in sys.argv
    if OUT.exists() and not resume:
        raise RuntimeError('Final startup evidence exists; do not repeat service interruptions')
    store = Store(ROOT / 'storage/m2')
    with store.connection() as db:
        active = db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
    if active:
        raise RuntimeError('Queue is active; leave running generation untouched')
    paths = read_json(ROOT / 'docs/evidence/M3/external-long-courses.json')['paths']
    before = {e['project_id']: fingerprint(store.get(e['project_id'])) for e in paths.values()}
    if resume:
        first = read_json(OUT)
        assert first['state'] == 'failed' and first['code'] == 'STARTUP_TIMEOUT'
        write_json(OUT.with_name('final-startup-first.json'), first)
        process = first['previous_process']
    else:
        process = json.loads(ps("$l=Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 8765; if(@($l).Count -ne 1){throw 'Unexpected listener count'}; $p=Get-CimInstance Win32_Process -Filter \"ProcessId = $($l.OwningProcess)\"; if($p.CommandLine -notlike '*-m mooc_m2*'){throw 'Unexpected listener owner'}; @{pid=$p.ProcessId; command_line=$p.CommandLine} | ConvertTo-Json -Compress"))
    record = {'started_at': stamp(), 'active_jobs_before': active, 'previous_process': process,
              'method': 'documented direct Python CLI; hidden independent long-lived process; no execution policy changed',
              'teacher_confirmation_submitted': False}
    if not resume:
        ps('Stop-Process -Id ' + str(int(process['pid'])))
    with (ROOT / 'storage/m4-final-startup.stdout.log').open('ab') as stdout, (ROOT / 'storage/m4-final-startup.stderr.log').open('ab') as stderr:
        launcher = subprocess.Popen([str(ROOT / '.venv-m1/Scripts/python.exe'), '-m', 'mooc_m2', '--port', '8765'],
                                    cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=10) as client:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                health = client.get('/api/health').json()
                if health.get('application') == 'mooc-workbench' and health.get('worker_alive'):
                    break
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(.2)
        else:
            record.update(state='failed', code='STARTUP_TIMEOUT', launcher_pid=launcher.pid, finished_at=stamp())
            write_json(OUT, record)
            raise RuntimeError('Startup failed; inspect protected logs')
        assert client.get('/').status_code == 200
        client.post('/api/session', json={'token': store.token}).raise_for_status()
        states = {mode: client.get('/api/projects/' + entry['project_id'] + '/generation').json() for mode, entry in paths.items()}
    assert all(state['state'] == 'completed' and not state.get('teacher_confirmation') for state in states.values())
    assert all(fingerprint(store.get(pid)) == old for pid, old in before.items())
    record.update(state='passed', health=health, root_http_status=200, launcher_pid=launcher.pid,
                  first_failure_retained=resume, projects_unchanged=True,
                  courses={mode: {'state': state['state'], 'media_job_id': state['media']['id'], 'teacher_confirmed': False} for mode, state in states.items()},
                  code_sha256={str(path.relative_to(ROOT)): digest(path) for path in [ROOT / 'mooc_m2/service.py', ROOT / 'mooc_m3/pipeline.py', ROOT / 'mooc_m1/core.py']}, finished_at=stamp())
    write_json(OUT, record)
    print({'startup': 'passed', 'projects_unchanged': True, 'worker_alive': health['worker_alive']})


if __name__ == '__main__':
    main()
