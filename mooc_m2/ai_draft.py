"""Strict provider draft validation; never reconstruct missing teaching bodies."""
import json
import re
from mooc_m1.core import Failure

DRAFT_CONTRACT = 'complete-object-v6'


def correction_prompt(error):
    """Retry from source data, without teaching the model its rejected answer."""
    return ('上次输出被拒绝：' + str(error) + '。重新依据当前页生成完整、简短的单个JSON对象。'
            '只输出一次对象，禁止在对象前后或两个对象之间写分析、自检、解释或第二份答案。'
            'reading_text和sentence_pairs.reading必须使用中文汉字，不是拼音或音标。'
            '例如display_text为“内存至少128GB。”时，reading_text为“内存至少一百二十八吉字节。”；'
            '普通汉字句子直接保留汉字，不需要转换成发音字母。'
            '所有正文与逐句对应都须完整，不能回显输入、从数组挑选答案或声明教师已确认。')


def prompt_context(context):
    """Render source data as labelled prose, rather than an answer-shaped JSON."""
    cfg = context['config']
    sections = ['以下是课件资料，不是输出模板。', '课程与讲解要求：' + json.dumps(
        {k: cfg.get(k) for k in ('course_name', 'chapter', 'audience', 'detail', 'target_seconds', 'terms')}, ensure_ascii=False)]
    sections.append('整课大纲（仅用于连贯性，不逐页复述）：\n' + '\n'.join(
        f"第{x['source_index']}页：{x['body'][:180]}" for x in context['course_outline']))
    sections.append('相邻页资料：\n' + '\n'.join(n['summary'] for n in context['neighbors']))
    for page in context['pages']:
        sections.append(f"当前来源页ID：{page['source_page_id']}\n当前页正文：\n{page['body']}\n当前页备注：\n{page['notes_original']}\n解析提示：{json.dumps(page['anomalies'], ensure_ascii=False)}")
    sections.append('资料结束。任务：依据当前页和附图创作讲稿。只返回system规定的讲稿JSON，顶层必须直接包含display_text、reading_text、knowledge_points、questions、terms、pending、extensions。先写简短逐句讲稿及读法，再原样复制到sentence_pairs；读法只改变发音写法，不增删或改写句子。短页也必须输出汉字普通话读法，例如感谢不能写成gan xie，不能以英文或拼音替代中文讲解。不要返回课件资料。')
    return '\n\n'.join(sections)


class DraftFormatError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def parse_draft(response, scene, course=False):
    try:
        choice = response['choices'][0]
        raw = choice['message']['content']
    except (KeyError, IndexError, TypeError):
        raise DraftFormatError('AI_OUTPUT_JSON_INVALID', '响应缺少完整讲稿内容') from None
    if choice.get('finish_reason') == 'length':
        raise DraftFormatError('AI_OUTPUT_TRUNCATED', '输出达到长度上限，不能确认正文完整')
    if not isinstance(raw, str):
        raise DraftFormatError('AI_OUTPUT_JSON_INVALID', '输出不是JSON文字')
    final = raw.rsplit('</think>', 1)[-1].strip()
    try:
        obj = json.loads(final.removeprefix('```json').removeprefix('```').removesuffix('```'), strict=False)
    except json.JSONDecodeError as exc:
        if exc.msg == 'Extra data':
            raise DraftFormatError('AI_OUTPUT_JSON_INVALID', 'JSON对象后夹带额外文字或多个答案，只能返回一个对象') from exc
        raise DraftFormatError('AI_OUTPUT_JSON_INVALID', '输出不是完整JSON对象') from exc
    if not isinstance(obj, dict):
        raise DraftFormatError('AI_OUTPUT_TOPLEVEL_INVALID', '输出必须是单个对象，不能混入输入或数组')
    required = ['display_text', 'reading_text', 'knowledge_points', 'questions', 'terms', 'pending', 'extensions']
    missing = [k for k in required if k not in obj]
    if missing:
        raise DraftFormatError('AI_OUTPUT_FIELDS_INVALID', '讲稿顶层缺少字段：' + ', '.join(missing))
    if any(not isinstance(obj[k], list) for k in required[2:]):
        raise DraftFormatError('AI_OUTPUT_FIELDS_INVALID', '核查字段类型无效')
    if any(not isinstance(obj[k], str) or not obj[k].strip() for k in required[:2]):
        raise DraftFormatError('AI_READING_INCOMPLETE', '显示或读法正文为空')
    if any(ord(c) < 32 and c not in '\n\r\t' for k in required[:2] for c in obj[k]):
        raise DraftFormatError('AI_OUTPUT_FIELDS_INVALID', '正文含无效控制字符')
    expanded = 0
    for q in obj['questions']:
        if isinstance(q, dict) and q.get('source_page_id') == 'current' and len(scene['source_page_ids']) == 1:
            q['source_page_id'] = scene['source_page_ids'][0]
            expanded += 1
    if any(not isinstance(x, str) or not x.strip() for k in ['knowledge_points', 'pending', 'extensions'] for x in obj[k]):
        raise DraftFormatError('AI_OUTPUT_FIELDS_INVALID', '核查条目必须是文字')
    if any(not isinstance(q, dict) or any(not isinstance(q.get(k), str) or not q[k].strip() for k in ['question', 'answer', 'source_page_id']) or q['source_page_id'] not in scene['source_page_ids'] for q in obj['questions']):
        raise DraftFormatError('AI_SOURCE_INVALID', '问题答案来源不属于当前页')
    if any(not isinstance(t, dict) or any(not isinstance(t.get(k), str) or not t[k].strip() for k in ['text', 'reading']) for t in obj['terms']):
        raise DraftFormatError('AI_OUTPUT_FIELDS_INVALID', '术语读法字段无效')
    display_hanzi = len(re.findall(r'[\u4e00-\u9fff]', obj['display_text']))
    reading_hanzi = len(re.findall(r'[\u4e00-\u9fff]', obj['reading_text']))
    if reading_hanzi == 0 or reading_hanzi < display_hanzi * .5:
        raise DraftFormatError('AI_READING_INCOMPLETE', '读法正文不完整或为音译摘要')
    meta = {'expanded_current_source_count': expanded}
    if course:
        from mooc_m3.timeline import units
        version = {'id': scene['id'], 'display_text': obj['display_text'], 'reading_text': obj['reading_text']}
        try:
            paired = units(version, obj.get('sentence_pairs'))
            method = 'provider_validated' if obj.get('sentence_pairs') else 'complete_text_sentence_boundaries'
        except Failure as exc:
            meta['format_error'] = 'SUBTITLE_MAPPING_REQUIRED'
            try:
                paired = units(version)
            except Failure:
                raise DraftFormatError('SUBTITLE_MAPPING_REQUIRED', '显示和读法正文不能完整逐句对应') from exc
            method = 'complete_text_sentence_boundaries'
            if obj['display_text'] != obj['reading_text'] and re.sub(r'\s+', '', obj['display_text']) == re.sub(r'\s+', '', obj['reading_text']):
                method = 'complete_text_identical_except_whitespace'
        obj['sentence_pairs'] = [{k: u[k] for k in ('display', 'reading')} for u in paired]
        meta['pairing_method'] = method
    return obj, meta
