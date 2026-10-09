"""Read-only foreground monitor for this run; no generation, retries or approvals."""
import time
import json
import sys
from pathlib import Path
from mooc_m1.core import read_json, write_json, stamp
from mooc_m2.store import Store


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    root = Path(__file__).resolve().parents[1]
    fresh = '--fresh-ai' in sys.argv
    paths = read_json(root / ('docs/evidence/M3/fresh-ai-validation.json' if fresh else 'docs/evidence/M3/external-long-courses.json'))['paths']
    store = Store(root / 'storage/m2')
    history = []
    output = root / ('docs/evidence/M4/fresh-ai-progress.json' if fresh else 'docs/evidence/M4/real-course-progress.json')
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        observation = {'at': stamp(), 'paths': {}}
        for mode, entry in paths.items():
            jobs = [j for j in store.jobs(entry['project_id']) if j['kind'] == 'm3']
            j = jobs[0] if jobs else next(j for j in store.jobs(entry['project_id']) if j['kind'] == 'course')
            scenes = j.get('scenes', [])
            observation['paths'][mode] = {'state': j['state'], 'stage': j['stage'], 'job_id': j['id'],
                'valid': sum(s['state'] == 'valid' for s in scenes), 'total': len(scenes) if j['kind'] == 'm3' else j.get('total'), 'error': j.get('error')}
        history.append(observation)
        write_json(output, {'scope': 'actual foreground read-only observations; no timer percentages', 'observations': history})
        print(json.dumps(observation, ensure_ascii=False), flush=True)
        if all(v['state'] in {'failed','completed','canceled'} for v in observation['paths'].values()):
            return
        time.sleep(40)
    raise RuntimeError('Monitor duration reached; generation status remains authoritative')


if __name__ == '__main__':
    main()
