"""Validate current real outputs and docs without replacing older evidence."""
import sys,re,json,hashlib
from pathlib import Path
from urllib.parse import unquote
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mooc_m1.core import read_json,write_json,digest,stamp
from mooc_m2.api import create_app
from mooc_m2.content import current

app=create_app(worker=False);svc=app.state.service
lesson=read_json(ROOT/'docs/evidence/M2/formal-lesson-review.json');p=svc.store.get(lesson['project_id'])
active=[s for s in p['scenes'] if not s['skipped']]
assert len(active)==10 and all(not s['confirmed'] for s in active)
questions={q['question'].strip() for s in active for q in current(s)['checks']['questions']}
assert len(questions)>=5
audios=[]
findings=[]
packet_path=svc.store.folder(p['id'])/'teacher-review-packet.md'
packet=packet_path.read_text(encoding='utf-8').split('\n\n## 具体待审核清单（工具仅提供线索，教师决定）')[0]
packet+='\n\n## 具体待审核清单（工具仅提供线索，教师决定）\n'
for s in active:
    page=next(x for x in p['slides'] if x['source_page_id']==s['play_page_id']);v=current(s)
    assert all(q['source_page_id'] in s['source_page_ids'] for q in v['checks']['questions'])
    a=s['preview_audition'];assert a['draft_preview'] and not a['human_review'] and a['version_id']==v['id']
    assert s['audition'] is None
    inspected=svc.media.inspect(svc.store.file(p['id'],a['path']),'audio')
    assert inspected['sha256']==a['sha256']
    audios.append({'source_index':page['source_index'],'sha256':a['sha256'],'duration_seconds':inspected['duration_seconds'],'silence_ratio':inspected['silence_ratio'],'provider':a['provider'],'draft_preview':True})
    pending=list(v['checks']['pending'])
    pending.extend(f"读法项‘{t['text']}’当前为‘{t['reading']}’，请核对并改成可朗读的中文读法，应用后重新试听。" for t in v['checks']['terms'] if re.search(r'[\u4e00-\u9fff]',t['text']) and not re.search(r'[\u4e00-\u9fff]',t['reading']))
    review_text='\n'.join([v['display_text'],v['reading_text'],*[q['answer'] for q in v['checks']['questions']]])
    values=re.findall(r'\d+(?:\.\d+)?(?:[–到\-]\d+(?:\.\d+)?)?',review_text)
    if values:pending.append('核对讲稿数字、单位与所属概念：'+ '、'.join(dict.fromkeys(values)))
    if page['source_index']==5:
        pending[-1]='请逐项对照原页图表：草稿将 RAN、30–100 公里、54–862 MHz、低于 60 GHz 归入无线蜂窝网，答案还将无线局域网归入个人区域网。核查这些标签、范围与网络类别的对应关系，修订知识点、讲稿和答案；来源关联本身不证明答案正确。'
    pending.append('播放本页完整试听，核查音色、术语读法、漏句、重复，并与原页逐项核对。')
    if page['source_index'] in (12,13):
        pending[-1]=f"本页草稿试听实际 {inspected['duration_seconds']:.2f} 秒，请完整对照读法稿核查是否漏句/重复及课时节奏，并核查音色与术语；解码成功不代表试听质量通过。"
    for finding in pending:packet+=f"\n- 原页 {page['source_index']}：{finding}\n"
    findings.append({'source_index':page['source_index'],'items':pending})
packet_path.write_text(packet,encoding='utf-8')
write_json(svc.store.folder(p['id'])/'teacher-review-items.json',findings)
with svc.store.edit(p['id']) as project:
    project['review_packet']='teacher-review-packet.md'
    project['review_items']=findings
lesson['question_count']=len(questions);lesson['real_audition_redecode']=audios
lesson['private_review_packet']={'path':str(packet_path),'sha256':digest(packet_path)}
lesson['private_review_items']={'path':str(svc.store.folder(p['id'])/'teacher-review-items.json'),'sha256':digest(svc.store.folder(p['id'])/'teacher-review-items.json')}
lesson['review_item_count']=sum(len(f['items']) for f in findings)
lesson['verified_at']=stamp()
write_json(ROOT/'docs/evidence/M2/formal-lesson-review.json',lesson)

errors=[];links=0
documents=[ROOT/'AGENTS.md',*list((ROOT/'docs').glob('*.md')),*list((ROOT/'specs').glob('*.md')),*list((ROOT/'.agents/skills').glob('*/SKILL.md')),ROOT/'docs/evidence/M2/README.md']
for path in documents:
    for target in re.findall(r'\]\(([^)]+)\)',path.read_text(encoding='utf-8')):
        if '://' in target or target.startswith('#'):continue
        links+=1
        if not (path.parent/unquote(target.split('#')[0])).exists():errors.append(str(path.relative_to(ROOT))+' -> '+target)
ids=re.findall(r'^\| (M[1-4]-F\d\d) \|',(ROOT/'docs/PROJECT_STATUS.md').read_text(encoding='utf-8'),re.M)
assert len(ids)==24 and len(set(ids))==24
assert all('- [x]' not in (ROOT/f'specs/{stage}.spec.md').read_text(encoding='utf-8') for stage in ['M1-capability-validation','M2-content-pipeline'])
write_json(ROOT/'docs/evidence/M2/document-round2-check.json',{'checked_at':stamp(),'links_checked':links,'errors':errors,'stable_work_items':24,'m1_m2_exit_unchecked':True})
assert not errors,errors
print('Real draft auditions redecoded:',len(audios),'unique draft questions:',len(questions),'teacher confirmations: 0; docs checked',links)
