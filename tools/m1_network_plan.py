"""Read official model metadata without the broken Windows registry proxy."""
import json
from pathlib import Path
import requests

s = requests.Session()
s.trust_env = False
root = Path('.tools')
root.mkdir(exist_ok=True)
for model in ['lj1995/GPT-SoVITS', 'XXXXRT/GPT-SoVITS-Pretrained']:
    r = s.get(f'https://huggingface.co/api/models/{model}?blobs=true', timeout=60)
    r.raise_for_status()
    j = r.json()
    (root / (model.split('/')[0] + '-metadata.json')).write_text(json.dumps(j), encoding='utf-8')
    print(model, j['sha'], flush=True)
    print([x for x in j['siblings'] if any(t in x['rfilename'] for t in ['gsv-v2final', 'chinese-roberta', 'chinese-hubert', 'G2PW'])], flush=True)
r = s.get('https://download.pytorch.org/whl/cu118/torch/', timeout=60)
print('CUDA wheel index status', r.status_code, flush=True)
print([x.strip()[:400] for x in r.text.splitlines() if '2.5.1%2Bcu118-cp310-cp310-win_amd64' in x], flush=True)
