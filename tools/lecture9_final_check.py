"""Read-only final evidence: retained files, native output frames and docs integrity."""
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote
import httpx
from mooc_m1.core import digest, read_json, write_json, stamp, run
from mooc_m2.service import Service

ROOT = Path(__file__).resolve().parents[1]
PID = '11604689-6106-451f-b40b-95089e07b5b5'
MID = '3c71bde5-a379-452b-9992-2064c7878a46'
svc = Service(read_json(ROOT / 'config/m2.local.json'))
j = svc.m3.get(PID, MID)
assert j['state'] == 'completed' and all(s['state'] == 'valid' for s in j['scenes'])
result = {'at': stamp(), 'media_id': MID, 'state': j['state'], 'duration_seconds': j['result']['duration_seconds'],
          'real_elapsed_seconds': j['elapsed_seconds'], 'valid_pages': len(j['scenes']),
          'cache_hits': {k: sum(s['cache_hits'][k]['hit'] for s in j['scenes']) for k in ('tts','portrait','compose')},
          'paid_allowed': svc.config['ai']['allow_paid'], 'metrics_frozen': False, 'teacher_confirmation_filled': False,
          'exports': {k: str(svc.store.file(PID, path)) for k,path in j['result']['exports'].items()},
          'artifact_hashes': j['result']['file_hashes'], 'frames': []}
video = svc.store.file(PID, j['result']['path'])
frame_root = ROOT / 'storage/m4-review/lecture9-final-frames'
frame_root.mkdir(parents=True, exist_ok=True)
for page, seconds in ((1,5),(11,446.772),(24,718.5)):
    target = frame_root / f'page-{page}.png'
    if not target.exists():
        run([svc.media.ffmpeg,'-nostdin','-v','error','-ss',str(seconds),'-i',video,'-frames:v','1',target],60)
    md = svc.media.inspect(target,'photo')
    result['frames'].append({'page':page,'seconds':seconds,'path':str(target),'sha256':md['sha256']})
download = Path('C:/Users/及时行乐/Downloads/draft-course (6).mp4')
assert digest(download) == j['result']['file_hashes']['mp4']
result['browser_download'] = {'path':str(download),'bytes':download.stat().st_size,'sha256':digest(download),'matches_final_export':True}
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=60) as client:
    client.post('/api/session',json={'token':(svc.store.root/'.session-token').read_text().strip()}).raise_for_status()
    result['runtime_health'] = client.get('/api/health').json()
    assert result['runtime_health']['worker_alive'] is True
    html = client.get('/').text
    asset = re.search(r'src="(/assets/[^\"]+\.js)"',html).group(1)
    served = client.get(asset);served.raise_for_status()
    assert '本次制作的重试次数已用完，已完成页面保留。讲稿服务或生成配置修复后可继续制作。' in served.text
    import hashlib
    result['frontend_bundle'] = {'path':asset,'sha256':hashlib.sha256(served.content).hexdigest(),'new_exhaustion_hint_in_served_bundle':True}
    current = client.get(f'/api/projects/{PID}/generation').json()
    assert current['state']=='completed' and current['is_current'] and not current['teacher_confirmation']
    result['current_generation'] = {k:current[k] for k in ('id','state','stage','is_current','teacher_confirmation')}
    response = client.get(f'/api/projects/{PID}/files/{j["result"]["path"]}',headers={'Range':'bytes=0-1023'})
    assert response.status_code==206 and len(response.content)==1024
    result['range_request'] = {'status':206,'bytes':1024,'content_range':response.headers.get('content-range')}
files = [ROOT/'AGENTS.md',ROOT/'README.md']
files += list((ROOT/'specs').glob('*.md')) + list((ROOT/'docs').rglob('*.md'))
files += list((ROOT/'.agents/skills').glob('*/SKILL.md'))
errors,checked = [],0
for path in files:
    text = path.read_text(encoding='utf-8-sig')
    assert '\ufffd' not in text
    for match in re.finditer(r'\[[^\]\n]*\]\(([^\)]+)\)',text):
        target=match.group(1).strip().strip('<>')
        if target.startswith(('https://','http://','#','mailto:','codex:')):continue
        target=unquote(target.split('#')[0]);checked+=1
        if not (path.parent/target).exists():errors.append(str(path.relative_to(ROOT))+' -> '+target)
assert not errors, errors
result['documentation']={'files':len(files),'local_links_checked':checked,'errors':errors}
state = (ROOT/'docs/PROJECT_STATUS.md').read_text(encoding='utf-8')
items = re.findall(r'^\| (M[1-4]-F\d\d) \|',state,re.MULTILINE)
assert len(items)==24 and set(items)=={f'M{s}-F{i:02d}' for s in range(1,5) for i in range(1,7)}
tracking = (ROOT/'specs/TRACEABILITY.md').read_text(encoding='utf-8')
for prefix,count in (('FR',20),('NFR',8),('AC',18)):
    assert set(re.findall(r'^\| ('+prefix+r'\d\d)\b',tracking,re.MULTILINE))=={f'{prefix}{i:02d}' for i in range(1,count+1)}
result['documentation'].update(stable_work_items=24,fr=20,nfr=8,ac=18)
key = os.environ.get('ZHIPUAI_API_KEY')
checked_source = 0
if key:
    for folder in ('config','docs','specs','mooc_m1','mooc_m2','mooc_m3','tests','tools','frontend'):
        for path in (ROOT/folder).rglob('*'):
            if not path.is_file() or any(x in path.parts for x in ('node_modules','__pycache__')):continue
            if path.suffix not in ('.py','.md','.json','.vue','.ts','.js','.toml','.yaml','.yml'):continue
            assert key not in path.read_text(encoding='utf-8',errors='ignore'), str(path.relative_to(ROOT))
            checked_source+=1
result['credential_scan']={'files':checked_source,'credential_value_found':False,'scope':'source/config/evidence; value never printed'}
write_json(ROOT/'docs/evidence/M4/lecture9-final-check.json',result)
print(json.dumps({k:result[k] for k in ('state','duration_seconds','real_elapsed_seconds','valid_pages','cache_hits','documentation','credential_scan')},ensure_ascii=False))
