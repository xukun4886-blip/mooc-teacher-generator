"""Independent long-media validation via external scripts, not an AI fallback.

Original AI failure projects and all source projects remain untouched.
"""
import copy
import shutil
from pathlib import Path
import httpx
from mooc_m1.core import read_json, write_json, stamp, digest
from mooc_m2.content import import_scripts, fingerprint
from mooc_m2.store import Store

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/M3/external-long-courses.json'
TEXTS = [
    '这一页进入无线蜂窝网的学习。我们先观察原图中的网络覆盖层次。不同网络面向不同的接入范围，理解范围和连接方式，是比较无线接入技术的起点。',
    '本课围绕无线接入技术展开，包含无线局域网和无线蜂窝网。学习时先分清应用场景，再比较资源分配方式，最后把多址技术与网络演进联系起来。',
    '请结合这一页的原图观察蜂窝网络结构。蜂窝网络把服务区域划分为小区，通过基站连接终端。比较结构时，需要同时关注无线接入和后续网络连接。',
    '这一页比较电路交换和分组交换。电路交换在通话期间占用连接，分组交换把数据分成包传输。网络演进让语音和数据业务能够在统一的网络中协同提供。',
    '时分多址按时间分配信道。每个用户在自己的时隙发送和接收数据，其他时隙等待。多个用户共享同一信道，但使用时间不同，关键是时隙安排与同步。',
    '频分多址按频率划分资源。用户使用各自的频率信道，可以同时通信。与时分多址相比，它主要分开频率而不是时间，理解这一差别可以帮助比较两种方式。',
    '码分多址给不同用户分配不同的扩频码。发送端用码扩展信号，接收端用相应的码提取目标信息。因此用户可以共享时间和频率，接收端利用码来区分信号。',
    '本页展示正交扩频码。请沿原图观察码的扩展和组合关系，并比较各组码。学习重点是不同码之间的区分关系，而不是只记住符号；具体码值需要结合原图核对。',
    '这一页汇总无线局域网标准的演进。比较时按工作频段、接入机制、带宽和速率逐列观察。不同列描述不同指标，不能把频段等同于带宽，具体数值应以核查后的课件为准。',
    '本页讨论带宽与传输速率的关系。结合原图和公式观察，信道容量不仅与带宽有关，也受信噪比影响。回顾本课时，应把网络场景、资源划分与容量条件连成完整的理解。'
]


def main():
    store = Store(ROOT / 'storage/m2')
    if OUT.exists():
        raise RuntimeError('External validation projects already exist; retain and inspect them')
    source = read_json(ROOT / 'docs/evidence/M3/long-course-validation.json')
    result = {'created_at': stamp(), 'scope': '10-page external-script real media preacceptance; never counts as fresh AI success or teacher review',
              'teacher_confirmation_submitted': False, 'metrics_frozen': False, 'paths': {},
              'source_project_id': source['source_project_id'], 'source_digest_before': source['source_digest_before']}
    with httpx.Client(base_url='http://127.0.0.1:8765', trust_env=False, timeout=60) as c:
        c.post('/api/session', json={'token': store.token}).raise_for_status()
        for mode in ['photo', 'video']:
            original_id = source['paths'][mode]['project_id']
            original = store.get(original_id)
            new = c.post('/api/projects', json={'name': '十页媒体预验收 · 外部稿 · ' + mode,
                'config': {'mode': mode, 'resolution': '1080p', 'layout': 'sidebar', 'target_seconds': 18}})
            new.raise_for_status()
            pid = new.json()['id']
            assets, slides, scenes = (copy.deepcopy(original[k]) for k in ['assets', 'slides', 'scenes'])
            files = set()
            for a in assets.values():
                files.update([a['original'], a['selected']])
            for s in slides:
                files.update([s['image'], s['source_xml']])
            for relative in files:
                target = store.file(pid, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(store.file(original_id, relative), target)
            pages = [{'source_page_id': slide['source_page_id'], 'display_text': TEXTS[i], 'reading_text': TEXTS[i]} for i, slide in enumerate(slides)]
            external = {'schema_version': 'm2.scripts.v1', 'pages': pages}
            external_path = store.file(pid, 'external-preacceptance-scripts.json')
            write_json(external_path, external)
            with store.edit(pid) as p:
                p.update(assets=assets, slides=slides, scenes=scenes, engineering_only=True, category='development', source_project_id=original_id)
                for s in p['scenes']:
                    s.update(versions=[], current_version=None, confirmed=None, audition=None, preview_audition=None)
                import_scripts(p, external)
            response = c.post(f'/api/projects/{pid}/generate')
            response.raise_for_status()
            result['paths'][mode] = {'project_id': pid, 'course_job_id': response.json()['id'], 'source_project_id': original_id,
                 'source_digest_before': fingerprint(original), 'script_sha256': digest(external_path), 'script_file': str(external_path),
                 'total_characters': sum(len(t) for t in TEXTS), 'source_original_pages': list(range(5, 15)), 'status': response.json()}
            write_json(OUT, result)
            print(mode, pid, response.json()['id'], flush=True)


if __name__ == '__main__':
    main()
