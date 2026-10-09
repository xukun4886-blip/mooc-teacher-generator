"""Behavior of body checkpoints and local rules, not teaching-quality evidence."""
import copy
import json
import httpx
import pytest
from PIL import Image
from mooc_m1.core import Failure
from mooc_m2.content import current, fingerprint, review
from mooc_m2.narration import derive, number
from mooc_m2.draft_pipeline import validate_prose, validate_checks, settings
from mooc_m2.ai_draft import DraftFormatError
from test_m2 import app, client, seed, cmd
from test_m3 import rig, execute

ORIGINAL_HTTPX_POST = httpx.Client.post


def response(text, finish='stop'):
    return {'id':'test-provider', 'choices':[{'finish_reason':finish,'message':{'content':text,'reasoning_content':'不朗读的思考'}}]}


def checks(source='current'):
    return {'knowledge_points':['边缘计算'], 'questions':[{'question':'边缘处理的作用？','answer':'降低延迟。','source':source}], 'pending':[], 'extensions':[]}


def setup_provider(svc, monkeypatch, fn=None):
    svc.config['ai']={'base_url':'http://127.0.0.1:9999/v1','model':'vision-test','api_key_env':'',
                     'pipeline':{'enabled':True,'text_model':'text-test','request_options':{'max_tokens':2048}}}
    for p in svc.store.list():
        Image.new('RGB',(20,20)).save(svc.store.file(p['id'],'missing.png'))
    sent=[]
    def post(client, url, **kwargs):
        if not str(url).startswith('http://127.0.0.1:9999/'):
            return ORIGINAL_HTTPX_POST(client,url,**kwargs)
        req=kwargs['json'];sent.append(copy.deepcopy(req))
        stage='vision' if req['model']=='vision-test' else 'teaching' if req['response_format']['type']=='json_object' else 'narration'
        result=fn(stage,req) if fn else response('本页介绍边缘节点。' if stage=='vision' else json.dumps(checks(),ensure_ascii=False) if stage=='teaching' else '边缘节点内存至少128GB。网络延迟低于10ms。')
        if isinstance(result,httpx.Response):return result
        return httpx.Response(200,json=result,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx.Client,'post',post)
    monkeypatch.setattr(svc.stop,'wait',lambda seconds:False)
    return sent


@pytest.mark.parametrize('n,expected',[('10','十'),('101','一百零一'),('1001','一千零一'),('10000','一万'),('10001','一万零一'),('128','一百二十八'),('1.05','一点零五'),('001','零零一')])
def test_numbers(n,expected):assert number(n)==expected


def test_local_reading_units_arrays_citations_formulas_and_pause():
    text='内存≥128GB，容量1TB，延迟<10ms，提升10–20%。区间[0,1]，数组[1,2,3]，引用[1]。{{pause:1.5}}E=mc²。'
    result=derive(text)
    assert result['display_text']==text.replace('{{pause:1.5}}','')
    assert all(x in result['reading_text'] for x in ['大于等于一百二十八吉字节','一太字节','小于十毫秒','百分之十到百分之二十','[0,1]','[1,2,3]','[1]','E=mc²'])
    assert result['reading_text'][result['control_events'][0]['offset']:].startswith('E=mc²')
    assert ''.join(p['reading'] for p in result['sentence_pairs'])==result['reading_text']
    assert result['pending'] and len(result['replacements'])==4


def test_terms_are_applied_once_and_whitespace_is_preserved():
    result=derive('甲。\n\n乙。\n',{'甲':'乙','乙':'丙'})
    assert result['reading_text']=='乙。\n\n丙。\n'
    assert all(x['reading'] in {'乙','丙'} for x in result['replacements'])


@pytest.mark.parametrize('text,finish',[('{"display_text":"正文"}','stop'),('gan xie','stop'),('完整正文。','length'),('分析过程：重新输出。','stop'),('','stop'),(chr(96)*3+'讲稿'+chr(96)*3,'stop')])
def test_bad_bodies_never_become_narration(text,finish):
    with pytest.raises(DraftFormatError):validate_prose(response(text,finish))


