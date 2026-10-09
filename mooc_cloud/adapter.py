"""Durable remote receipt, hash-bound inputs, resumable result download."""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from mooc_m1.core import Failure, digest, read_json, stamp, write_json
from mooc_m2.content import fingerprint
from .protocol import client, checked, health, pinned


class RemotePhotoAdapter:
    def __init__(self, config, media, storage, boundary=lambda: None, transport=None):
        self.config, self.media, self.storage = config, media, Path(storage)
        self.boundary, self.transport = boundary, transport

    def health(self):
        try:
            result = health(self.config, transport=self.transport)
            if result['model_key'] != self.config['model_key'] or result['price'] != self.config['price']:
                raise Failure('MODEL_CHANGED', '云端版本或报价已变化')
            return result
        except Failure as exc:
            return {'ready': False, 'blockers': [exc.record()]}

    def capabilities(self):
        return {'provider': 'SadTalker', 'execution': 'remote_resident_worker', 'quality_verified': False,
                'cold_seconds': None, 'warm_seconds': None, 'fee': self.config.get('price')}

    def generate(self, request):
        self.boundary()
        config = self.config
        if not request.get('authorized') or not request.get('authorization_record'):
            raise Failure('AUTHORIZATION_REQUIRED', '缺少素材授权记录')
        observed = health(config, transport=self.transport)
        pinned(config, observed)
        if observed['model_key'] != config['model_key'] or observed['price'] != config['price']:
            raise Failure('MODEL_CHANGED', '云端版本或报价已变化，请重新检查并保存服务器配置')
        photo, audio = Path(request['photo']), Path(request['audio'])
        self.media.inspect(photo, 'photo')
        audio_info = self.media.inspect(audio, 'audio', min_duration=.1)
        inputs = {'photo_sha256': digest(photo), 'audio_sha256': audio_info['sha256'],
                  'model_key': config['model_key'], 'batch_size': config['batch_size']}
        # Stable across local execution fences and process restarts; explicit retry
        # of a failed cloud generation gets a new key. A network failure does not.
        operation = fingerprint({'operation': request['operation_id'], 'inputs': inputs})
        folder = self.storage / 'requests' / operation
        folder.mkdir(parents=True, exist_ok=True)
        receipt = folder / 'remote-receipt.json'
        record = read_json(receipt) if receipt.is_file() else {'operation': operation, 'attempt': 1, 'created_at': stamp()}
        if record.get('remote_state') in {'failed', 'canceled'} and request.get('generation', 1) > record.get('local_generation', 1):
            record['attempt'] += 1
        record.update(local_generation=request.get('generation', 1), inputs=inputs)
        key = fingerprint({'operation': operation, 'attempt': record['attempt']})
        record['idempotency_key'] = key
        write_json(receipt, record)  # Persist before POST, including ambiguous submission.
        started = time.perf_counter()
        deadline = started + config['timeout_seconds']
        timings = {}
        def checkpoint():
            self.boundary()
            if time.perf_counter() >= deadline:
                raise Failure('TIMEOUT', '云端人物片段超时；收据已保留，可按原任务查询恢复')
        def chunks(path):
            with path.open('rb') as source:
                while chunk := source.read(1024 * 1024):
                    checkpoint()
                    yield chunk
        with client(config, transport=self.transport) as http:
            try:
                before = time.perf_counter()
                for path, kind, sha in [(photo, 'photo', inputs['photo_sha256']), (audio, 'audio', inputs['audio_sha256'])]:
                    checkpoint()
                    exists = http.head('v1/blobs/' + sha)
                    if exists.status_code == 404:
                        checked(http.put('v1/blobs/' + sha, params={'kind': kind}, content=chunks(path),
                                         headers={'Content-Type': 'application/octet-stream', 'X-Content-Bytes': str(path.stat().st_size)}))
                    else:
                        checked(exists)
                timings['upload_seconds'] = time.perf_counter() - before
                checkpoint()
                submitted = checked(http.post('v1/jobs', json={**inputs, 'idempotency_key': key,
                    'max_seconds': config['timeout_seconds'], 'allow_paid': config['allow_paid'], 'max_cost': config['max_cost']})).json()
                jid = submitted['id']
                if not isinstance(jid, str) or not __import__('re').fullmatch(r'[0-9a-f]{64}', jid):
                    raise Failure('CLOUD_INCOMPATIBLE', '云端任务标识无效')
                record.update(remote_id=jid, remote_state=submitted['state'])
                write_json(receipt, record)
                before = time.perf_counter()
                while True:
                    checkpoint()
                    remote = checked(http.get('v1/jobs/' + jid)).json()
                    record['remote_state'] = remote['state']
                    write_json(receipt, record)
                    if remote['state'] in {'failed', 'canceled'}:
                        raise Failure('CLOUD_GENERATION_FAILED', '云端人物生成失败，原失败及收据已保留；可有限重试')
                    if remote['state'] == 'completed':
                        break
                    time.sleep(.2 if self.transport else 2)
                timings['remote_wait_seconds'] = time.perf_counter() - before
                if any(remote.get(k) != v for k, v in inputs.items()):
                    raise Failure('CLOUD_INPUT_MISMATCH', '云端结果的当前音频、照片或模型摘要不一致')
                output = remote['output']
                sha, size = output['sha256'], output['bytes']
                if not __import__('re').fullmatch(r'[0-9a-f]{64}', str(sha)) or type(size) is not int or not 0 < size <= 2 * 1024**3:
                    raise Failure('CLOUD_INCOMPATIBLE', '云端输出摘要或大小无效')
                dest, part = folder / 'portrait.mp4', folder / 'portrait.mp4.part'
                before = time.perf_counter()
                if not dest.is_file() or digest(dest) != sha:
                    offset = part.stat().st_size if part.is_file() else 0
                    if offset >= size:
                        offset = 0
                    headers = {'Range': f'bytes={offset}-'} if offset else {}
                    with http.stream('GET', 'v1/jobs/' + jid + '/result', headers=headers) as response:
                        checked(response)
                        append = offset > 0 and response.status_code == 206
                        if append and response.headers.get('content-range') != f'bytes {offset}-{size-1}/{size}':
                            raise Failure('CLOUD_INCOMPATIBLE', '云端续传范围无效')
                        with part.open('ab' if append else 'wb') as target:
                            for chunk in response.iter_bytes(1024 * 1024):
                                checkpoint()
                                target.write(chunk)
                    if part.stat().st_size != size or digest(part) != sha:
                        raise Failure('CLOUD_OUTPUT_CHANGED', '云端媒体传输不完整或摘要不一致；保留下载收据')
                    part.replace(dest)
                timings['download_seconds'] = time.perf_counter() - before
                checkpoint()
                info = self.media.inspect(dest, 'video', expected_duration=audio_info['duration_seconds'])
                self.media.inspect(dest, 'audio', expected_duration=audio_info['duration_seconds'])
                result = {'state': 'media_ready', 'request_id': operation, 'actual_provider': 'SadTalker', 'output': info,
                    'code_revision': observed['model']['code_revision'], 'actual_weight_version': observed['model']['weight_version'],
                    'native_model_record': remote['metrics'], 'native_driving': inputs, 'native_loads': observed['model']['weights'],
                    'resources': remote['metrics'].get('resources'), 'elapsed_seconds': time.perf_counter() - started,
                    'remote_receipt': {'id': jid, 'inputs': inputs, 'timings': timings, 'metrics': remote['metrics']}, 'quality_verified': False}
                write_json(folder / 'status.json', result)
                (folder / 'native.log').write_text(__import__('json').dumps(result['remote_receipt'], ensure_ascii=False, indent=2), encoding='utf-8')
                return result
            except httpx.HTTPError as exc:
                raise Failure('CLOUD_UNAVAILABLE', '云端连接中断；收据已保存，恢复时查询同一云端任务') from exc
            except (ValueError, KeyError, TypeError) as exc:
                raise Failure('CLOUD_INCOMPATIBLE', '云端任务响应字段或格式不兼容；收据已保留') from exc
            except Failure as exc:
                if exc.code == 'CANCELED' and record.get('idempotency_key'):
                    try:
                        http.post('v1/jobs/' + record.get('remote_id', record['idempotency_key']) + '/cancel')
                    except httpx.HTTPError:
                        pass
                raise
