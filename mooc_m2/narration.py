"""Deterministic, inspectable pronunciation derived from a single narration body."""
import re
from .content import speech

READING_CONTRACT = 'local-reading-v1'
DIGITS = '零一二三四五六七八九'
UNITS = {'GB': '吉字节', 'TB': '太字节', 'MB': '兆字节', 'KB': '千字节',
         'GiB': '吉比字节', 'MiB': '兆比字节', 'GHz': '吉赫兹', 'MHz': '兆赫兹',
         'kHz': '千赫兹', 'Hz': '赫兹', 'Gbps': '吉比特每秒', 'Mbps': '兆比特每秒',
         'ms': '毫秒', 's': '秒', 'kg': '千克', 'cm': '厘米', 'mm': '毫米'}
LETTERS = dict(zip('ABCDEFGHIJKLMNOPQRSTUVWXYZ', ['诶','比','西','迪','伊','艾弗','吉','艾尺','艾','杰','开','艾勒','艾姆','恩','欧','皮','丘','阿尔','艾斯','提','优','维','达布流','艾克斯','歪','贼德']))
ABBREVIATIONS = {'CPU', 'GPU', 'NPU', 'AI', 'API', 'DRAM', 'SSD', 'MEC', 'VIM', 'NR', 'LTE', 'MIMO', 'TOF', 'RGB', 'CNN', 'CCD', 'PPT', 'TTS'}
NUMBER = r'\d+(?:\.\d+)?'


