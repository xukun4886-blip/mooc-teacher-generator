"""Validate documented local startup, authentication and persistence on isolated storage."""
import os
import sys
import json
import time
import platform
import subprocess
from pathlib import Path
from importlib.metadata import version
import httpx
from mooc_m1.core import read_json, write_json, stamp, digest, run

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    folder = ROOT / 'storage/m4-delivery'
    folder.mkdir(parents=True, exist_ok=True)
    config = read_json(ROOT / 'config/m2.example.json')
    config.update(storage=str(folder / 'workbench'), m1_config='config/m1.local.json')
    config_path = folder / 'm2.delivery.json'
    write_json(config_path, config)
    evidence = {'created_at': stamp(), 'scope': 'local startup/restart on independent validation storage; not clean-machine installation',
                'port': 8766, 'config_path': str(config_path), 'teacher_confirmation_submitted': False, 'checks': []}
    client = httpx.Client(base_url='http://127.0.0.1:8766', trust_env=False, timeout=15)
    processes = []
    logs = []
    def start(index):
        log = (folder / f'start-{index}.log').open('wb')
        logs.append(log)
        proc = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'tools/m2_start.ps1'), '-NoBrowser', '-Port', '8766', '-Config', str(config_path)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(proc)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError('Launcher exited; inspect isolated startup log')
            try:
                health = client.get('/api/health')
                if health.status_code == 200 and health.json().get('worker_alive'):
                    return health.json()
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        raise RuntimeError('Startup did not become healthy within 45 seconds')
    def stop_server():
        # Only the validated unique module, port and config; never enumerate then
        # send deletion commands through another shell.
        command = "$listener=Get-NetTCPConnection -State Listen -LocalAddress 127.0.0.1 -LocalPort 8766; $p=Get-CimInstance Win32_Process -Filter \"ProcessId = $($listener.OwningProcess)\"; if($p.CommandLine -notlike '*-m mooc_m2*' -or $p.CommandLine -notlike '*m2.delivery.json*'){throw 'Unexpected isolated service owner'}; Stop-Process -Id $p.ProcessId"
        run(['powershell.exe', '-NoProfile', '-Command', command], 15)
        processes[-1].wait(timeout=15)
    try:
        evidence['startup_health'] = start(1)
        assert client.get('/').status_code == 200
        assert client.get('/api/projects').status_code == 401
        token = (folder / 'workbench/.session-token').read_text().strip()
        client.post('/api/session', json={'token': token}).raise_for_status()
        assert client.get('/api/projects', headers={'Origin': 'https://example.invalid'}).status_code == 403
        assert client.get('/api/projects', headers={'Host': 'example.invalid'}).status_code == 403
        response = client.post('/api/projects', json={'name': '启动与恢复验收 · 隔离测试'})
        response.raise_for_status()
        pid = response.json()['id']
        evidence['project_id'] = pid
        ticket = client.post('/api/session/launch-ticket').json()['ticket']
        assert client.post('/api/session/launch', json={'ticket': ticket}).status_code == 200
        assert client.post('/api/session/launch', json={'ticket': ticket}).status_code == 401
        error = client.post(f'/api/projects/{pid}/generate')
        assert error.status_code == 422 and error.json()['error']['code'] == 'INPUT_MISSING'
        stop_server()
        evidence['restart_health'] = start(2)
        assert client.get(f'/api/projects/{pid}').json()['name'] == '启动与恢复验收 · 隔离测试'
        existing = run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            ROOT / 'tools/m2_start.ps1', '-NoBrowser', '-Port', '8766', '-Config', config_path], 30)
        assert '已运行' in existing['stdout']
        evidence['checks'] = ['root_200', 'unauthenticated_401', 'cross_origin_403', 'host_403',
                              'one_use_ticket', 'missing_input_422_no_media', 'project_survives_actual_restart', 'reuse_existing_healthy_service']
        stop_server()
        evidence['state'] = 'passed'
    except Exception as exc:
        evidence.update(state='failed', error={'type': type(exc).__name__, 'message': str(exc)[:300]})
        raise
    finally:
        client.close()
        for log in logs:
            log.close()
        evidence['finished_at'] = stamp()
        write_json(ROOT / 'docs/evidence/M4/delivery-startup.json', evidence)
    m1 = read_json(ROOT / 'config/m1.local.json')
    versions = {'checked_at': stamp(), 'os': platform.platform(), 'control_python': sys.version,
                'application_version': evidence['startup_health']['version'],
                'packages': {name: version(name) for name in ['fastapi', 'uvicorn', 'starlette', 'httpx', 'python-pptx', 'Pillow', 'pywin32']},
                'node': run(['node', '--version'], 15)['stdout'].strip(),
                'frontend_lock_sha256': digest(ROOT / 'frontend/package-lock.json'), 'models': {}}
    for role, model in m1['models'].items():
        versions['models'][role] = {k: model.get(k) for k in ['python', 'repo', 'code_revision', 'weight_version', 'memory_profile', 'tokenizer_backend']}
        versions['models'][role]['pip_check'] = run([model['python'], '-m', 'pip', 'check'], 60)['stdout'].strip()
        versions['models'][role]['freeze'] = run([model['python'], '-m', 'pip', 'freeze'], 60)['stdout'].splitlines()
        weights = []
        for weight in model['weights']:
            actual = digest(weight['path'])
            assert actual == weight['sha256']
            weights.append({'name': Path(weight['path']).name, 'sha256': actual})
        versions['models'][role]['weights'] = weights
        actual_revision = run(['git', '-C', model['repo'], 'rev-parse', 'HEAD'], 15)['stdout'].strip()
        assert actual_revision == model['code_revision']
        versions['models'][role]['actual_revision'] = actual_revision
    versions['clean_machine_rebuild_verified'] = False
    write_json(ROOT / 'docs/evidence/M4/version-inventory.json', versions)
    print({'delivery_startup': evidence['state'], 'version_inventory': True, 'clean_machine_rebuild_verified': False})


if __name__ == '__main__':
    main()
