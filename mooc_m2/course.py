"""Persistent one-click draft orchestration on the existing single SQLite worker."""
from __future__ import annotations

import json
from pathlib import Path

from mooc_m1.core import Failure, digest, run, stamp
from .content import current, effective, fingerprint, reject, uid
from .ai_draft import DRAFT_CONTRACT


class Course:
    def __init__(self, service):
        self.service, self.store = service, service.store

    def signature(self, p):
        inputs = {k: p[k] for k in ('assets', 'config', 'scenes', 'slides')}
        if p.get('photo_execution', {}).get('mode') == 'cloud' and p['config'].get('mode', 'photo') == 'photo':
            inputs['photo_execution'] = p['photo_execution']
        return fingerprint(inputs)

    def draft_recipe(self):
        ai = self.service.config.get('ai', {})
        from .draft_pipeline import settings
        return fingerprint(settings(ai) or {'contract': DRAFT_CONTRACT, **{k: ai.get(k) for k in ('model', 'base_url', 'request_options')}})

    def repaired_draft(self, job):
        return job['state'] == 'failed' and not job.get('result') and job.get('draft_recipe') != self.draft_recipe()

    def get(self, pid, jid, db=None):
        if db is None:
            with self.store.connection() as conn:
                return self.get(pid, jid, conn)
        row = db.execute('SELECT data FROM jobs WHERE id=? AND project_id=?', (jid, pid)).fetchone()
        j = json.loads(row[0]) if row else None
        if not j or j['kind'] != 'course':
            reject('NOT_FOUND', '课程制作记录不存在')
        return j

    def submit(self, pid):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            p = self.store.get(pid, db)
            for row in db.execute('SELECT data FROM jobs WHERE project_id=? ORDER BY rowid DESC', (pid,)):
                old = json.loads(row[0])
                if old['kind'] == 'course' and self.repaired_draft(old):
                    continue
                if old['kind'] == 'course' and (old['state'] in {'queued', 'running'} or old.get('signature') == self.signature(p)):
                    if old.get('result') and self.service.m3.needs_punctuation_repair(self.service.m3.get(pid,old['result']['media_job_id'],db)):
                        continue
                    if not old.get('result') or self.service.m3.get(pid, old['result']['media_job_id'], db)['state'] != 'canceled':
                        return self.public(old)
            if self.store.busy(pid, db):
                reject('PROJECT_BUSY', '素材正在处理，请稍候再生成')
            mode = effective(p, {'overrides': {}})['mode']
            for role, label in [('pptx', '课程 PPT'), ('reference_audio', '参考语音'), (mode, '教师形象')]:
                if p['assets'].get(role, {}).get('state') != 'ready':
                    reject('INPUT_MISSING', f'请上传有效的{label}')
            if not p['slides']:
                reject('INPUT_MISSING', '请先完成课件解析')
            job = {'id': uid(), 'project_id': pid, 'kind': 'course', 'payload': {}, 'state': 'queued',
                   'stage': 'queued', 'created_at': stamp(), 'generation': 1, 'result': None, 'error': None,
                   'signature': self.signature(p), 'draft_recipe': self.draft_recipe(), 'scripts_ready': 0, 'total': sum(not s['skipped'] for s in p['scenes'])}
            from .draft_pipeline import settings
            cfg=settings(self.service.config.get('ai',{}))
            if cfg:job['draft_settings']=cfg
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (job['id'], pid, 'queued', json.dumps(job, ensure_ascii=False)))
        return self.public(job)

    def public(self, job):
        result = {k: job.get(k) for k in ('id', 'project_id', 'state', 'stage', 'error', 'scripts_ready', 'total', 'generation', 'page_failures')}
        p=self.store.get(job['project_id'])
        result['teaching_pending']=sum(bool(not s['skipped'] and current(s) and current(s).get('teaching_check_state')=='pending') for s in p['scenes'])
        if job.get('error') and job['error'].get('code', '').startswith('AI_'):
            p = self.store.get(job['project_id'])
            scene = next((s for s in p['scenes'] if s['id'] == job['error'].get('source')), None)
            page = next((s['source_index'] for s in p['slides'] if scene and s['source_page_id'] in scene['source_page_ids']), None)
            if page is not None:
                result['error'] = {**job['error'], 'source_page_index': page}
                if not result['error']['message'].startswith(f'第{page}页'):
                    result['error']['message'] = f"第{page}页：" + result['error']['message']
        media_job = self.service.m3.get(job['project_id'], job['result']['media_job_id']) if job.get('result') else None
        result['media'] = self.service.m3.public(media_job) if media_job else None
        if result['media']:
            result.update(state=result['media']['state'], stage=result['media']['stage'], error=result['media']['error'])
            key = 'course:' + result['media']['id']
            result['teacher_confirmation'] = self.service.m3.review.get(key)
            result['is_current'] = self.signature(self.store.get(job['project_id'])) == job['signature']
        result['retry_allowed'] = result['state'] == 'failed' and (self.repaired_draft(job) or
            (media_job and self.service.m3.needs_punctuation_repair(media_job)) or
            (media_job or job).get('generation', 1) < 3 or
            self.signature(self.store.get(job['project_id'])) != job['signature'])
        return result

    def latest(self, pid):
        return next((self.public(j) for j in self.store.jobs(pid) if j['kind'] == 'course'), None)

    def retry(self, pid, jid):
        job = self.get(pid, jid)
        if job['signature'] != self.signature(self.store.get(pid)) or self.repaired_draft(job):
            return self.submit(pid)
        if job.get('result'):
            if self.service.m3.needs_punctuation_repair(self.service.m3.get(pid,job['result']['media_job_id'])):
                return self.submit(pid)
            self.service.m3.retry(pid, job['result']['media_job_id'])
            return self.public(job)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self.get(pid, jid, db)
            if job['state'] != 'failed' or job['generation'] >= 3 or self.store.busy(pid, db):
                reject('RETRY_BLOCKED', '请检查素材和设置后重试；每次制作最多重试两次')
            job.setdefault('attempts', []).append({'error': job['error'], 'stage': job['stage'], 'at': stamp()})
            job.update(state='queued', stage='queued', error=None, generation=job['generation'] + 1)
            db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', ('queued', json.dumps(job, ensure_ascii=False), jid))
        return self.public(job)

    def recover(self):
        with self.store.connection() as db:
            for row in db.execute("SELECT data FROM jobs WHERE state='failed'").fetchall():
                j = json.loads(row[0])
                if j['kind'] == 'course' and (j.get('error') or {}).get('code') == 'WORKER_INTERRUPTED':
                    j.update(state='queued', stage='recovering', error=None)
                    db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', ('queued', json.dumps(j, ensure_ascii=False), j['id']))

    def reference(self, job):
        pid = job['project_id']
        ref = self.store.get(pid)['assets']['reference_audio']
        if (ref.get('selection') or {}).get('transcript'):
            return
        self.service.phase(job, 'recognizing_reference')
        duration = ref['metadata']['duration_seconds']
        if duration < 3:
            reject('REFERENCE_TOO_SHORT', '参考语音不足 3 秒，请上传一段清晰、连续的中文语音')
        seconds = min(7.5, duration)
        folder = self.store.file(pid, f"assets/{ref['id']}/auto-reference.wav")
        run([self.service.media.ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', self.store.file(pid, ref['original']),
             '-t', seconds, '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', folder], 90)
        output = folder.with_suffix('.asr.json')
        python = self.service.m1.get('models', {}).get('video', {}).get('python')
        if not python or not Path(python).is_file():
            reject('ASR_UNAVAILABLE', '本地语音识别环境未就绪，请在高级设置中填写参考语音对应文字')
        run([python, self.service.base / 'tools/course_reference_asr.py', folder, output,
             self.service.base / '.tools/models/MuseTalk/models/whisper'], 180)
        record = json.loads(output.read_text(encoding='utf-8'))
        if not record['text'].strip():
            reject('REFERENCE_UNCLEAR', '未识别到中文语音，请更换清晰语音或在高级设置中修正文字')
        md = self.service.media.inspect(folder, 'audio')
        with self.store.edit(pid) as p:
            a = p['assets']['reference_audio']
            if a['id'] != ref['id']:
                reject('REVISION_CONFLICT', '参考语音已更换，请重新生成')
            a.update(selected=str(folder.relative_to(self.store.folder(pid))).replace('\\', '/'), selected_sha256=digest(folder),
                     selected_metadata=md, selection={'start': 0, 'end': seconds, 'transcript': record['text'],
                     'method': 'local_whisper_tiny', 'human_review': False, 'record_sha256': digest(output)})

    def execute(self, job):
        pid = job['project_id']
        job['scripts_ready'] = 0
        try:
            self.reference(job)
            p = self.store.get(pid)
            if effective(p, {'overrides': {}})['mode'] == 'video':
                a = p['assets']['video']
                duration = a['metadata']['duration_seconds']
                if duration < 5:
                    reject('VIDEO_TOO_SHORT', '教师视频不足 5 秒，请上传 5 秒以上的清晰人物视频')
                if duration > 60 and not a.get('selection'):
                    self.service.phase(job, 'preparing_teacher_video')
                    job['payload'] = {'role': 'video', 'asset_id': a['id'], 'selection': {'start': 0, 'end': 60, 'method': 'automatic_first_60_seconds'}}
                    self.service.derive(job)
                    job['payload'] = {}
                    p = self.store.get(pid)
            active = [s for s in p['scenes'] if not s['skipped']]
            job['page_failures']=[]
            for scene in active:
                if self.service.stop.is_set():
                    reject('WORKER_INTERRUPTED', '服务停止，制作将在重启后恢复')
                task=job.get('page_tasks',{}).get(scene['id'])
                resume_checks=False
                if task and current(scene) and current(scene).get('teaching_check_state')=='pending':
                    run=self.service.drafts.get_run({'project_id':pid,'payload':task})
                    resume_checks=run['stages'].get('teaching',{}).get('state')!='failed'
                if not current(scene) or resume_checks:
                    # New runs pin their recipe; old in-flight jobs retain the legacy contract.
                    if job.get('draft_settings'):
                        task=job.setdefault('page_tasks',{}).get(scene['id'])
                        if task is None:
                            task=self.service.ai_input(self.store.get(pid),scene,staged=False)
                            task['draft_settings']=job['draft_settings']
                            job['page_tasks'][scene['id']]=task
                        job['payload']=task
                        self.store.update_job(job)
                        try:self.service.generate_ai(job)
                        except Failure as exc:
                            if exc.code in {'WORKER_INTERRUPTED','REVISION_CONFLICT'}:raise
                            job['page_failures'].append({'scene_id':scene['id'],'error':exc.record()})
                            self.service.phase(job,'preparing_narration')
                            continue
                    else:
                        job['payload'] = self.service.ai_input(self.store.get(pid), scene,staged=False)
                        self.service.generate_ai(job)
                job['scripts_ready'] += 1
                self.service.phase(job, 'preparing_narration')
            if job['page_failures']:
                first=job['page_failures'][0]
                reject('AI_PAGES_INCOMPLETE',f"{len(job['page_failures'])}页讲稿未完成，其他已完成页面均已保存",first['scene_id'],'重试只处理缺失页及失败步骤')
            job['payload'] = {}
            self.service.phase(job, 'preparing_video')
            p = self.store.get(pid)
            mappings = {s['id']: current(s)['provenance']['sentence_pairs'] for s in p['scenes']
                        if not s['skipped'] and current(s)['provenance'].get('sentence_pairs')}
            media = self.service.m3.submit(pid, {'preview': True, 'revision': p['revision'], 'subtitle_units': mappings})
            job.update(state='completed', stage='video_queued', result={'media_job_id': media['id']},
                       signature=self.signature(p), error=None, finished_at=stamp())
        except Exception as exc:
            job.update(state='failed', error=exc.record() if isinstance(exc, Failure) else
                       {'code': 'RUN_FAILED', 'message': '课程制作失败，请检查素材后重试'}, finished_at=stamp(),
                       signature=self.signature(self.store.get(pid)))
        self.store.update_job(job)

    def confirm(self, pid, jid, body):
        job = self.get(pid, jid)
        if not job.get('result'):
            reject('REVIEW_REQUIRED', '请等待视频完成并观看后确认')
        media = self.service.m3.get(pid, job['result']['media_job_id'])
        if media['state'] != 'completed' or body.get('confirmed') is not True:
            reject('REVIEW_REQUIRED', '请观看完整成片后由教师主动确认')
        self.service.m3.verify(pid, media['result']['path'], media['result']['sha256'])
        if self.signature(self.store.get(pid)) != job['signature']:
            reject('REVISION_CONFLICT', '内容已修改，请生成新视频后确认')
        record = {'project_id': pid, 'job_id': media['id'], 'sha256': media['result']['sha256'],
                  'input_key': media['payload']['input_key'], 'reviewer': 'local-teacher', 'at': stamp(),
                  'decision': 'teacher_confirmed_preview', 'note': str(body.get('note', '教师观看成片后确认'))[:2000],
                  'formal_acceptance': False}
        self.service.m3.review.put('course:' + media['id'], record)
        return record
