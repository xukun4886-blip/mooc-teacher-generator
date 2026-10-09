"""Provider contract/limited recovery tests, never model quality evidence."""
import copy
import json
import httpx
import pytest
from mooc_m1.core import Failure
from mooc_m2.ai_draft import parse_draft, DraftFormatError, prompt_context
from mooc_m2.content import current, fingerprint
from test_m2 import app, client, seed
from test_m2_batch_review import provider
from test_m3 import rig, execute


def draft():
    return {'display_text': '第一句。第二句。', 'reading_text': '第一句。第二句。',
            'knowledge_points': ['知识点'], 'questions': [], 'terms': [], 'pending': [], 'extensions': [],
            'sentence_pairs': [{'display': '第一句。', 'reading': '第一句。'}, {'display': '第二句。', 'reading': '第二句。'}]}


def body(value, finish='stop'):
    return {'choices': [{'finish_reason': finish, 'message': {'content': json.dumps(value, ensure_ascii=False)}}]}


@pytest.mark.parametrize('value,finish,code', [([draft(), {'pages': []}], 'stop', 'AI_OUTPUT_TOPLEVEL_INVALID'),
    (draft(), 'length', 'AI_OUTPUT_TRUNCATED'), ({'config': {}, 'pages': []}, 'stop', 'AI_OUTPUT_FIELDS_INVALID')])
def test_array_input_echo_and_truncated_json_rejected(value, finish, code):
    with pytest.raises(DraftFormatError) as exc:
        parse_draft(body(value, finish), {'id': 'scene', 'source_page_ids': ['current-source']}, True)
    assert exc.value.code == code


@pytest.mark.parametrize('succeeds', [True, False])
def test_format_repairs_are_bounded_and_original_responses_preserved(app, client, monkeypatch, succeeds):
    p = seed(app, 1)
    replies = [body([draft(), {'pages': []}]), body(draft(), 'length'), body(draft() if succeeds else [draft()])]
    def reply(req):
        return httpx.Response(200, json=replies.pop(0), request=httpx.Request('POST', 'http://localhost'))
    svc, sent = provider(app, monkeypatch, reply)
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    if succeeds:
        svc.generate_ai(j)
        stored = current(svc.store.get(p['id'])['scenes'][0])
        assert stored['display_text'] == draft()['display_text'] and stored['teacher_review'] is None
    else:
        with pytest.raises(Failure) as exc:
            svc.generate_ai(j)
        assert exc.value.code == 'AI_FORMAT_INVALID' and '第1页' in str(exc.value)
        assert not svc.store.get(p['id'])['scenes'][0]['versions']
    attempts = svc.store.jobs(p['id'])[0]['ai_attempts']
    assert len(sent) == len(attempts) == 3
    assert [a['format_retry'] for a in attempts[:2]] == [1, 2]
    assert attempts[0]['format_error'] == 'AI_OUTPUT_TOPLEVEL_INVALID'
    assert attempts[1]['format_error'] == 'AI_OUTPUT_TRUNCATED'
    for a in attempts:
        assert svc.store.file(p['id'], a['provider_record']['path']).is_file()
    assert sent[-1]['messages'][-1]['role'] == 'user'
    assert len(sent[-1]['messages']) == 3
    assert not any(m['role'] == 'assistant' for m in sent[-1]['messages'])
    assert len(sent[0]['messages'][1]['content']) == 2  # One input JSON and original page image.
    assert sent[0]['messages'][1]['content'][0]['text'].startswith('以下是课件资料')


def test_duplicate_answers_and_commentary_are_not_salvaged():
    response = body(draft())
    response['choices'][0]['message']['content'] += ' 再检查一遍。' + json.dumps(draft())
    with pytest.raises(DraftFormatError) as exc:
        parse_draft(response, {'id': 's', 'source_page_ids': ['p']}, True)
    assert exc.value.code == 'AI_OUTPUT_JSON_INVALID'
    assert '额外文字或多个答案' in str(exc.value)


