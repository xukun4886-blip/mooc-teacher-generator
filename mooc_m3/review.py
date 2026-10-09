from __future__ import annotations

from pathlib import Path
from mooc_m1.core import digest, read_json, stamp
from mooc_m2.content import fingerprint, reject


CRITERIA = {
    'voice_similarity': '对照原参考语音，音色一致',
    'mandarin_terms_and_formula_letters': '普通话、术语、公式字母读法正确',
    'no_missing_sentences': '对照样片讲稿，无漏句',
    'no_repeated_sentences': '无重复句',
    'pauses_appropriate': '停顿合理',
    'selected_person_consistent': '对照原素材，人物身份一致',
    'photo_lipsync': '照片 A/B 口型与各自音频一致',
    'video_lipsync': '视频 A/B 口型与各自音频一致',
    'video_turnaround_smooth': '连续观看视频循环和转向接缝',
    'a_b_driving_correspondence': 'A/B 各自对应不同讲解，无固定说话片复用',
    'course_original_page_fidelity': '原页保真，字体、公式和图表可读',
}


class Review:
    def __init__(self, service):
        import threading
        self.service, self.store = service, service.store
        self.playback_lock = threading.Lock()
        with self.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS m3_reviews(key TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS m3_review_history(id INTEGER PRIMARY KEY, key TEXT, data TEXT NOT NULL)')

    def binding(self, project):
        models = {role: self.service.m3.model_key(c) for role, c in self.service.m1.get('models', {}).items()}
        if project.get('photo_execution', {}).get('mode') == 'cloud':
            models['photo'] = project['photo_execution']
        return fingerprint({'assets': {k: [a.get('selected_sha256', a['sha256']), a.get('selection'), a.get('teacher_id')]
            for k, a in project['assets'].items()}, 'models': models})

    def gallery(self, pid):
        p = self.store.get(pid)
        result = []
        for role in ['reference_audio', 'photo', 'video']:
            asset = p['assets'].get(role)
            if asset:
                for field in ['original', 'selected']:
                    path = self.store.file(pid, asset[field])
                    if path.is_file():
                        result.append({'id': role + '-' + field, 'label': {'reference_audio': '参考语音', 'photo': '教师照片', 'video': '教师原视频'}[role] + ('原件' if field == 'original' else '当前选择'),
                            'kind': 'audio' if role == 'reference_audio' else role, 'path': str(path), 'sha256': digest(path), 'original_video': role == 'video'})
        baseline_path = self.service.base / 'docs/evidence/M1/human-review.json'
        native_path = self.service.base / 'docs/evidence/M1/native-requests.json'
        if baseline_path.is_file() and native_path.is_file():
            baseline, native = read_json(baseline_path), read_json(native_path)['requests']
            for role, ids in [('tts', [baseline['voice_request_id']]), ('photo', baseline['photo_request_ids']), ('video', baseline['video_request_ids'])]:
                for i, rid in enumerate(ids):
                    record = next((r for r in native if r['request_id'] == rid), None)
                    if not record:
                        continue
                    for field in ['output', 'warm_output']:
                        output = record.get(field)
                        if not output or not Path(output['path']).is_file():
                            continue
                        cfg = self.service.m1.get('models', {}).get(role, {})
                        request_path = Path(output['path']).parent / 'worker-request.json'
                        native_request = read_json(request_path) if request_path.is_file() else {}
                        source_role = 'reference_audio' if role == 'tts' else role
                        asset = p['assets'].get(source_role, {})
                        source_hash = record.get('inputs', {}).get(source_role, {}).get('sha256')
                        compatible = bool(native_request.get('config') == cfg and record.get('code_revision') == cfg.get('code_revision')
                            and source_hash == asset.get('selected_sha256', asset.get('sha256')))
                        if role == 'photo' and p.get('photo_execution', {}).get('mode') == 'cloud':
                            compatible = False
                        if role == 'tts':
                            compatible = compatible and record.get('native_model_record', {}).get('inference_config_sha256') == (digest(cfg['tts_config']) if cfg.get('tts_config') and Path(cfg['tts_config']).is_file() else None)
                        result.append({'id': rid + '-' + field, 'label': {'tts': '完整真实合成语音', 'photo': '照片真实样片', 'video': '视频真实样片'}[role] + (' 预热对照 B' if field == 'warm_output' else ' 预热对照 A' if i else ' 首次 A'),
                            'kind': 'audio' if role == 'tts' else 'video', 'path': output['path'], 'sha256': output['sha256'], 'request_id': rid,
                            'baseline_sample': True, 'role': role, 'compatible_with_current': compatible})
        return result

    def get(self, key):
        import json
        with self.store.connection() as db:
            row = db.execute('SELECT data FROM m3_reviews WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, record):
        import json
        with self.store.connection() as db:
            db.execute('INSERT OR REPLACE INTO m3_reviews VALUES(?,?)', (key, json.dumps(record, ensure_ascii=False)))
            db.execute('INSERT INTO m3_review_history(key,data) VALUES(?,?)', (key, json.dumps(record, ensure_ascii=False)))

    def state(self, pid):
        p = self.store.get(pid)
        saved = self.get('m1:' + pid)
        gallery = self.gallery(pid)
        sample_script = None
        for a in gallery:
            if a.get('request_id') and a['kind'] == 'audio':
                request_path = Path(a['path']).parent / 'worker-request.json'
                if request_path.is_file():
                    sample_script = read_json(request_path)['request'].get('text')
        return {'criteria': CRITERIA, 'saved': saved, 'binding': self.binding(p), 'stale': bool(saved and saved['binding'] != self.binding(p)),
                'sample_script': sample_script, 'reference_transcript': (p['assets'].get('reference_audio', {}).get('selection') or {}).get('transcript'),
                'gallery': [{k: v for k, v in a.items() if k != 'path'} for a in gallery],
                'm1_stage_passed': False, 'baseline_note': 'M1 原始样片：请对照当前选择；保存评审不自动宣告阶段通过。'}

    def save(self, pid, body):
        p = self.store.get(pid)
        if body.get('binding') != self.binding(p):
            reject('REVISION_CONFLICT', '素材或模型已变化，请重新加载评审')
        checks = body.get('checks')
        if not isinstance(checks, dict) or set(checks) != set(CRITERIA) or any(v is not None and type(v) is not bool for v in checks.values()):
            reject('INPUT_INCOMPATIBLE', '评审结论须为逐项待评、通过或需修复')
        completed = body.get('completed') is True
        if not isinstance(body.get('note'), str) or not body['note'].strip() or (completed and any(v is not True for v in checks.values())):
            reject('REVIEW_REQUIRED', '请填写人工评审记录；完成需逐项通过')
        gallery = self.gallery(pid)
        if completed and any(not a.get('compatible_with_current') for a in gallery if a.get('baseline_sample')):
            reject('M1_SAMPLE_STALE', '已有 M1 样片与当前选择或模型不兼容，需按当前素材/模型真实复测后评审')
        if completed and (sum(a.get('baseline_sample', False) and a['kind'] == 'audio' for a in gallery) < 1 or sum(a.get('baseline_sample', False) and a['kind'] == 'video' for a in gallery) < 4):
            reject('REVIEW_REQUIRED', '真实语音及两条 A/B 样片不齐全，不能保存完成结论')
        for a in gallery:
            if digest(a['path']) != a['sha256']:
                reject('ASSET_CHANGED', '样片摘要变化，不能保存通过结论')
        record = {'checks': checks, 'completed': completed, 'note': body['note'], 'reviewer': 'local-teacher', 'at': stamp(),
                  'binding': self.binding(p), 'gallery_digest': fingerprint([{k: v for k, v in a.items() if k != 'path'} for a in gallery])}
        self.put('m1:' + pid, record)
        return self.state(pid)

    def playback(self, pid, item):
        """Browser-compatible original-video playback copy; driver remains original."""
        if not item.get('original_video'):
            return Path(item['path'])
        with self.playback_lock:
            return self._video_playback(pid, item)

    def _video_playback(self, pid, item):
        output = self.store.file(pid, 'm3/review-playback/' + item['sha256'] + '.mp4')
        if not output.is_file():
            from mooc_m1.core import run
            output.parent.mkdir(parents=True, exist_ok=True)
            temp = output.with_name(item['sha256'] + '-publishing.mp4')
            run([self.service.media.ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', item['path'], '-map', '0:v:0', '-map', '0:a?',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', temp], 180)
            self.service.media.inspect(temp, 'video')
            temp.replace(output)
        return output

    def ready(self, p):
        record = self.get('m1:' + p['id'])
        gallery = self.gallery(p['id'])
        return bool(record and record['completed'] and record['binding'] == self.binding(p)
            and record['gallery_digest'] == fingerprint([{k: v for k, v in a.items() if k != 'path'} for a in gallery])
            and all(digest(a['path']) == a['sha256'] for a in gallery)
            and all(a.get('compatible_with_current') for a in gallery if a.get('baseline_sample')))
