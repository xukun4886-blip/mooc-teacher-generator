"""Open an existing local service without exposing the persistent token."""
import argparse,json,webbrowser
from pathlib import Path
import httpx
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);parser.add_argument('--config',default='config/m2.local.json');args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
path=root/args.config
config=json.loads((path if path.is_file() else root/'config/m2.example.json').read_text(encoding='utf-8-sig'))
token=(root/config.get('storage','storage/m2')/'.session-token').read_text().strip()
with httpx.Client(base_url=f'http://127.0.0.1:{args.port}',trust_env=False,timeout=10) as client:
    health=client.get('/api/health');health.raise_for_status()
    if health.json().get('application')!='mooc-workbench' or not health.json().get('worker_alive'):
        raise RuntimeError('Expected local workbench is not healthy; session token was not sent')
    client.post('/api/session',json={'token':token}).raise_for_status()
    response=client.post('/api/session/launch-ticket');response.raise_for_status()
    webbrowser.open(f'http://127.0.0.1:{args.port}/#launch={response.json()["ticket"]}')
print('Local workbench opened with a one-use ticket.')