def test_pinyin_retry_uses_source_and_hanzi_example_without_rejected_answer(app, client, monkeypatch):
    p = seed(app, 1)
    wrong = draft(); wrong['reading_text'] = 'di yi ju. di er ju.'
    replies = [body(wrong), body(draft())]
    svc, sent = provider(app, monkeypatch, lambda req: httpx.Response(200, json=replies.pop(0), request=httpx.Request('POST', 'http://localhost')))
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    svc.generate_ai(j)
    retry = sent[1]['messages']
    assert retry[:2] == sent[0]['messages']
    assert wrong['reading_text'] not in json.dumps(retry)
    assert '一百二十八吉字节' in retry[-1]['content']
    assert svc.store.jobs(p['id'])[0]['ai_attempts'][0]['format_error'] == 'AI_READING_INCOMPLETE'
    assert current(svc.store.get(p['id'])['scenes'][0])['reading_text'] == draft()['reading_text']


def test_format_and_rate_limit_share_four_requests(app, client, monkeypatch):
    p = seed(app, 1)
    statuses = [429, 200, 429, 200]
    def reply(req):
        status = statuses.pop(0)
        return httpx.Response(status, json=body([draft()]), request=httpx.Request('POST', 'http://localhost'))
    svc, sent = provider(app, monkeypatch, reply)
    monkeypatch.setattr(svc.stop, 'wait', lambda seconds: False)
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    with pytest.raises(Failure):
        svc.generate_ai(j)
    assert len(sent) == 4 and not svc.store.get(p['id'])['scenes'][0]['versions']
    assert all(svc.store.file(p['id'], a['provider_record']['path']).is_file() for a in svc.store.jobs(p['id'])[0]['ai_attempts'])


def test_nested_answer_is_rejected_with_exact_missing_fields():
    with pytest.raises(DraftFormatError) as exc:
        parse_draft(body({'config': {}, 'pages': [{'course_outline': [draft()]}]}), {'id': 's', 'source_page_ids': ['p']}, True)
    assert exc.value.code == 'AI_OUTPUT_FIELDS_INVALID'
    assert 'display_text' in str(exc.value) and 'extensions' in str(exc.value)


def test_short_chinese_ending_cannot_use_pinyin_reading():
    value = draft(); value.update(display_text='感谢 THANK YOU!', reading_text='gan xie Thank you!')
    with pytest.raises(DraftFormatError) as exc:
        parse_draft(body(value), {'id': 's', 'source_page_ids': ['p']}, True)
    assert exc.value.code == 'AI_READING_INCOMPLETE'


def test_english_source_ending_still_requires_mandarin_ai_narration():
    value = draft(); value.update(display_text='THANK YOU!', reading_text='Thank you!')
    with pytest.raises(DraftFormatError) as caught:
        parse_draft(body(value), {'id': 's', 'source_page_ids': ['p']}, True)
    assert caught.value.code == 'AI_READING_INCOMPLETE'


def test_layout_whitespace_identity_preserves_complete_hanzi_bodies():
    value = draft(); value.update(display_text='感 谢\nTHANK YOU!', reading_text='感 谢 THANK YOU!',
        sentence_pairs=[{'display': '感 谢\nTHANK YOU!', 'reading': 'gǎn xiè THANK YOU!'}])
    obj, meta = parse_draft(body(value), {'id': 's', 'source_page_ids': ['p']}, True)
    assert obj['display_text'] == value['display_text'] and obj['reading_text'] == value['reading_text']
    assert ''.join(u['display'] for u in obj['sentence_pairs']) == value['display_text']
    assert ''.join(u['reading'] for u in obj['sentence_pairs']) == value['reading_text']
    assert meta['pairing_method'] == 'complete_text_identical_except_whitespace'
    value['reading_text'] = '感 谢。谢谢大家。再见。'
    with pytest.raises(DraftFormatError):
        parse_draft(body(value), {'id': 's', 'source_page_ids': ['p']}, True)


