"""Pinned MuseTalk v15 and inference auxiliaries from upstream download list."""
import json
from concurrent.futures import ThreadPoolExecutor
import requests
from m1_fetch_gpt_weights import ROOT, fetch

repo=ROOT/'.tools/models/MuseTalk'
selections=[('TMElyralab/MuseTalk','TMElyralab','',['musetalkV15/musetalk.json','musetalkV15/unet.pth','LICENSE.txt']),
 ('stabilityai/sd-vae-ft-mse','stabilityai','sd-vae',['config.json','diffusion_pytorch_model.bin']),
 ('openai/whisper-tiny','openai','whisper',['config.json','pytorch_model.bin','preprocessor_config.json']),
 ('yzd-v/DWPose','yzd-v','dwpose',['dw-ll_ucoco_384.pth']),
 ('ManyOtherFunctions/face-parse-bisent','ManyOtherFunctions','face-parse-bisent',['79999_iter.pth','resnet18-5c106cde.pth'])]
plan=[]
for model,key,directory,names in selections:
    meta=json.loads((ROOT/f'.tools/{key}-muse-metadata.json').read_text())
    for name in names:
        entry=next(x for x in meta['siblings'] if x['rfilename']==name)
        plan.append((model,meta['sha'],entry,repo/'models'/directory/name))
s=requests.Session(); s.trust_env=False
url='https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth'
r=s.head(url,timeout=45);r.raise_for_status()
size=int(r.headers['Content-Length'])
plan.append(('adrianbulat/python-fan','source-linked-S3FD',{'rfilename':'s3fd.pth','size':size,'url':url},repo/'musetalk/utils/face_detection/detection/sfd/s3fd.pth'))
records=[]
with ThreadPoolExecutor(max_workers=3) as pool:
    for record in pool.map(fetch,plan):
        records.append(record)
        (ROOT/'docs/evidence/M1/muse-weight-downloads.json').write_text(json.dumps({'records':records,'generation_called':False},indent=2),encoding='utf-8')
print('MuseTalk inference set complete',all(x['ready'] for x in records),flush=True)
