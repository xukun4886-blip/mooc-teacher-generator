import sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mooc_m1.core import write_json
with httpx.Client(base_url='http://127.0.0.1:8765/api',trust_env=False,timeout=30) as c:
    c.post('/session',json={'token':(ROOT/'storage/m2/.session-token').read_text().strip()}).raise_for_status()
    p=c.post('/projects/57866fdf-6350-400b-9911-8c9bd9cc407f/copy').json();pid=p['id']
    for action,data in [('category',{'category':'development'}),('config',{'course_name':'M2 浏览器表单检查 · 隔离副本'})]:
        r=c.post(f'/projects/{pid}/commands',json={'revision':p['revision'],'action':action,'data':data});r.raise_for_status();p=r.json()
    # Clone is engineering-only; preserve source evidence and keep every review pending.
    sid=p['scenes'][0]['id']
    r=c.post(f'/projects/{pid}/commands',json={'revision':p['revision'],'action':'script','data':{'scene_id':sid,'display_text':'浏览器工程验证用稿。区间 [0,1] 与数组 [1,2,3] 原样保留。','reading_text':'浏览器工程验证用稿，零到一的闭区间与数组一二三。'}});r.raise_for_status()
    write_json(ROOT/'storage/m2/browser-round2-project.json',{'project_id':pid,'scene_id':sid,'engineering_only':True})
    print('Isolated browser test project prepared; original evidence unchanged')