def test_source_prompt_keeps_current_page_and_notes_and_bounds_outline():
    text = prompt_context({'config': {'target_seconds': 45}, 'pages': [{'source_page_id': 'p', 'body': '数组[1,2,3]。', 'notes_original': '备注原文', 'anomalies': []}], 'course_outline': [{'source_index': 1, 'body': '甲' * 1000}], 'neighbors': [{'summary': '相邻正文'}]})
    assert '数组[1,2,3]。' in text and '备注原文' in text and '相邻正文' in text
    assert '甲' * 181 not in text and text.endswith('不要返回课件资料。')


def test_vision_request_filters_unsupported_options(app, client, monkeypatch):
    p = seed(app, 1)
    svc, sent = provider(app, monkeypatch, lambda req: httpx.Response(200, json=body(draft()), request=httpx.Request('POST', 'http://localhost')))
    svc.config['ai'].update(model='glm-4.1v-thinking-flash', request_options={'max_tokens': 8000, 'response_format': {'type': 'json_object'}, 'thinking': {'type': 'disabled'}})
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    svc.generate_ai(j)
    assert sent[0]['max_tokens'] == 8000 and 'response_format' not in sent[0] and 'thinking' not in sent[0]


@pytest.mark.parametrize('provider_code,code', [('1113', 'AI_ACCOUNT_ARREARS'), ('1308', 'AI_QUOTA_EXCEEDED')])
def test_account_errors_are_evidenced_without_rate_retries(app, client, monkeypatch, provider_code, code):
    p = seed(app, 1)
    svc, sent = provider(app, monkeypatch, lambda req: httpx.Response(429, json={'error': {'code': provider_code, 'message': 'provider message'}}, request=httpx.Request('POST', 'http://localhost')))
    j = svc.store.job(p['id'], 'course', svc.ai_input(p, p['scenes'][0]))
    with pytest.raises(Failure) as exc:
        svc.generate_ai(j)
    assert exc.value.code == code and len(sent) == 1
    record = svc.store.jobs(p['id'])[0]['ai_attempts'][0]
    assert json.loads(svc.store.file(p['id'], record['provider_record']['path']).read_text())['error']['code'] == provider_code


def test_recipe_change_opens_new_bounded_run_preserving_exhausted_history(rig):
    svc, p, _, client, _ = rig
    pid = p['id']; url = f'/api/projects/{pid}'
    jid = client.post(url + '/generate').json()['id']
    j = svc.course.get(pid, jid)
    j.update(state='failed', generation=3, error={'code': 'AI_FORMAT_INVALID', 'message': '首次失败'})
    svc.store.update_job(j)
    before = copy.deepcopy(svc.store.get(pid))
    history = fingerprint(svc.course.get(pid, jid))
    assert client.get(url + '/generation').json()['retry_allowed'] is False
    assert client.post(url + f'/generation/{jid}/retry').status_code == 422
    svc.config['ai']['request_options'] = {'max_tokens': 8000}
    assert client.get(url + '/generation').json()['retry_allowed'] is True
    fresh = client.post(url + f'/generation/{jid}/retry').json()
    assert fresh['id'] != jid and fresh['generation'] == 1
    assert client.post(url + '/generate').json()['id'] == fresh['id']
    assert fingerprint(svc.course.get(pid, jid)) == history and svc.store.get(pid) == before


def test_completed_media_not_invalidated_by_draft_recipe(rig):
    svc, p, _, client, _ = rig
    url = f"/api/projects/{p['id']}"
    jid = client.post(url + '/generate').json()['id']; execute(rig); execute(rig)
    svc.config['ai']['model'] = 'changed-after-completion'
    assert client.post(url + '/generate').json()['id'] == jid
    state = client.get(url + '/generation').json()
    assert state['state'] == 'completed' and state['is_current'] and not state['teacher_confirmation']
