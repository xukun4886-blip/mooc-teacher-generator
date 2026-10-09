import copy
import json
import time
import re
import httpx
import pytest
from PIL import Image
from test_m2 import app, client, seed, cmd, checks
from mooc_m2.content import current, audition_key
from mooc_m1.core import Failure


def provider(app, monkeypatch, response_fn=None):
    svc = app.state.service
    svc.config['ai'] = {'base_url':'http://127.0.0.1:9999/v1','model':'test-double','api_key_env':''}
    for p in svc.store.list():
        Image.new('RGB',(20,20)).save(svc.store.file(p['id'],'missing.png'))
    sent=[]
    original=httpx.Client.post
    def post(self,url,**kw):
        if not str(url).startswith('http://127.0.0.1:9999/'):
            return original(self,url,**kw)
        sent.append(kw['json'])
        if response_fn: return response_fn(kw['json'])
        source = re.search(r'当前来源页ID：([^\n]+)', kw['json']['messages'][1]['content'][0]['text']).group(1)
        draft={'display_text':'真实服务替身仅测试编排','reading_text':'真实服务替身仅测试编排','knowledge_points':['知识点'],'questions':[{'question':'测试问题','answer':'测试答案','source_page_id':source}],'terms':[],'pending':['教师待判断'],'extensions':[]}
        return httpx.Response(200,json={'id':'test-response','choices':[{'message':{'content':json.dumps(draft)}}]},request=httpx.Request('POST',url))
    monkeypatch.setattr('httpx.Client.post',post)
    return svc,sent


def test_batch_duplicate_full_context_and_atomic_revision(app,client,monkeypatch):
    p=seed(app,5); svc,sent=provider(app,monkeypatch)
    b=svc.queue_ai(p['id'],p['revision'])
    assert b['total']==5
    assert len(svc.store.jobs(p['id']))==5
    with pytest.raises(Failure,match='已有 AI'): svc.queue_ai(p['id'],p['revision'])
    with pytest.raises(Failure): svc.queue_ai(p['id'],p['revision']-1,[p['scenes'][0]['id']])
    while j:=svc.store.claim(): svc.execute(j)
    assert all(j['state']=='completed' for j in svc.store.jobs(p['id']))
    assert all(all(f'第{i}页：' in x['messages'][1]['content'][0]['text'] for i in range(1,6)) for x in sent)
    assert all(s['confirmed'] is None for s in svc.store.get(p['id'])['scenes'])


def test_queued_input_edit_conflict_and_failed_only_retry(app,client,monkeypatch):
    p=seed(app);svc,_=provider(app,monkeypatch)
    b=svc.queue_ai(p['id'],p['revision'])
    p=cmd(client,p,'script',{'scene_id':p['scenes'][0]['id'],'display_text':'教师排队期间编辑'})
    while j:=svc.store.claim(): svc.execute(j)
    jobs=svc.store.jobs(p['id'])
    assert sum(j['state']=='failed' for j in jobs)==1
    assert next(j for j in jobs if j['state']=='failed')['error']['code']=='REVISION_CONFLICT'
    p=svc.store.get(p['id']); b=svc.queue_ai(p['id'],p['revision'],retry_failed=True)
    assert b['total']==1
    svc.execute(svc.store.claim())
    s=svc.store.get(p['id'])['scenes'][0]
    assert current(s)['display_text']=='教师排队期间编辑' and s['ai_candidate']


def test_invalid_ai_answer_source_never_stored(app,client,monkeypatch):
    p=seed(app)
    def bad(req):
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'display_text':'草稿','reading_text':'草稿','knowledge_points':[],'questions':[{'question':'问题','answer':'答案','source_page_id':'invented'}],'terms':[],'pending':[],'extensions':[]})}}]},request=httpx.Request('POST','http://localhost'))
    svc,_=provider(app,monkeypatch,bad);svc.queue_ai(p['id'],p['revision'],[p['scenes'][0]['id']]);svc.execute(svc.store.claim())
    assert svc.store.jobs(p['id'])[0]['error']['code']=='AI_FORMAT_INVALID'
    assert not svc.store.get(p['id'])['scenes'][0]['versions']


def test_review_draft_version_adopt_ai_and_teacher_gate(app,client,monkeypatch):
    p=seed(app);sid=p['scenes'][0]['id'];svc,_=provider(app,monkeypatch)
    p=cmd(client,p,'script',{'scene_id':sid,'display_text':'人工稿'})
    p=cmd(client,p,'checks',{'scene_id':sid,'checks':checks(p['scenes'][0])})
    p=cmd(client,p,'review',{'scene_id':sid,'checks':checks(p['scenes'][0]),'note':'教师核查记录'})
    approved=p['scenes'][0]['confirmed'];svc.queue_ai(p['id'],p['revision'],[sid]);svc.execute(svc.store.claim())
    p=svc.store.get(p['id']);s=p['scenes'][0]
    assert s['confirmed']==approved and current(s)['display_text']=='人工稿'
    p=cmd(client,p,'adopt_ai',{'scene_id':sid,'version_id':s['ai_candidate']})
    assert p['scenes'][0]['confirmed'] is None
    cmd(client,p,'review',{'scene_id':sid,'checks':current(p['scenes'][0])['checks'],'note':'未处理待审核项'},422)


