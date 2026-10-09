"""Evidence integrity, preacceptance coverage and pending human review pack."""
import re
import os
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.content import fingerprint
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'docs/evidence/M4'


def main():
    store = Store(ROOT / 'storage/m2')
    sources = read_json(ROOT / 'docs/evidence/M3/long-course-validation.json')
    external = read_json(ROOT / 'docs/evidence/M3/external-long-courses.json')
    fresh = read_json(ROOT / 'docs/evidence/M3/fresh-ai-validation.json')
    original = store.get(sources['source_project_id'])
    assert fingerprint(original) == sources['source_digest_before']
    assert sum(bool(s['confirmed']) for s in original['scenes']) == 0
    with store.connection() as db:
        assert db.execute('SELECT count(*) FROM snapshots WHERE project_id=?', (original['id'],)).fetchone()[0] == 0
    review_guards = {}
    for entry in list(sources['paths'].values()) + list(external['paths'].values()) + list(fresh['paths'].values()):
        pid = entry['project_id']
        project = store.get(pid)
        assert not any(s['confirmed'] for s in project['scenes'])
        with store.connection() as db:
            snapshots = db.execute('SELECT count(*) FROM snapshots WHERE project_id=?', (pid,)).fetchone()[0]
            approvals = db.execute("SELECT count(*) FROM m3_reviews WHERE key IN (SELECT 'course:' || id FROM jobs WHERE project_id=?)", (pid,)).fetchone()[0]
        assert snapshots == approvals == 0
        review_guards[pid] = {'confirmed_scenes': 0, 'formal_snapshots': snapshots, 'course_confirmations': approvals}
    files = [ROOT / 'README.md', ROOT / 'AGENTS.md'] + list((ROOT / 'specs').glob('*.md')) + list((ROOT / 'docs').rglob('*.md')) + list((ROOT / '.agents/skills').glob('*/SKILL.md'))
    links, errors = 0, []
    for path in files:
        text = path.read_text(encoding='utf-8-sig')
        if '\ufffd' in text:
            errors.append(str(path.relative_to(ROOT)))
        for match in re.finditer(r'\[[^\]\n]*\]\(([^\)]+)\)', text):
            target = match.group(1).strip().strip('<>')
            if target.startswith(('http:', 'https:', '#', 'mailto:', 'codex:')):
                continue
            links += 1
            if not (path.parent / unquote(target.split('#')[0])).exists():
                errors.append(f'{path.relative_to(ROOT)} -> {target}')
    state = (ROOT / 'docs/PROJECT_STATUS.md').read_text(encoding='utf-8')
    assert set(re.findall(r'^\| (M[1-4]-F\d\d) \|', state, re.M)) == {f'M{i}-F{j:02d}' for i in range(1,5) for j in range(1,7)}
    tracking = (ROOT / 'specs/TRACEABILITY.md').read_text(encoding='utf-8')
    for prefix, n in [('FR',20),('NFR',8),('AC',18)]:
        assert set(re.findall(r'^\| ('+prefix+r'\d\d)\b', tracking, re.M)) == {f'{prefix}{j:02d}' for j in range(1,n+1)}
    tests = {}
    for name in ['engineering-tests.xml','targeted-final-tests.xml','lifecycle-tests.xml','repair-tests-final.xml','temp-files-final.xml','free-vision-tests.xml','free-vision-content-tests.xml','engineering-tests-final.xml','ppt-reselect-tests.xml','ppt-reselect-regression.xml']:
        suite = ET.parse(EVIDENCE / name).getroot().find('testsuite')
        assert int(suite.attrib['errors']) == int(suite.attrib['failures']) == 0
        tests[name] = {k:suite.attrib[k] for k in ['tests','failures','errors','time']}
    for name in ['lecture9-format-tests-first.xml', 'lecture9-format-regression.xml']:
        suite = ET.parse(ROOT / 'docs/evidence/M2' / name).getroot().find('testsuite')
        assert int(suite.attrib['errors']) == int(suite.attrib['failures']) == 0
        tests['M2/' + name] = {k:suite.attrib[k] for k in ['tests','failures','errors','time']}
    secrets_found = []
    candidates = [store.token]
    ai = read_json(ROOT / 'config/m2.local.json')['ai']
    if os.environ.get(ai['api_key_env']):
        candidates.append(os.environ[ai['api_key_env']])
    for folder in [EVIDENCE, ROOT / 'docs/evidence/M3', ROOT / 'docs/evidence/M2']:
        for path in folder.iterdir():
            if path.suffix in {'.json','.md','.xml'}:
                text = path.read_text(encoding='utf-8-sig')
                if any(secret in text for secret in candidates):
                    secrets_found.append(str(path.relative_to(ROOT)))
    assert not secrets_found
    descriptions = {
      'AC01':('partial','工程上传/保存/删除检查通过；原页5–14十页重新上传渲染；完整3课件数据及人工保真待补'),
      'AC02':('blocked','教师知识点、95%覆盖及关键数值/公式/待确认清零未评'),
      'AC03':('blocked','真实中文语音可解码；全部基线逐句人工核查/术语读法待评'),
      'AC04':('blocked','仅1位授权教师，5段/教师及本人+2评审独立评分未齐'),
      'AC05':('partial','两路径已有真实短课；独立十页外部稿长课结果见M3，不计正式质量通过'),
      'AC06':('blocked','每路径20个发音起点的人工逐帧/波形复核待执行'),
      'AC07':('partial','真实句段时间轴/原页切换已实现；20句人工字幕误差与重点区域待评'),
      'AC08':('partial','四类导出/摘要/解码有实测；十页成果以最终记录为准，连续播放人工评审待执行'),
      'AC09':('partial','改稿/布局局部缓存工程通过；真实生成期重启保留同任务和有效片段'),
      'AC10':('blocked','12有效任务/11首次成功及近上限长任务不足；限流和恢复分开保留'),
      'AC11':('partial','三稿源工程检查通过；十页外部稿精确映射；原4.6限流失败保留，同提供方免费4.1新上传两页复验单列，不计正式样本'),
      'AC12':('engineering_passed','区间/数组/引用原文保留，采样停顿和事件不朗读检查通过；非教学评分'),
      'AC13':('partial','3页显隐/位置/大小/布局工程及先前真实短课通过；人工无遮挡待评'),
      'AC14':('engineering_passed','缺输入/配置、正式未审核阻断；未审核草稿允许先制作；无付费回退或虚构基线'),
      'AC15':('engineering_passed','TTS/人物服务失败、可解码静音注入均失败且不提供完整成果；首次错误/恢复保留'),
      'AC16':('partial','重复提交/消息与真实子进程死亡工程通过；真实长课同任务重启，最终恢复完成见长课记录'),
      'AC17':('partial','讲稿/参考/模型/布局分层失效及后续偏移工程通过；正式全样例和质量待验证'),
      'AC18':('blocked','现有草稿问题有来源；所有基线课时教师核查与3评审评分未完成')}
    nfr = {
      'NFR01':('partial','SQLite实际重启与文件摘要；长课有效片段恢复'),
      'NFR02':('partial','单worker锁/排队/资源不足和有限重试检查；真实OOM前序记录保留，足额资源样本待补'),
      'NFR03':('partial','阶段/实际页数、模型耗时与设备/模型资源；十页同进程预热尚未验证'),
      'NFR04':('blocked','文件/静音及严格教师模式已检；教学/视听评分待评'),
      'NFR05':('partial','已有授权、身份绑定、本机会话/目录隔离、删除工程测试及证据密钥扫描；足额教师待补'),
      'NFR06':('partial','内置浏览器实际验证；独立环境pip check通过；另机重建与多个主流桌面浏览器版本待补'),
      'NFR07':('partial','版本/权重逐项核对、适配契约及配置模板；干净机器安装未验证'),
      'NFR08':('partial','任务/阶段/错误/耗时、临时文件/项目删除检查通过；日志脱敏检查覆盖本轮证据')}
    report = {'at':stamp(), 'scope':'M4 preacceptance only', 'formal_passed':False, 'metrics_frozen':False,
              'AC':{k:{'status':v[0],'finding':v[1]} for k,v in descriptions.items()},
              'NFR':{k:{'status':v[0],'finding':v[1]} for k,v in nfr.items()},
              'tests':tests, 'source_unchanged':True,'teacher_confirmations_added':0,'source_snapshot_count':0,
              'current_project_review_guards':review_guards,
              'documents':len(files),'links':links,'errors':errors,'evidence_secret_scan_findings':secrets_found,
              'external_long_courses':{k:{'project_id':v['project_id'],'state':v.get('status',{}).get('state'),
                  'duration_seconds':(v.get('status',{}).get('media') or {}).get('result',{}).get('duration_seconds') if (v.get('status',{}).get('media') or {}).get('result') else None} for k,v in external['paths'].items()},
              'input_baseline':{'authorized_teachers_available':1,'required_teachers':2,'required_decks':3,'required_valid_tasks':12,'required_near_limit_tasks':1},
              'source_docx_sha256':{p.name:digest(p) for p in ROOT.glob('*.docx')}}
    report['fresh_ai_chain'] = {mode: {'project_id': entry['project_id'], 'state': (entry.get('status') or {}).get('state'),
        'versions_before_generate': entry['versions_before_generate'], 'ai_model': fresh['ai_model'],
        'formal_baseline': False, 'error': (entry.get('status') or {}).get('error')} for mode, entry in fresh['paths'].items()}
    report['FR'] = {}
    for row in re.findall(r'^\| FR\d\d \|.*$', tracking, re.M):
        _, number, label, work, case_text, _ = row.split('|')
        cases = set(re.findall(r'AC\d\d', case_text))
        for first, last in re.findall(r'(AC\d\d)[–-](AC\d\d)', case_text):
            cases.update(f'AC{i:02d}' for i in range(int(first[2:]), int(last[2:]) + 1))
        report['FR'][number.strip()] = {'content':label.strip(), 'work_items':re.findall(r'M\d-F\d\d', work),
            'acceptance_cases':sorted(cases), 'formal_passed':False,
            'linked_preacceptance':{case: report['AC'][case] for case in sorted(cases)}}
    implementation = list((ROOT / 'mooc_m1').glob('*.py')) + list((ROOT / 'mooc_m2').glob('*.py')) + list((ROOT / 'mooc_m3').glob('*.py')) + list((ROOT / 'frontend/src').glob('*'))
    implementation += [ROOT / 'tools/m2_start.ps1', ROOT / 'tools/m2_open.py', ROOT / 'config/m4.example.json']
    implementation += list((ROOT / 'tools').glob('m4*.py')) + [ROOT / 'requirements-m1.txt', ROOT / 'requirements-m2.txt', ROOT / 'frontend/package-lock.json']
    report['implementation_sha256'] = {str(p.relative_to(ROOT)): digest(p) for p in implementation if p.is_file()}
    report['local_config_sha256'] = {str(p.relative_to(ROOT)): digest(p) for p in [ROOT / 'config/m1.local.json', ROOT / 'config/m2.local.json']}
    write_json(EVIDENCE / 'preacceptance-summary.json',report)
    assert not errors, errors
    print({'tests':tests,'documents':len(files),'links':links,'source_unchanged':True,'formal_passed':False})


if __name__ == '__main__':
    main()