def test_literal_quotes_newlines_and_brackets_need_no_json_escaping():
    text='“区间[0,1]”保持原意。\n第二句含"引号"。'
    assert validate_prose(response(text))==text
    assert derive(text)['display_text']==text


def test_new_pipeline_uses_plain_body_and_local_pairs(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service;sent=setup_provider(svc,monkeypatch)
    svc.queue_ai(p['id'],p['revision']);svc.execute(svc.store.claim())
    job=svc.store.jobs(p['id'])[0];v=current(svc.store.get(p['id'])['scenes'][0])
    assert job['state']=='completed' and v['teaching_check_state']=='completed'
    assert v['display_text']=='边缘节点内存至少128GB。网络延迟低于10ms。'
    assert v['reading_text']=='边缘节点内存至少一百二十八吉字节。网络延迟低于十毫秒。'
    assert len(sent)==3 and sent[1]['response_format']=={'type':'text'}
    assert 'sentence_pairs' not in sent[1]['messages'][0]['content']
    assert sent[2]['response_format']=={'type':'json_object'}
    assert v['checks']['questions'][0]['source_page_id']==p['slides'][0]['source_page_id']
    assert v['teacher_review'] is None


def test_check_failure_only_retry_keeps_saved_body(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service
    def fail(stage,req):
        return response('{bad') if stage=='teaching' else response('边缘节点降低延迟。')
    sent=setup_provider(svc,monkeypatch,fail)
    svc.queue_ai(p['id'],p['revision']);svc.execute(svc.store.claim())
    p=svc.store.get(p['id']);v=current(p['scenes'][0]);old=fingerprint(v)
    assert v['teaching_check_state']=='pending' and len(sent)==5
    assert svc.store.jobs(p['id'])[0]['result']['teaching_check_state']=='pending'
    with pytest.raises(Failure,match='教学核查'):review(p['scenes'][0],{k:v['checks'][k] for k in ('knowledge_points','questions','terms','pending')},'核对')
    sent=setup_provider(svc,monkeypatch)
    r=client.post(f"/api/projects/{p['id']}/scenes/{p['scenes'][0]['id']}/teaching-check",json={'revision':p['revision']})
    assert r.status_code==200
    svc.execute(svc.store.claim())
    p=svc.store.get(p['id']);new=current(p['scenes'][0])
    assert len(sent)==1 and new['display_text']==v['display_text'] and new['reading_text']==v['reading_text']
    assert new['teaching_check_state']=='completed'
    assert fingerprint(next(x for x in p['scenes'][0]['versions'] if x['id']==v['id']))==old


def test_saved_body_resume_after_derived_stage_crash(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service;sent=setup_provider(svc,monkeypatch)
    svc.queue_ai(p['id'],p['revision']);job=svc.store.claim()
    import mooc_m2.draft_pipeline as module
    original=module.derive
    monkeypatch.setattr(module,'derive',lambda *a: (_ for _ in ()).throw(Failure('WORKER_INTERRUPTED','重启注入')))
    svc.execute(job)
    assert len(sent)==2
    run=svc.drafts.get_run(job);body_hash=run['stages']['narration']['output_sha256']
    monkeypatch.setattr(module,'derive',original)
    from mooc_m2.service import Service
    reopened=Service(svc.config,svc.base)
    job['state']='running';reopened.execute(job)
    assert len(sent)==3 and reopened.drafts.get_run(job)['stages']['narration']['output_sha256']==body_hash
    assert current(reopened.store.get(p['id'])['scenes'][0])['teaching_check_state']=='completed'


def test_protected_manual_and_stale_source_never_overwritten(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service
    p=cmd(client,p,'script',{'scene_id':p['scenes'][0]['id'],'display_text':'教师人工原稿。'})
    old=current(p['scenes'][0]);setup_provider(svc,monkeypatch)
    svc.queue_ai(p['id'],p['revision']);svc.execute(svc.store.claim())
    s=svc.store.get(p['id'])['scenes'][0]
    assert current(s)==old and s['ai_candidate'] and len(s['versions'])==3


def test_course_continues_other_pages_and_retry_only_missing_stage(rig,monkeypatch):
    svc,p,_,client,_=rig
    with svc.store.edit(p['id']) as edited:
        for s in edited['scenes']:s['versions']=[];s['current_version']=None
    count=0
    def fail(stage,req):
        nonlocal count
        if stage=='vision':
            count+=1
            if count<=3:return response('只有拼音吗',finish='length')
        return response(json.dumps(checks(),ensure_ascii=False) if stage=='teaching' else '本页介绍边缘计算。')
    setup_provider(svc,monkeypatch,fail)
    url=f"/api/projects/{p['id']}";jid=client.post(url+'/generate').json()['id'];execute(rig)
    state=client.get(url+'/generation').json()
    assert state['state']=='failed' and state['scripts_ready']==2 and len(state['page_failures'])==1
    assert state['media'] is None
    saved=[current(s) for s in svc.store.get(p['id'])['scenes'][1:]]
    client.post(url+f'/generation/{jid}/retry');execute(rig)
    assert client.get(url+'/generation').json()['scripts_ready']==3
    assert [current(s) for s in svc.store.get(p['id'])['scenes'][1:]]==saved


def test_text_whitelist_cannot_enable_paid_variants(app,client):
    svc=app.state.service
    ai={'base_url':'https://open.bigmodel.cn/api/paas/v4','model':'glm-4.1v-thinking-flash','allow_external':True,'api_key_env':'','pipeline':{'enabled':True,'text_model':'glm-4.7-flashx'}}
    with pytest.raises(Failure):svc.drafts.health(settings(ai))


def test_checks_cannot_claim_another_page():
    with pytest.raises(DraftFormatError):validate_checks(response(json.dumps(checks('invented'))),{'source_page_ids':['p']},'lecture')


def test_copy_pending_body_can_retry_only_checks(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service
    setup_provider(svc,monkeypatch,lambda stage,req:response('{bad' if stage=='teaching' else '边缘计算降低延迟。'))
    svc.queue_ai(p['id'],p['revision']);svc.execute(svc.store.claim())
    clone=client.post(f"/api/projects/{p['id']}/copy").json()
    body=current(clone['scenes'][0])
    sent=setup_provider(svc,monkeypatch)
    result=client.post(f"/api/projects/{clone['id']}/scenes/{clone['scenes'][0]['id']}/teaching-check",json={'revision':clone['revision']})
    assert result.status_code==200
    svc.execute(svc.store.claim())
    v=current(svc.store.get(clone['id'])['scenes'][0])
    assert v['display_text']==body['display_text'] and len(sent)==1
    assert v['teaching_check_state']=='completed'
    assert current(svc.store.get(p['id'])['scenes'][0])==body


def test_actual_process_exit_after_body_recovers_same_saved_text(app,client):
    import subprocess,sys,threading,time
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    sent=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            req=json.loads(self.rfile.read(int(self.headers['content-length'])))
            sent.append(req)
            stage='vision' if req['model']=='vision-test' else 'teaching' if req['response_format']['type']=='json_object' else 'narration'
            out=response(json.dumps(checks(),ensure_ascii=False) if stage=='teaching' else '本页用边缘节点降低延迟。')
            data=json.dumps(out,ensure_ascii=False).encode()
            self.send_response(200);self.send_header('content-type','application/json');self.send_header('content-length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    svc=app.state.service;p=seed(app,1)
    Image.new('RGB',(20,20)).save(svc.store.file(p['id'],'missing.png'))
    svc.config['ai']={'base_url':f'http://127.0.0.1:{server.server_port}','model':'vision-test','api_key_env':'',
                     'pipeline':{'enabled':True,'text_model':'text-test'}}
    cfg=svc.store.root/'test-config.json';cfg.write_text(json.dumps(svc.config),encoding='utf-8')
    j=svc.queue_ai(p['id'],p['revision'])['jobs'][0]
    script="""
import sys,json,os
from pathlib import Path
from mooc_m2.service import Service
import mooc_m2.draft_pipeline as module
s=Service(json.loads(Path(sys.argv[1]).read_text()))
module.derive=lambda *a:os._exit(9)
s.execute(s.store.claim())
"""
    try:
        child=subprocess.run([sys.executable,'-c',script,str(cfg)],capture_output=True,timeout=45)
        assert child.returncode==9 and len(sent)==2
        with svc.store.connection() as db:
            before=json.loads(db.execute('select data from draft_runs').fetchone()[0])
        digest_before=before['stages']['narration']['output_sha256']
        svc.start()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and svc.store.jobs(p['id'])[0]['state']!='completed':time.sleep(.1)
        job=svc.store.jobs(p['id'])[0]
        assert job['id']==j['id'] and job['state']=='completed' and len(sent)==3
        assert svc.drafts.get_run(job)['stages']['narration']['output_sha256']==digest_before
        assert current(svc.store.get(p['id'])['scenes'][0])['teacher_review'] is None
    finally:
        svc.close();server.shutdown();server.server_close()


def test_rate_wait_is_durable_and_retry_budget_shared(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service
    statuses=[429,200,200,200]
    def reply(stage,req):
        status=statuses.pop(0)
        if status==429:return httpx.Response(429,json={'error':{'code':'1305'}},request=httpx.Request('POST','http://localhost'))
        return response(json.dumps(checks(),ensure_ascii=False) if stage=='teaching' else '边缘计算降低延迟。')
    sent=setup_provider(svc,monkeypatch,reply)
    original=svc.phase
    def stop_on_wait(job,phase):
        original(job,phase)
        if phase=='waiting_ai_rate_limit':svc.stop.set()
    monkeypatch.setattr(svc,'phase',stop_on_wait)
    svc.queue_ai(p['id'],p['revision']);job=svc.store.claim();svc.execute(job)
    run=svc.drafts.get_run(job)
    assert job['error']['code']=='WORKER_INTERRUPTED'
    assert run['stages']['vision']['next_retry_at'] and len(sent)==1
    svc.stop.clear();monkeypatch.setattr(svc,'phase',original)
    waits=[];monkeypatch.setattr(svc.stop,'wait',lambda seconds:waits.append(seconds) or False)
    svc.execute(job)
    assert waits and 0<waits[0]<=60 and len(sent)==4
    assert current(svc.store.get(p['id'])['scenes'][0])


def test_saved_response_corruption_blocks_reuse_before_external_call(app,client,monkeypatch):
    p=seed(app,1);svc=app.state.service;sent=setup_provider(svc,monkeypatch)
    svc.queue_ai(p['id'],p['revision']);job=svc.store.claim();svc.execute(job)
    run=svc.drafts.get_run(job)
    path=svc.store.file(p['id'],run['stages']['vision']['response']['path'])
    path.write_text('{}',encoding='utf-8')
    # An explicit new version reuses only compatible, integrity-checked vision.
    svc.queue_ai(p['id'],svc.store.get(p['id'])['revision']);svc.execute(svc.store.claim())
    latest=svc.store.jobs(p['id'])[0]
    assert latest['error']['code']=='CACHE_CORRUPT' and len(sent)==3


@pytest.mark.parametrize('stage',['narration','reading'])
def test_teaching_retry_rejects_corrupt_saved_body_or_reading(app,client,monkeypatch,stage):
    p=seed(app,1);svc=app.state.service
    setup_provider(svc,monkeypatch,lambda name,req: response('{bad' if name=='teaching' else '边缘计算降低延迟。'))
    svc.queue_ai(p['id'],p['revision']);original=svc.store.claim();svc.execute(original)
    p=svc.store.get(p['id']);v=current(p['scenes'][0]);before=fingerprint(v)
    run=svc.drafts.get_run(original)
    run['stages'][stage]['output']='被损坏的缓存' if stage=='narration' else {}
    svc.store.save_draft_run(run)
    sent=setup_provider(svc,monkeypatch)
    svc.queue_teaching(p['id'],p['scenes'][0]['id'],p['revision']);job=svc.store.claim();svc.execute(job)
    assert job['error']['code']=='CACHE_CORRUPT' and not sent
    assert fingerprint(current(svc.store.get(p['id'])['scenes'][0]))==before


def test_local_pairs_attach_closing_punctuation_without_deleting_content():
    text='示例（公式[1,2,3]的说明。)'
    d=derive(text)
    assert ''.join(p['display'] for p in d['sentence_pairs'])==text
    assert d['sentence_pairs'][-1]['display'].endswith('。)')
    assert all(p['reading'] not in {')','。)'} for p in d['sentence_pairs'])