def test_single_use_launch_and_expiry(app):
    from fastapi.testclient import TestClient
    c=TestClient(app)
    app.state.launch_ticket='temporary';app.state.launch_created=time.monotonic()
    assert c.post('/api/session/launch',json={'ticket':'temporary'},headers={'Origin':'https://evil.invalid'}).status_code==403
    assert c.post('/api/session/launch',json={'ticket':'temporary'}).status_code==200
    assert c.get('/api/projects').status_code==200
    assert c.post('/api/session/launch',json={'ticket':'temporary'}).status_code==401
    app.state.launch_ticket='expired';app.state.launch_created=time.monotonic()-121
    assert c.post('/api/session/launch',json={'ticket':'expired'}).status_code==401


def test_draft_preview_not_formal_review(app,client):
    p=seed(app);sid=p['scenes'][0]['id']
    p=cmd(client,p,'script',{'scene_id':sid,'display_text':'未审核课程稿'})
    svc=app.state.service
    with svc.store.edit(p['id']) as project:
        project['assets']['reference_audio']={'id':'ref','state':'ready','selection':{'transcript':'参考文字'},'selected':'ref.wav','sha256':'test','selected_sha256':'test'}
    p=svc.store.get(p['id'])
    with pytest.raises(Failure): svc.queue_audition(p['id'],sid,p['revision'])
    j=svc.queue_audition(p['id'],sid,p['revision'],True)
    assert j['payload']['draft_preview'] is True
    assert p['scenes'][0]['confirmed'] is None and p['scenes'][0]['audition'] is None
    cmd(client,p,'listen_review',{'scene_id':sid,'checks':{'timbre':True,'pronunciation':True,'no_omission':True,'no_repetition':True},'note':'不能以草稿试听确认正式内容'},422)


def test_project_category_preserves_evidence(app,client):
    p=seed(app)
    p=cmd(client,p,'category',{'category':'development'})
    assert next(x for x in client.get('/api/projects').json() if x['id']==p['id'])['category']=='development'
    assert len(p['scenes'])==3


def test_provider_multiline_text_is_preserved(app,client,monkeypatch):
    p=seed(app)
    def multiline(req):
        obj={'display_text':'正文\n第二行','reading_text':'正文\n第二行','knowledge_points':['正文'],'questions':[],'terms':[],'pending':[],'extensions':[]}
        raw=json.dumps(obj,ensure_ascii=False).replace('\\n','\n')
        return httpx.Response(200,json={'id':'real-format-test-double','choices':[{'message':{'content':raw}}]},request=httpx.Request('POST','http://localhost'))
    svc,_=provider(app,monkeypatch,multiline);svc.queue_ai(p['id'],p['revision'],[p['scenes'][0]['id']]);svc.execute(svc.store.claim())
    assert svc.store.jobs(p['id'])[0]['state']=='completed'
    assert current(svc.store.get(p['id'])['scenes'][0])['display_text']=='正文\n第二行'


def test_same_question_on_different_pages_is_not_five_questions(app,client):
    p=seed(app,5)
    for s in list(p['scenes']):
        p=cmd(client,p,'script',{'scene_id':s['id'],'display_text':'教师稿'})
        c=checks(s)
        p=cmd(client,p,'review',{'scene_id':s['id'],'checks':c,'note':'测试替身核查'})
    report=app.state.service.preflight(p,model_checks=False)
    assert any(b['code']=='TEACHING_CHECK_REQUIRED' and '至少' in b['message'] for b in report['blockers'])


def test_request_options_cannot_switch_to_paid_model(app,client,monkeypatch):
    p=seed(app);svc,sent=provider(app,monkeypatch)
    svc.config['ai']['request_options']={'model':'unexpected-paid-model','messages':[],'thinking':{'type':'disabled'}}
    svc.queue_ai(p['id'],p['revision'],[p['scenes'][0]['id']]);svc.execute(svc.store.claim())
    assert sent[0]['model']=='test-double' and sent[0]['messages']
    assert sent[0]['thinking']=={'type':'disabled'}


def test_explicit_current_source_alias_and_compact_poll(app,client,monkeypatch):
    p=seed(app)
    def alias(req):
        obj={'display_text':'当前原页草稿','reading_text':'当前原页草稿','knowledge_points':['原页知识点'],'questions':[{'question':'当前页问题','answer':'当前页答案','source_page_id':'current'}],'terms':[],'pending':[],'extensions':[]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(obj)}}]},request=httpx.Request('POST','http://localhost'))
    svc,_=provider(app,monkeypatch,alias);svc.queue_ai(p['id'],p['revision'],[p['scenes'][0]['id']]);svc.execute(svc.store.claim())
    v=current(svc.store.get(p['id'])['scenes'][0])
    assert v['checks']['questions'][0]['source_page_id']==p['slides'][0]['source_page_id']
    assert v['provenance']['expanded_current_source_count']==1
    jobs=client.get(f'/api/projects/{p["id"]}/jobs').json()
    assert 'context' not in jobs[0]['payload'] and jobs[0]['payload']['scene_id']
    assert 'context' in svc.store.jobs(p['id'])[0]['payload']
