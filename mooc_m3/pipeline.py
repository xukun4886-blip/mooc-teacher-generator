from __future__ import annotations

import copy
import json
import os
import shutil
import time
from pathlib import Path

from mooc_m1.adapters import LocalModelAdapter
from mooc_m1.core import Failure, digest, stamp, write_json
from mooc_m2.content import current, effective, fingerprint, reject, uid, check_mapping
from .review import Review
from .timeline import units, speech_runs, captions, course_timeline, srt, coalesce_punctuation
from .render import compose, join


class Pipeline:
    """Uses the M2 SQLite job queue and its sole worker (including GPU auditions).

    Stage publication is fenced by an execution token and cancel state. Cache
    objects are private to their project and contain verified media, not filenames.
    """
    def __init__(self, service):
        self.service, self.store, self.media = service, service.store, service.media
        self.review = Review(service)
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS m3_cache(project_id TEXT, layer TEXT, key TEXT, data TEXT, PRIMARY KEY(project_id,layer,key))')

    def get(self, pid, jid, db=None):
        if db is None:
            with self.store.connection() as conn:
                return self.get(pid, jid, conn)
        row = db.execute('SELECT data FROM jobs WHERE id=? AND project_id=?', (jid, pid)).fetchone()
        value = json.loads(row[0]) if row else None
        if not value or value['kind'] != 'm3':
            reject('NOT_FOUND', '媒体任务不存在')
        return value

    def save(self, job, final=False):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            live = self.get(job['project_id'], job['id'], db)
            if live.get('execution') != job.get('execution') or live['state'] != 'running':
                reject('STALE_EXECUTION', '旧工作进程结果不能覆盖当前任务')
            if live.get('cancel_requested'):
                reject('CANCELED', '已请求取消；当前模型到达可中断点后停止')
            job['updated_at'] = stamp()
            job['elapsed_seconds'] = job.get('elapsed_before_execution', 0) + time.perf_counter() - job['_started']
            db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (job['state'], json.dumps({k: v for k, v in job.items() if k != '_started'}, ensure_ascii=False), job['id']))

    def boundary(self, job):
        live = self.get(job['project_id'], job['id'])
        if live.get('execution') != job.get('execution') or live['state'] != 'running':
            reject('STALE_EXECUTION', '任务执行代次已失效')
        if live.get('cancel_requested'):
            reject('CANCELED', '任务取消，当前模型完成后停止，不生成下一片段')
        if time.perf_counter() - job['_started'] > job['payload']['timeout_seconds']:
            reject('TIMEOUT', '任务超过配置时限，可重试失败片段')
        if self.service.stop.is_set():
            reject('WORKER_INTERRUPTED', '工作进程停止，将从已验证阶段恢复')

    def cancel(self, pid, jid):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self.get(pid, jid, db)
            if job['state'] in {'queued', 'running'}:
                job['cancel_requested'] = True
                if job['state'] == 'queued':
                    job.update(state='canceled', stage='canceled', finished_at=stamp())
                db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (job['state'], json.dumps(job, ensure_ascii=False), jid))
        return self.public(job)

    def retry(self, pid, jid):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self.get(pid, jid, db)
            if job['state'] != 'failed' or job['generation'] >= 3:
                reject('RETRY_BLOCKED', '仅失败任务可重试，最多三代执行；取消任务需明确新建')
            job.setdefault('attempts', []).append({'generation': job['generation'], 'error': job['error'], 'stage': job['stage'], 'finished_at': job.get('finished_at')})
            job['elapsed_before_execution'] = job.get('elapsed_seconds', 0)
            job.update(state='queued', stage='queued', generation=job['generation'] + 1, execution=None, error=None)
            for scene in job['scenes']:
                if scene['state'] == 'failed':
                    scene.update(state='pending', error=None)
            db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', ('queued', json.dumps(job, ensure_ascii=False), jid))
        return self.public(job)

    def recover(self):
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute("SELECT data FROM jobs WHERE state='running'").fetchall():
                job = json.loads(row[0])
                if job['kind'] != 'm3':
                    continue
                self.cleanup_unpublished(job['project_id'])
                job['execution'] = None
                job['elapsed_before_execution'] = job.get('elapsed_seconds', 0)
                job.setdefault('recovery_history', []).append({'at': stamp(), 'stage': job['stage'], 'last_checkpoint_elapsed_seconds': job.get('elapsed_seconds'),
                    'scope': 'elapsed time after the last checkpoint before abrupt death is unavailable'})
                job['recoveries'] = job.get('recoveries', 0) + 1
                if job.get('cancel_requested'):
                    job.update(state='canceled', stage='canceled', finished_at=stamp())
                elif job['recoveries'] > 3:
                    job.update(state='failed', error={'code': 'RECOVERY_LIMIT', 'message': '三次恢复仍中断，请检查工作进程'}, finished_at=stamp())
                else:
                    job.update(state='queued', stage='recovering_validated_stages')
                db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (job['state'], json.dumps(job, ensure_ascii=False), job['id']))

    def cleanup_unpublished(self, pid):
        """Remove only unpublished media inside this project's managed M3 paths.

        Crash evidence and all published cache/results remain available. Validate
        each resolved path through Store before unlinking; never follow reparses.
        """
        for relative_root in ['m3/cache', 'm3/jobs']:
            folder = self.store.file(pid, relative_root)
            if not folder.exists():
                continue
            for path in folder.rglob('*'):
                if path.name not in {'publishing.mp4', 'publishing-course.mp4', 'audio.tmp', 'portrait.tmp', 'manifest.json.tmp'}:
                    continue
                safe = self.store.file(pid, str(path.relative_to(self.store.folder(pid))))
                if safe.is_file():
                    safe.unlink()

    def snapshot_list(self, pid):
        self.store.get(pid)
        with self.store.connection() as db:
            return [{'id': p['snapshot_id'], 'revision': p['revision'], 'frozen_at': p['frozen_at']}
                    for p in [json.loads(r[0]) for r in db.execute('SELECT data FROM snapshots WHERE project_id=? ORDER BY rowid DESC', (pid,))]]

    def prepare(self, pid, body):
        if set(body) - {'preview', 'revision', 'snapshot_id', 'scene_ids', 'mode', 'subtitle_units'}:
            reject('INPUT_INCOMPATIBLE', '媒体提交字段不支持；配置变更请在 M2 保存并重新审核')
        preview = body.get('preview') is True
        if preview:
            p = self.store.get(pid)
            if body.get('revision') != p['revision']:
                reject('REVISION_CONFLICT', '请刷新项目后生成草稿预览')
            p = copy.deepcopy(p)
            p.update(snapshot_id='draft:' + fingerprint(p), schema_version='m3.draft.v1')
        else:
            if not isinstance(body.get('snapshot_id'), str):
                reject('SNAPSHOT_REQUIRED', '正式任务必须选择 M2 不可变审核快照')
            p = self.store.get_snapshot(pid, body['snapshot_id'])
            if p.get('engineering_only') or not p.get('preflight', {}).get('ready'):
                reject('REVIEW_REQUIRED', '工程内容或未通过内容预检不能正式生成')
            if not self.review.ready(p):
                reject('M1_REVIEW_REQUIRED', '请先完成当前素材和模型的 M1 人工评审')
        check_mapping(p)
        config = effective(p, {'overrides': {}})
        mode = config['mode']
        # Changing teacher mode is an M2 config operation with an audit trail.
        # Preview may test either real path without mutating project configuration.
        if preview and body.get('mode') in {'photo', 'video'}:
            mode = body['mode']
        scene_ids = body.get('scene_ids')
        active = [s for s in p['scenes'] if not s['skipped']]
        if scene_ids is not None:
            if not isinstance(scene_ids, list) or not scene_ids or len(scene_ids) != len(set(scene_ids)) or set(scene_ids) - {s['id'] for s in active}:
                reject('INPUT_INCOMPATIBLE', '样片范围应为明确的活动片段')
            if not preview and len(scene_ids) != 1:
                reject('INPUT_INCOMPATIBLE', '正式样片只选一页；整课生成省略范围')
            active = [s for s in active if s['id'] in scene_ids]
        if not active:
            reject('EMPTY_SCENES', '没有可生成片段')
        kind = 'sample' if scene_ids else 'course'
        models = {role: self.model_key(c) for role, c in self.service.m1.get('models', {}).items()}
        if mode == 'photo' and p.get('photo_execution', {}).get('mode') == 'cloud':
            models['photo'] = copy.deepcopy(p['photo_execution'])
        resolution = '720p' if kind == 'sample' else config['resolution']
        # At submission, authorize and checksum every exact input. Repeat at execution.
        for role in ['pptx', 'reference_audio', mode]:
            a = p['assets'].get(role)
            if not a or a['state'] != 'ready' or not a.get('authorization', {}).get('confirmed'):
                reject('INPUT_MISSING', f'{role} 未就绪或未授权')
            for field, sha in [('original', a['sha256']), ('selected', a.get('selected_sha256', a['sha256']))]:
                self.verify(pid, a[field], sha)
        if p['assets'][mode]['teacher_id'] != p['assets']['reference_audio']['teacher_id']:
            reject('TEACHER_MISMATCH', '人物与音色教师不一致')
        if not (p['assets']['reference_audio'].get('selection') or {}).get('transcript'):
            reject('REFERENCE_SELECTION_REQUIRED', '参考语音需有准确对应文字')
        mappings = body.get('subtitle_units', {})
        if not isinstance(mappings, dict) or set(mappings) - {s['id'] for s in active}:
            reject('SUBTITLE_MAPPING_REQUIRED', '字幕对应必须使用当前片段 ID')
        scenes = []
        for s in active:
            v = current(s)
            if not v or not v['reading_text'].strip():
                reject('EMPTY_SCRIPT', '片段缺少读法稿', s['id'])
            if not preview and (s['confirmed'] != v['id'] or not v.get('teacher_review') or not (s.get('audition') or {}).get('human_review')):
                reject('REVIEW_REQUIRED', '快照中片段未完成教师审核与正式试听', s['id'])
            slide = next(x for x in p['slides'] if x['source_page_id'] == s['play_page_id'])
            self.verify(pid, slide['image'], slide['image_sha256'])
            c = effective(p, s)
            c.update(mode=mode, resolution=resolution)
            paired = coalesce_punctuation(units(v, mappings.get(s['id'])))
            scenes.append({'id': s['id'], 'source_page_ids': s['source_page_ids'], 'play_page_id': s['play_page_id'], 'source_index': slide['source_index'],
                'version': v, 'config': c, 'slide': slide, 'paired': paired, 'state': 'pending', 'tts': None, 'portrait': None, 'compose': None,
                'stage_states': {'tts': 'pending', 'portrait': 'pending' if c['show_teacher'] else 'not_required', 'compose': 'pending'}, 'cache_hits': {}})
        prepared = {'snapshot': p, 'preview': preview, 'output_kind': kind, 'mode': mode, 'models': models,
                    'timeout_seconds': self.service.config.get('m3', {}).get('job_timeout_seconds', 21600), 'mapping_digest': fingerprint(mappings)}
        key = fingerprint({'export_version': 2, 'snapshot': p, 'preview': preview, 'kind': kind, 'models': models, 'scenes': [{k: s[k] for k in ['id', 'config', 'paired']} for s in scenes]})
        prepared['input_key'] = key
        prepared['sample_signature'] = self.sample_signature(prepared, scenes)
        if not preview and kind == 'course':
            review = self.review.get('sample:' + prepared['sample_signature'])
            if not review:
                reject('SAMPLE_REVIEW_REQUIRED', '先生成并确认同一快照与配置的 720p 单页样片')
            sample = self.get(pid, review['job_id'])
            self.verify(pid, sample['result']['path'], review['sha256'])
            prepared['sample_review'] = review
            prepared['layout_reviews'] = []
            for scene in scenes:
                layout = self.review.get('layout:' + self.layout_signature(p, scene))
                if not layout:
                    reject('LAYOUT_REVIEW_REQUIRED', f"原页 {scene['source_index']} 尚未人工确认重点区域无遮挡", scene['id'])
                prepared['layout_reviews'].append(layout)
        return prepared, scenes

    def sample_signature(self, payload, scenes):
        # The single-page sample confirms the whole frozen input configuration.
        p = payload['snapshot']
        return fingerprint({'snapshot_id': p['snapshot_id'], 'models': payload['models'], 'mode': payload['mode'],
                            'config': p['config'], 'scenes': [{k: s.get(k) for k in ['id', 'current_version', 'overrides']} for s in p['scenes'] if not s['skipped']],
                            'mapping_digest': payload['mapping_digest']})

    def layout_signature(self, p, scene):
        c = scene['config']
        return fingerprint({'project_id': p['id'], 'image': scene['slide']['image_sha256'],
            'layout': {k: c[k] for k in ['show_teacher', 'position', 'size', 'layout', 'subtitles', 'mode']},
            'person': p['assets'][c['mode']].get('selected_sha256', p['assets'][c['mode']]['sha256'])})

    def layouts(self, pid, snapshot_id):
        p = self.store.get_snapshot(pid, snapshot_id)
        result = []
        for s in p['scenes']:
            if s['skipped']:
                continue
            slide = next(x for x in p['slides'] if x['source_page_id'] == s['play_page_id'])
            self.verify(pid, slide['image'], slide['image_sha256'])
            value = {'id': s['id'], 'config': effective(p, s), 'slide': slide}
            key = self.layout_signature(p, value)
            result.append({'scene_id': s['id'], 'source_index': slide['source_index'], 'image': slide['image'], 'config': value['config'],
                           'binding': key, 'review': self.review.get('layout:' + key)})
        return result

    def save_layout(self, pid, snapshot_id, body):
        items = self.layouts(pid, snapshot_id)
        item = next((x for x in items if x['scene_id'] == body.get('scene_id')), None)
        if not item or item['binding'] != body.get('binding'):
            reject('REVISION_CONFLICT', '页面布局已变化，请重新核查')
        if body.get('no_obstruction') is not True or not isinstance(body.get('note'), str) or not body['note'].strip():
            reject('REVIEW_REQUIRED', '请人工核查原页重点、人物与字幕区域并填写记录')
        record = {'project_id': pid, 'snapshot_id': snapshot_id, 'scene_id': item['scene_id'], 'binding': item['binding'],
                  'no_obstruction': True, 'note': body['note'], 'at': stamp(), 'reviewer': 'local-teacher'}
        self.review.put('layout:' + item['binding'], record)
        return record

    def submit(self, pid, body):
        payload, scenes = self.prepare(pid, body)
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if payload['preview'] and self.store.get(pid, db)['revision'] != body['revision']:
                reject('REVISION_CONFLICT', '入队期间项目已更新')
            for row in db.execute("SELECT data FROM jobs WHERE project_id=?", (pid,)):
                old = json.loads(row[0])
                if old['kind'] == 'm3' and old['payload']['input_key'] == payload['input_key'] and old['state'] != 'canceled':
                    return self.public(old)
            job = {'id': uid(), 'project_id': pid, 'kind': 'm3', 'payload': payload, 'state': 'queued', 'stage': 'queued', 'created_at': stamp(),
                   'generation': 1, 'execution': None, 'cancel_requested': False, 'scenes': scenes, 'result': None, 'error': None, 'recoveries': 0}
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (job['id'], pid, 'queued', json.dumps(job, ensure_ascii=False)))
        return self.public(job)

    def needs_punctuation_repair(self, job):
        if job['state']!='failed':return False
        try:return any(coalesce_punctuation(s['paired'])!=s['paired'] for s in job['scenes'])
        except Failure as exc:
            if exc.code=='EMPTY_SCRIPT':return False  # Requires an actual script edit.
            raise

    def verify(self, pid, relative, sha):
        path = self.store.file(pid, relative)
        if not path.is_file() or digest(path) != sha:
            reject('ASSET_CHANGED', '输入或媒体文件缺失/摘要变化', relative)
        return path

    def model_key(self, config):
        # Include all parameters plus explicit YAML content digest, not just model name.
        config = copy.deepcopy(config)
        if config.get('tts_config') and Path(config['tts_config']).is_file():
            config['tts_config_sha256'] = digest(config['tts_config'])
        return config

    def cache(self, pid, layer, key):
        with self.store.connection() as db:
            row = db.execute('SELECT data FROM m3_cache WHERE project_id=? AND layer=? AND key=?', (pid, layer, key)).fetchone()
        if not row:
            return None
        record = json.loads(row[0])
        try:
            path = self.verify(pid, record['path'], record['sha256'])
            self.media.inspect(path, 'audio' if layer == 'tts' else 'video', expected_duration=record['duration_seconds'])
            if layer != 'tts':
                self.media.inspect(path, 'audio', expected_duration=record['duration_seconds'])
        except Failure:
            return None
        return record

    def publish_cache(self, job, layer, key, record):
        # Atomically fence cache publication as well as job state publication.
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            live = self.get(job['project_id'], job['id'], db)
            if live['state'] != 'running' or live.get('execution') != job['execution'] or live.get('cancel_requested'):
                reject('CANCELED', '输出到达时任务已取消或执行已过期')
            db.execute('INSERT OR REPLACE INTO m3_cache VALUES(?,?,?,?)', (job['project_id'], layer, key, json.dumps(record, ensure_ascii=False)))

    def keys(self, job, scene, paired=None):
        p, v, c = job['payload']['snapshot'], scene['version'], scene['config']
        ref = p['assets']['reference_audio']
        # Review ID is retained in manifest; equal verified speech inputs can reuse
        # actual audio across reapproval, display-only edits and new layout snapshots.
        tts = fingerprint({'schema': 'm3.tts.v2', 'reading': v['reading_text'], 'events': v['control_events'], 'paired_reading': [u['reading'] for u in (paired if paired is not None else coalesce_punctuation(scene['paired']))],
                           'reference': ref.get('selected_sha256', ref['sha256']), 'transcript': ref['selection']['transcript'],
                           'model': self.model_key(job['payload']['models'].get('tts', {})), 'speed': c['speed'], 'before': c['pause_before'], 'after': c['pause_after']})
        return tts

    def native(self, job, role, request):
        self.boundary(job)
        config = copy.deepcopy(job['payload']['models'].get(role, {}))
        if config.get('tts_config_sha256') and digest(config['tts_config']) != config['tts_config_sha256']:
            reject('MODEL_CHANGED', '入队后 TTS 推理配置变化，不能使用旧审核配置生成')
        remaining = max(1, job['payload']['timeout_seconds'] - (time.perf_counter() - job['_started']))
        config['timeout_seconds'] = min(config.get('timeout_seconds', 900), remaining)
        storage = self.store.folder(job['project_id']) / 'm3/native'
        if role == 'photo' and config.get('mode') == 'cloud':
            from mooc_cloud.adapter import RemotePhotoAdapter
            # Runtime remaining time must not change the pinned price authorization.
            config = copy.deepcopy(job['payload']['models']['photo'])
            adapter = RemotePhotoAdapter(config, self.media, storage, boundary=lambda: self.boundary(job))
        else:
            adapter = LocalModelAdapter(role, config, self.media, storage)
        result = adapter.generate(request)
        self.boundary(job)
        if result['state'] != 'media_ready':
            error = result.get('error', {})
            reject(error.get('code', 'RUN_FAILED'), error.get('message', '真实模型未返回有效媒体'), role,
                   '查看受控原生日志；检查资源及配置后有限重试，不降级人物或声音')
        return result

    def copied_native(self, job, layer, key, result):
        relative = f'm3/cache/{layer}/{key}/' + ('audio.wav' if layer == 'tts' else 'portrait.mp4')
        target = self.store.file(job['project_id'], relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix('.tmp')
        try:
            shutil.copyfile(result['output']['path'], temp)
            self.media.inspect(temp, 'audio' if layer == 'tts' else 'video', expected_duration=result['output']['duration_seconds'])
            self.boundary(job)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return {'path': relative, 'sha256': digest(target), 'duration_seconds': result['output']['duration_seconds'], 'provider': result['actual_provider'],
                'request_id': result['request_id'], 'code_revision': result['code_revision'], 'weight_version': result['actual_weight_version'],
                'native_model': result.get('native_model_record'), 'native_driving': result.get('native_driving'), 'resources': result.get('resources'),
                'native_loads': result.get('native_loads'), 'elapsed_seconds': result['elapsed_seconds'], 'quality_verified': False,
                'native_log': f"m3/native/requests/{result['request_id']}/native.log",
                **({'remote_receipt': result['remote_receipt']} if result.get('remote_receipt') else {})}

    def process_scene(self, job, scene):
        pid, payload, c, v = job['project_id'], job['payload'], scene['config'], scene['version']
        p = payload['snapshot']
        for role in ['reference_audio', payload['mode']]:
            a = p['assets'][role]
            self.verify(pid, a['selected'], a.get('selected_sha256', a['sha256']))
        self.verify(pid, scene['slide']['image'], scene['slide']['image_sha256'])
        paired=coalesce_punctuation(scene['paired'])
        key = self.keys(job, scene, paired)
        scene.update(state='running', active_stage='tts')
        job['stage'] = 'tts_native_generation'
        self.save(job)
        audio = self.cache(pid, 'tts', key)
        scene['cache_hits']['tts'] = {'hit': bool(audio), 'key': key, 'reason': 'verified_compatible_speech_inputs' if audio else 'no_valid_compatible_media'}
        runs, groups = speech_runs(v, paired, c['pause_after'])
        if not audio:
            ref = p['assets']['reference_audio']
            result = self.native(job, 'tts', {'purpose': 'audition', 'draft_preview': payload['preview'], 'script_confirmed': not payload['preview'],
                'authorized': True, 'authorization_record': f"m3 project {pid} snapshot {p['snapshot_id']} reference {ref['id']}", 'text': v['reading_text'],
                'speech_segments': runs, 'pause_before': c['pause_before'], 'speed_factor': c['speed'],
                'reference_audio': str(self.store.file(pid, ref['selected'])), 'reference_transcript': ref['selection']['transcript']})
            audio = self.copied_native(job, 'tts', key, result)
            audio['speech_timeline'] = result['native_model_record']['speech_timeline']
            self.publish_cache(job, 'tts', key, audio)
        # Display-only edits reuse audio but regenerate sentence captions.
        scene['tts'] = {**audio, 'captions': captions(paired, groups, audio['speech_timeline'])}
        scene['stage_states']['tts'] = 'valid'
        self.save(job)
        self.boundary(job)
        portrait = None
        if c['show_teacher']:
            role = payload['mode']
            a = p['assets'][role]
            person_key = fingerprint({'schema': 'm3.portrait.v1', 'audio': audio['sha256'], 'mode': role,
                'source': a.get('selected_sha256', a['sha256']), 'model': self.model_key(payload['models'].get(role, {}))})
            scene['active_stage'], job['stage'] = 'portrait', role + '_native_generation'
            self.save(job)
            portrait = self.cache(pid, 'portrait', person_key)
            scene['cache_hits']['portrait'] = {'hit': bool(portrait), 'key': person_key, 'reason': 'same_current_audio_and_person_model' if portrait else 'current_audio_or_person_inputs_require_generation'}
            if not portrait:
                result = self.native(job, role, {'purpose': 'm3_segment', 'authorized': True,
                    'operation_id': f"{job['id']}:{scene['id']}", 'generation': job['generation'],
                    'authorization_record': f"m3 project {pid} person {a['id']} snapshot {p['snapshot_id']}",
                    'audio': str(self.store.file(pid, audio['path'])), role: str(self.store.file(pid, a['selected']))})
                portrait = self.copied_native(job, 'portrait', person_key, result)
                portrait['audio_sha256'] = audio['sha256']
                portrait['mode'] = role
                self.publish_cache(job, 'portrait', person_key, portrait)
            scene['portrait'] = portrait
            scene['stage_states']['portrait'] = 'valid'
            self.save(job)
        self.boundary(job)
        scene['active_stage'], job['stage'] = 'compose', 'composing_original_page'
        self.save(job)
        render_config = {k: c[k] for k in ['resolution', 'subtitles', 'show_teacher', 'position', 'size', 'layout']}
        composite_key = fingerprint({'schema': 'm3.compose.v3', 'audio': audio['sha256'], 'portrait': portrait['sha256'] if portrait else None,
            'image': scene['slide']['image_sha256'], 'captions': scene['tts']['captions'], 'config': render_config, 'draft': payload['preview'], 'encoding': 'h264-aac-25fps-48khz-stereo'})
        composed = self.cache(pid, 'compose', composite_key)
        scene['cache_hits']['compose'] = {'hit': bool(composed), 'key': composite_key, 'reason': 'same_page_media_captions_layout_encoding' if composed else 'composition_inputs_changed_or_missing'}
        if not composed:
            relative = f'm3/cache/compose/{composite_key}/page.mp4'
            composed = compose(self.media, self.store.file(pid, scene['slide']['image']), self.store.file(pid, audio['path']),
                self.store.file(pid, portrait['path']) if portrait else None, scene['tts']['captions'], c, self.store.file(pid, relative), payload['preview'], self.remaining(job, 300))
            composed['path'] = relative
            self.boundary(job)
            self.publish_cache(job, 'compose', composite_key, composed)
        scene['compose'] = composed
        scene['stage_states']['compose'] = 'valid'
        scene.update(state='valid', active_stage=None, error=None)
        self.save(job)

    def remaining(self, job, limit):
        self.boundary(job)
        return max(1, min(limit, job['payload']['timeout_seconds'] - (time.perf_counter() - job['_started'])))

    def execute(self, job):
        job['_started'] = time.perf_counter()
        job['execution'] = uid()
        # Initial execution token is installed transactionally before any subprocess.
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            live = self.get(job['project_id'], job['id'], db)
            if live['state'] != 'running' or live.get('execution') is not None:
                return
            job['cancel_requested'] = live['cancel_requested']
            db.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps({k: v for k, v in job.items() if k != '_started'}, ensure_ascii=False), job['id']))
        active = None
        try:
            self.boundary(job)
            for scene in job['scenes']:
                active = scene
                self.boundary(job)
                # Cache validation repeats decode/hash checks on restart, even for valid scenes.
                self.process_scene(job, scene)
            self.boundary(job)
            active = None
            job['stage'] = 'validating_and_exporting_course'
            self.save(job)
            pid = job['project_id']
            folder = f"m3/jobs/{job['id']}/generation-{job['generation']}"
            pages, cues, duration = course_timeline(job['scenes'])
            result = join(self.media, [self.store.file(pid, s['compose']['path']) for s in job['scenes']], self.store.file(pid, folder + '/course.mp4'), duration, self.remaining(job, 600))
            result.update(path=folder + '/course.mp4', preview=job['payload']['preview'], output_kind=job['payload']['output_kind'], timeline=pages,
                          snapshot_id=job['payload']['snapshot']['snapshot_id'], input_key=job['payload']['input_key'], quality_verified=False)
            self.store.file(pid, folder + '/course.srt').write_text(srt(cues), encoding='utf-8')
            transcript = '\n\n'.join(f"## 原页 {s['source_index']} · 片段 {s['id']}\n\n{s['version']['display_text']}\n\n来源：{', '.join(s['source_page_ids'])}" for s in job['scenes'])
            self.store.file(pid, folder + '/scripts.md').write_text(transcript, encoding='utf-8')
            manifest = {'schema_version': 'm3.manifest.v1', 'job_id': job['id'], 'generation': job['generation'], 'project_id': pid,
                        'snapshot_id': result['snapshot_id'], 'project_revision': job['payload']['snapshot']['revision'], 'config_version': job['payload']['snapshot']['config_version'],
                        'input_key': result['input_key'], 'preview': result['preview'], 'quality_verified': False, 'mode': job['payload']['mode'],
                        'created_at': stamp(), 'timeline': pages, 'duration_seconds': duration, 'scenes': job['scenes'],
                        'assets': job['payload']['snapshot']['assets'], 'models': job['payload']['models'], 'm1_review': self.review.get('m1:' + pid),
                        'sample_review': job['payload'].get('sample_review'), 'layout_reviews': job['payload'].get('layout_reviews'), 'recoveries': job['recoveries'], 'attempts': job.get('attempts', []),
                        'checks': result, 'caption_scope': 'sentence intervals measured during actual TTS; word alignment and pedagogical quality require human review'}
            result['exports'] = {k: folder + '/' + name for k, name in {'mp4': 'course.mp4', 'srt': 'course.srt', 'script': 'scripts.md', 'manifest': 'manifest.json'}.items()}
            write_json(self.store.file(pid, folder + '/manifest.json'), manifest)
            result['file_hashes'] = {k: digest(self.store.file(pid, rel)) for k, rel in result['exports'].items()}
            self.boundary(job)
            job.update(state='completed', stage='draft_preview_ready' if job['payload']['preview'] else 'sample_awaiting_review' if job['payload']['output_kind'] == 'sample' else 'completed',
                       result=result, finished_at=stamp(), error=None)
            self.save(job, final=True)
        except Exception as exc:
            error = exc.record() if isinstance(exc, Failure) else {'code': 'RUN_FAILED', 'message': '媒体处理失败，请查看受控记录'}
            if error['code'] == 'STALE_EXECUTION':
                return
            if active:
                active.update(state='failed', error=error)
                active['stage_states'][active.get('active_stage') or 'compose'] = 'failed'
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                live = self.get(job['project_id'], job['id'], db)
                if live['state'] != 'running' or live.get('execution') != job['execution']:
                    return
                if live.get('cancel_requested') or error['code'] == 'CANCELED':
                    job.update(state='canceled', stage='canceled', result=None)
                elif error['code'] == 'WORKER_INTERRUPTED':
                    job.update(state='queued', stage='recovering_validated_stages', execution=None)
                else:
                    job.update(state='failed', result=None)
                job.update(error=error, finished_at=stamp(), elapsed_seconds=job.get('elapsed_before_execution', 0) + time.perf_counter() - job['_started'])
                self.cleanup_unpublished(job['project_id'])
                job.pop('_started', None)
                db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (job['state'], json.dumps(job, ensure_ascii=False), job['id']))

    def sample_review(self, pid, jid, body):
        job = self.get(pid, jid)
        if job['state'] != 'completed' or job['payload']['preview'] or job['payload']['output_kind'] != 'sample':
            reject('REVIEW_REQUIRED', '仅真实、已完成的审核快照样片可供正式确认')
        checks = body.get('checks', {})
        if set(checks) != {'identity_voice', 'lipsync_seams', 'subtitles_timing', 'layout_no_obstruction'} or any(v is not True for v in checks.values()) or not isinstance(body.get('note'), str) or not body['note'].strip():
            reject('REVIEW_REQUIRED', '请逐项核查人物音色、口型接缝、字幕时间及重点区域无遮挡并填写记录')
        self.verify(pid, job['result']['path'], job['result']['sha256'])
        record = {'project_id': pid, 'job_id': jid, 'checks': checks, 'note': body['note'], 'reviewer': 'local-teacher', 'at': stamp(), 'sha256': job['result']['sha256']}
        self.review.put('sample:' + job['payload']['sample_signature'], record)
        for scene in job['scenes']:
            key = self.layout_signature(job['payload']['snapshot'], scene)
            self.review.put('layout:' + key, {'project_id': pid, 'scene_id': scene['id'], 'binding': key, 'no_obstruction': True,
                'note': body['note'], 'reviewer': 'local-teacher', 'at': stamp(), 'sample_job_id': jid})
        return record

    def public(self, job):
        result = copy.deepcopy({k: v for k, v in job.items() if k not in {'payload', 'scenes', '_started'}})
        result['preview'] = job['payload']['preview']
        result['snapshot_id'] = job['payload']['snapshot']['snapshot_id']
        result['mode'] = job['payload']['mode']
        result['output_kind'] = job['payload']['output_kind']
        result['scenes'] = [{k: s.get(k) for k in ['id', 'source_index', 'state', 'active_stage', 'stage_states', 'cache_hits', 'error']} |
                           {'preview_path': (s.get('compose') or {}).get('path')} for s in job['scenes']]
        result['progress'] = {k: sum(s['stage_states'].get(k) in {'valid', 'not_required'} for s in job['scenes']) for k in ['tts', 'portrait', 'compose']}
        result['progress'].update(total=len(job['scenes']), valid=sum(s['state'] == 'valid' for s in job['scenes']), failed=sum(s['state'] == 'failed' for s in job['scenes']))
        return result

    def list(self, pid):
        return [self.public(j) for j in self.store.jobs(pid) if j['kind'] == 'm3']
