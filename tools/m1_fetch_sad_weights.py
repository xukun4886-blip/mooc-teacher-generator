"""Get the official SadTalker 256/full set and required face auxiliaries."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from m1_fetch_gpt_weights import ROOT, fetch

s = requests.Session()
s.trust_env = False
plan = []
repo = ROOT / '.tools/models/SadTalker'
for owner, tag, names, directory in [
    ('OpenTalker/SadTalker','v0.0.2-rc',['mapping_00109-model.pth.tar','SadTalker_V0.0.2_256.safetensors'],'checkpoints'),
    ('xinntao/facexlib','v0.1.0',['alignment_WFLW_4HG.pth','detection_Resnet50_Final.pth'],'gfpgan/weights'),
]:
    r = s.get(f'https://api.github.com/repos/{owner}/releases/tags/{tag}',timeout=45)
    r.raise_for_status()
    assets = r.json()['assets']
    for name in names:
        a = next(x for x in assets if x['name']==name)
        entry = {'rfilename': name, 'size': a['size'], 'url': a['browser_download_url']}
        if a.get('digest','') and a['digest'].startswith('sha256:'):
            entry['lfs']={'sha256':a['digest'].split(':')[1]}
        plan.append((owner, f'{tag}:asset-{a["id"]}', entry, repo/directory/name))
records=[]
with ThreadPoolExecutor(max_workers=3) as pool:
    for record in pool.map(fetch,plan):
        records.append(record)
        (ROOT/'docs/evidence/M1/sad-weight-downloads.json').write_text(json.dumps({'records':records,'generation_called':False},indent=2),encoding='utf-8')
print('required SadTalker set complete', all(x['ready'] for x in records), flush=True)