def number(value):
    if value.startswith('-'):
        return '负' + number(value[1:])
    if '.' in value:
        whole, fraction = value.split('.')
        return number(whole) + '点' + ''.join(DIGITS[int(c)] for c in fraction)
    if len(value) > 12 or (len(value) > 1 and value[0] == '0'):
        return ''.join(DIGITS[int(c)] for c in value)
    n = int(value)
    if n == 0:
        return '零'
    if n >= 10000:
        scale, label = (100000000, '亿') if n >= 100000000 else (10000, '万')
        q, r = divmod(n, scale)
        return number(str(q)) + label + (('零' if r < scale // 10 else '') + number(str(r)) if r else '')
    result, zero = '', False
    for divisor, label in [(1000, '千'), (100, '百'), (10, '十'), (1, '')]:
        q, n = divmod(n, divisor)
        if q:
            if zero:
                result += '零'; zero = False
            result += ('' if q == 1 and divisor == 10 and not result else DIGITS[q]) + label
        elif result and n:
            zero = True
    return result


def _convert(text, terms):
    # Protect mathematical brackets/references, identifiers and unrecognised
    # expressions before matching generic numbers. No general bracket cleanup.
    term_pattern = '|'.join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) or r'(?!)'
    unit_pattern = '|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
    pattern = re.compile(
        rf'(?P<term>{term_pattern})|(?P<protected>\[[^\]\n]*\]|\{{\{{pause:[^}}]+\}}\}}|'
        rf'\b\d+(?:\.\d+)?[eE][+-]?\d+\b|[A-Za-z]\w*\s*[=^]\s*[^，。；\n]+|'
        rf'\d+(?:\.\d+)?\s*[\^×÷/]\s*[^，。；\n]+|\d+[²³])|'
        rf'(?P<percent>{NUMBER}(?:\s*[-–—~～]\s*{NUMBER})?\s*%)|'
        rf'(?P<quantity>(?:>=|<=|≥|≤|<|>)?\s*{NUMBER}\s*(?:{unit_pattern}))(?![A-Za-z])|'
        rf'(?P<range>{NUMBER}\s*[-–—~～]\s*{NUMBER})(?![A-Za-z\d])|'
        rf'(?P<identifier>[A-Za-z][A-Za-z0-9_+.-]*|\d+[A-Za-z][A-Za-z0-9_.-]*)|'
        rf'(?P<number>{NUMBER})')
    result, cursor, edits, pending = '', 0, [], []
    for m in pattern.finditer(text):
        token, replacement, rule = m[0], m[0], m.lastgroup
        if rule == 'term':
            replacement = terms[token]
        elif rule == 'protected':
            if not token.startswith('{{pause:'):
                pending.append('符号或公式读法待核对：' + token)
        elif rule == 'percent':
            nums = re.findall(NUMBER, token)
            replacement = '到'.join('百分之' + number(n) for n in nums)
        elif rule == 'quantity':
            q = re.fullmatch(rf'(>=|<=|≥|≤|<|>)?\s*({NUMBER})\s*({unit_pattern})', token)
            replacement = {'>=':'大于等于','<=':'小于等于','≥':'大于等于','≤':'小于等于','<':'小于','>':'大于',None:''}[q[1]] + number(q[2]) + UNITS[q[3]]
        elif rule == 'range':
            replacement = '到'.join(number(n) for n in re.findall(NUMBER, token))
        elif rule == 'identifier':
            if token in ABBREVIATIONS:
                replacement = ''.join(LETTERS[c] for c in token)
                pending.append('英文缩写读法需试听确认：' + token)
            elif re.fullmatch(r'[3456]G', token):
                replacement = number(token[0]) + '吉'
                pending.append('移动通信缩写读法需试听确认：' + token)
            else:
                pending.append('型号或英文术语读法待核对：' + token)
        elif rule == 'number':
            replacement = number(token)
        result += text[cursor:m.start()]
        start = len(result)
        result += replacement
        if replacement != token:
            edits.append({'source_start':m.start(), 'source_end':m.end(), 'reading_start':start,
                          'reading_end':len(result), 'text':token, 'reading':replacement, 'rule':rule})
        cursor = m.end()
    return result + text[cursor:], edits, list(dict.fromkeys(pending))


def derive(display, terms=None):
    """Keep source/display literal; apply each rule once, retaining pause syntax."""
    from mooc_m3.timeline import sentences
    terms = terms or {}
    # Validate the control grammar, but preserve it in raw_reading for add_version.
    clean_display, _ = speech(display, {})
    raw_parts, pairs, replacements, pending = [], [], [], []
    offset, read_offset = 0, 0
    # Sentence boundaries come exclusively from display; rewritten decimals or
    # abbreviations cannot change the pairing or create a second narration.
    pieces = re.findall(r'[^。！？!?\n]+[。！？!?\n]*|[。！？!?\n]+', display)
    for piece in pieces:
        reading, edits, warnings = _convert(piece, terms)
        raw_parts.append(reading)
        d, _ = speech(piece, {})
        r, _ = speech(reading, {})
        if d.strip() and r.strip():
            pairs.append({'display':d, 'reading':r})
        elif pairs:  # whitespace/control-only suffixes do not create empty cues
            pairs[-1]['display'] += d; pairs[-1]['reading'] += r
        replacements.extend({**e, 'source_start':e['source_start']+offset, 'source_end':e['source_end']+offset,
                             'reading_start':e['reading_start']+read_offset, 'reading_end':e['reading_end']+read_offset} for e in edits)
        pending.extend(warnings); offset += len(piece); read_offset += len(reading)
    raw_reading = ''.join(raw_parts)
    reading, events = speech(raw_reading, {})
    # Fail on lost source bytes, never silently skip a leading/trailing span.
    if ''.join(pieces) != display:
        from .content import reject
        reject('NARRATION_MAPPING_FAILED', '讲稿句界未完整覆盖原文')
    from mooc_m3.timeline import units, coalesce_punctuation
    pairs=coalesce_punctuation(pairs)
    units({'id':'derived', 'display_text':clean_display, 'reading_text':reading}, pairs)
    return {'display_text':clean_display, 'raw_reading':raw_reading, 'reading_text':reading,
            'control_events':events, 'sentence_pairs':pairs, 'replacements':replacements,
            'pending':list(dict.fromkeys(pending)), 'contract':READING_CONTRACT}
