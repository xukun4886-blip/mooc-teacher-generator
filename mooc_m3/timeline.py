from __future__ import annotations

import re
from mooc_m2.content import reject


def coalesce_punctuation(paired):
    """Attach non-spoken punctuation to an adjacent complete sentence.

    Keep every display/reading character and source offset. Bracket contents,
    formula operators, numbers and words are never classified as punctuation.
    """
    punctuation=re.compile(r'''^[\s。．.,，！？!?；;：:、()（）\[\]【】“”‘’"']+$''')
    result=[];leading=[]
    for unit in paired:
        if punctuation.fullmatch(unit['display']) and punctuation.fullmatch(unit['reading']):
            if result:
                result[-1].update(display=result[-1]['display']+unit['display'],reading=result[-1]['reading']+unit['reading'])
                if 'end_offset' in unit:result[-1]['end_offset']=unit['end_offset']
            else:leading.append(unit)
        else:
            value=dict(unit)
            if leading:
                value.update(display=''.join(u['display'] for u in leading)+value['display'],
                             reading=''.join(u['reading'] for u in leading)+value['reading'])
                if 'start_offset' in leading[0]:value['start_offset']=leading[0]['start_offset']
                leading=[]
            result.append(value)
    if not result:reject('EMPTY_SCRIPT','讲稿只有标点，不能生成真实讲解')
    return result


def sentences(text):
    return [m.group() for m in re.finditer(r'[^。！？!?\n]+[。！？!?\n]*|[。！？!?\n]+', text) if m.group().strip()]


def units(version, supplied=None):
    """Pair complete sentences, never allocate time by character counts.

    Teachers can supply explicit sentence correspondence when punctuation differs.
    No automatic word-level accuracy is claimed.
    """
    display, reading = version['display_text'], version['reading_text']
    compact = lambda s: re.sub(r'\s+', '', s)
    if supplied is None:
        a, b = sentences(display), sentences(reading)
        if compact(display) == compact(reading) and [compact(s) for s in a] != [compact(s) for s in b]:
            # Layout line breaks are not spoken sentence boundaries. Only exact
            # whole-text identity modulo whitespace permits this recovery.
            # Locate every character in both original bodies; do not invent text
            # or infer timing. TTS will measure the resulting spoken intervals.
            canonical = sentences(re.sub(r'[\r\n]+', ' ', reading))
            supplied, cursors = [], [0, 0]
            for sentence in canonical:
                spans = []
                pattern = r'\s*' + r'\s*'.join(re.escape(ch) for ch in compact(sentence))
                for i, text in enumerate((display, reading)):
                    match = re.match(pattern, text[cursors[i]:])
                    if not match:
                        reject('SUBTITLE_MAPPING_REQUIRED', '完整正文空白对应失败，不生成猜测映射')
                    end = cursors[i] + match.end()
                    spans.append(text[cursors[i]:end])
                    cursors[i] = end
                supplied.append({'display': spans[0], 'reading': spans[1]})
            if supplied:
                supplied[-1]['display'] += display[cursors[0]:]
                supplied[-1]['reading'] += reading[cursors[1]:]
        if len(a) != len(b) or not a:
            if supplied is None:
                reject('SUBTITLE_MAPPING_REQUIRED', '显示稿与读法稿句数不同，请填写逐句字幕对应', version['id'])
        if supplied is None:
            supplied = [{'display': d, 'reading': r} for d, r in zip(a, b)]
    if (not isinstance(supplied, list) or not supplied or any(not isinstance(u, dict) or
        set(u) != {'display', 'reading'} or any(not isinstance(u[k], str) or not u[k].strip() for k in u) for u in supplied)
        or compact(''.join(u['display'] for u in supplied)) != compact(display)
        or compact(''.join(u['reading'] for u in supplied)) != compact(reading)):
        reject('SUBTITLE_MAPPING_REQUIRED', '逐句对应须完整覆盖显示稿和读法稿，不能删句或增补')
    # Locate each reading sentence in the original reading text, including whitespace.
    result, cursor = [], 0
    for u in supplied:
        match = re.match(r'\s*' + r'\s*'.join(re.escape(ch) for ch in compact(u['reading'])), reading[cursor:])
        if not match:
            reject('SUBTITLE_MAPPING_REQUIRED', '读法对应顺序与原稿不同')
        end = cursor + match.end()
        result.append({**u, 'start_offset': cursor, 'end_offset': end})
        cursor = end
    result[-1]['end_offset'] = len(reading)
    return result


def speech_runs(version, paired, pause_after):
    runs, run_groups = [], []
    for i, u in enumerate(paired):
        cursor = u['start_offset']
        for event in version['control_events']:
            if cursor <= event['offset'] < u['end_offset']:
                runs.append({'text': version['reading_text'][cursor:event['offset']], 'pause_after': event['seconds']})
                run_groups.append(i)
                cursor = event['offset']
        runs.append({'text': version['reading_text'][cursor:u['end_offset']], 'pause_after': 0})
        run_groups.append(i)
    # Events exactly at EOF are deliberately preserved once.
    for event in version['control_events']:
        if event['offset'] == len(version['reading_text']):
            runs.append({'text': '', 'pause_after': event['seconds']})
            run_groups.append(len(paired) - 1)
    runs.append({'text': '', 'pause_after': pause_after})
    run_groups.append(len(paired) - 1)
    return runs, run_groups


def captions(paired, groups, measured):
    measured = [t for t in measured if 'text_sha256' in t]
    if any('segment_index' not in t or t['segment_index'] >= len(groups) for t in measured):
        reject('ALIGNMENT_FAILED', '真实语音分段时间记录不完整')
    result = []
    for i, unit in enumerate(paired):
        parts = [t for t in measured if groups[t['segment_index']] == i and t['end_seconds'] > t['start_seconds']]
        if not parts:
            reject('ALIGNMENT_FAILED', '字幕对应句未生成实际语音')
        result.append({'start': parts[0]['start_seconds'], 'end': parts[-1]['end_seconds'], 'text': unit['display'].strip(),
                       'method': 'measured_sentence_synthesis', 'word_alignment_verified': False})
    return result


def clock(value):
    ms = max(0, round(value * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def srt(cues):
    return '\n'.join(f"{i}\n{clock(c['start'])} --> {clock(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1))


def course_timeline(scenes):
    pages, cues, offset = [], [], 0.0
    for scene in scenes:
        duration = scene.get('compose', {}).get('duration_seconds', scene['tts']['duration_seconds'])
        pages.append({'scene_id': scene['id'], 'source_page_ids': scene['source_page_ids'], 'play_page_id': scene['play_page_id'],
                      'start': offset, 'end': offset + duration, 'duration_seconds': duration})
        cues.extend({**c, 'start': c['start'] + offset, 'end': c['end'] + offset} for c in scene['tts']['captions'])
        offset += duration
    return pages, cues, offset
