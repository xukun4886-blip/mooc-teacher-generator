"""Single authenticated GPU worker, durable jobs; no PPT/scripts/review uploads."""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from mooc_m1.core import Failure, digest, stamp, write_json
from mooc_m1.media import MediaTools
from mooc_m2.content import fingerprint
from .engine import ResidentSadTalker, descriptor, runtime_readiness
from .protocol import PROTOCOL


class Worker:
    def __init__(self, config, engine_factory=ResidentSadTalker, model=None):
        self.config = dict(config)
        self.root = Path(config['storage']).resolve()
        self.config['storage'] = str(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != 'nt':
            os.chmod(self.root, 0o700)
        self.model = model or descriptor(config)
        self.model_key = fingerprint(self.model)
        self.blockers = runtime_readiness() if engine_factory is ResidentSadTalker else []
        self.media = MediaTools(config.get('ffmpeg', 'ffmpeg'), config.get('ffprobe', 'ffprobe'))
        self.engine_factory = engine_factory
        self.engine = engine_factory(self.config, self.model)
        self.stop = threading.Event()
        self.thread = None
        self.lock = None
        price = config.get('price', {})
        rate = price.get('hourly_rate')
        if type(rate) not in {int, float} or not math.isfinite(rate) or rate < 0 or not price.get('currency'):
            raise Failure('CLOUD_CONFIG_MISSING', '请设置小时费率/币种；已有自用服务器可声明费率0')
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,state TEXT,data TEXT)')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'jobs.sqlite3', timeout=30)
        db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def blob(self, sha):
        if not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise HTTPException(422, '摘要格式无效')
        return self.root / 'blobs' / sha

    def get(self, jid, db=None):
        if db is None:
            with self.db() as conn:
                return self.get(jid, conn)
        row = db.execute('SELECT data FROM jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise HTTPException(404, '任务不存在')
        return json.loads(row[0])

    def save(self, job, db):
        db.execute('UPDATE jobs SET state=?,data=? WHERE id=?', (job['state'], json.dumps(job), job['id']))

    def submit(self, body):
        if self.blockers:
            raise HTTPException(503, '模型运行环境尚未就绪；健康接口列出阻断项')
        required = {'idempotency_key', 'photo_sha256', 'audio_sha256', 'model_key', 'batch_size', 'max_seconds', 'allow_paid', 'max_cost'}
        if not isinstance(body, dict) or set(body) != required:
            raise HTTPException(422, '任务字段不兼容')
        for key in ['idempotency_key', 'photo_sha256', 'audio_sha256', 'model_key']:
            if not isinstance(body[key], str) or not re.fullmatch(r'[0-9a-f]{64}', body[key]):
                raise HTTPException(422, '任务摘要无效')
        if body['model_key'] != self.model_key:
            raise HTTPException(409, '模型版本变化')
        if type(body['batch_size']) is not int or body['batch_size'] not in {1, 2, 4}:
            raise HTTPException(422, 'batch 不兼容')
        if type(body['max_seconds']) is not int or not 30 <= body['max_seconds'] <= self.config.get('max_job_seconds', 7200):
            raise HTTPException(422, '时限不兼容')
        cost = self.config['price']['hourly_rate'] * body['max_seconds'] / 3600
        cap = body['max_cost']
        if type(cap) not in {int, float} or not math.isfinite(cap) or cap < 0 or (cost > 0 and (body['allow_paid'] is not True or cap < cost)):
            raise HTTPException(422, '费用授权不足')
        key = body['idempotency_key']
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM jobs WHERE id=?', (key,)).fetchone()
            if row:
                existing = json.loads(row[0])
                if existing['request'] != body:
                    raise HTTPException(409, '幂等键对应的参数不一致')
                return existing
            photo, audio = self.blob(body['photo_sha256']), self.blob(body['audio_sha256'])
            for path in [photo, audio]:
                if not path.is_file() or digest(path) != path.name:
                    raise HTTPException(422, '输入未完整上传')
            self.media.inspect(photo, 'photo')
            metadata = self.media.inspect(audio, 'audio', min_duration=.1)
            if metadata['duration_seconds'] > self.config.get('max_clip_seconds', 120):
                raise HTTPException(422, '仅接收限定时长的片段')
            job = {'id': key, 'request': body, 'state': 'queued', 'created_at': stamp(), 'recoveries': 0,
                   'history': [], 'audio_duration_seconds': metadata['duration_seconds'],
                   **{k: body[k] for k in ['photo_sha256', 'audio_sha256', 'model_key', 'batch_size']}}
            db.execute('INSERT INTO jobs VALUES(?,?,?)', (key, 'queued', json.dumps(job)))
            return job

    def cancel(self, jid):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self.get(jid, db)
            if job['state'] in {'queued', 'running'}:
                job['state'] = 'canceled'
                job['history'].append({'at': stamp(), 'reason': 'user_cancel'})
                self.save(job, db)
            return job

    def start(self):
        # Prevent two process workers claiming the same GPU/database.
        self.lock = (self.root / '.worker.lock').open('a+b')
        if os.name == 'nt':
            import msvcrt
            self.lock.write(b'1'); self.lock.flush(); self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for (data,) in db.execute("SELECT data FROM jobs WHERE state='running'").fetchall():
                job = json.loads(data)
                job['recoveries'] += 1
                job['history'].append({'at': stamp(), 'reason': 'worker_restart', 'execution': job.get('execution')})
                job['state'] = 'queued' if job['recoveries'] <= 2 else 'failed'
                self.save(job, db)
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(35)
        if self.lock and (not self.thread or not self.thread.is_alive()):
            self.lock.close()

    def loop(self):
        while not self.stop.is_set():
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT data FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
                job = json.loads(row[0]) if row else None
                if job:
                    job.update(state='running', execution=uuid.uuid4().hex, started_at=stamp())
                    self.save(job, db)
            if job:
                self.execute(job)
            else:
                self.stop.wait(.2)

    def execute(self, job):
        folder = self.root / 'jobs' / job['id'] / job['execution']
        folder.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        def boundary():
            live = self.get(job['id'])
            if self.stop.is_set() or live['state'] != 'running' or live.get('execution') != job['execution']:
                raise Failure('CANCELED', '已取消或旧工作进程')
            if time.perf_counter() - started > job['request']['max_seconds']:
                raise Failure('TIMEOUT', '云端片段超过时限')
        try:
            with (folder / 'native.log').open('a', encoding='utf-8', buffering=1) as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    output, metrics = self.engine.generate(self.blob(job['photo_sha256']), self.blob(job['audio_sha256']),
                                                            folder, job['batch_size'], boundary)
            boundary()
            before = time.perf_counter()
            info = self.media.inspect(output, 'video', expected_duration=job['audio_duration_seconds'])
            self.media.inspect(output, 'audio', expected_duration=job['audio_duration_seconds'])
            metrics['output_validation_seconds'] = time.perf_counter() - before
            metrics['worker_wall_seconds'] = time.perf_counter() - started
            metrics['quality_verified'] = False
            completed = {**job, 'state': 'completed', 'completed_at': stamp(), 'metrics': metrics,
                         'output': {'path': str(Path(output).relative_to(self.root)), 'sha256': info['sha256'],
                                    'bytes': Path(output).stat().st_size, 'duration_seconds': info['duration_seconds']}}
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                live = self.get(job['id'], db)
                if live['state'] == 'running' and live.get('execution') == job['execution']:
                    self.save(completed, db)
            write_json(folder / 'metrics.json', metrics)
        except Exception as exc:
            with (folder / 'native.log').open('a', encoding='utf-8') as log:
                log.write(traceback.format_exc())
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                live = self.get(job['id'], db)
                if live['state'] == 'running' and live.get('execution') == job['execution']:
                    # On controlled shutdown leave running for bounded recovery.
                    if not self.stop.is_set():
                        live.update(state='failed', error={'code': getattr(exc, 'code', 'RUN_FAILED'), 'message': '查看受控原生日志'}, failed_at=stamp())
                        self.save(live, db)
            # Avoid keeping partially constructed/OOM model instances alive.
            self.engine = self.engine_factory(self.config, self.model)


def create_app(config, *, engine_factory=ResidentSadTalker, model=None, worker=True):
    token = os.environ.get(config.get('token_env', 'MOOC_CLOUD_TOKEN'), '')
    if len(token) < 24:
        raise Failure('CLOUD_CONFIG_MISSING', '工作进程令牌须通过环境变量设置，至少24字符')
    service = Worker(config, engine_factory, model)
    @contextlib.asynccontextmanager
    async def lifespan(app):
        if worker:
            service.start()
        yield
        service.close()
    app = FastAPI(title='MOOC SadTalker worker', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.worker = service
    def authorized(request: Request):
        if not secrets.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + token):
            raise HTTPException(401, '令牌无效')
    protected = [Depends(authorized)]
    @app.exception_handler(Failure)
    async def failure(request, exc):
        return JSONResponse({'error': exc.record()}, status_code=422)
    @app.get('/v1/health', dependencies=protected)
    def health():
        return {'protocol': PROTOCOL, 'model': service.model, 'price': config['price'],
                'ready': not service.blockers, 'blockers': service.blockers,
                'resident_loaded': service.engine.loaded, 'quality_verified': False}
    @app.head('/v1/blobs/{sha}', dependencies=protected)
    def head(sha: str):
        path = service.blob(sha)
        if not path.is_file() or digest(path) != sha:
            raise HTTPException(404, '输入不存在')
        return Response(headers={'X-Content-Sha256': sha, 'X-Content-Bytes': str(path.stat().st_size)})
    @app.put('/v1/blobs/{sha}', dependencies=protected)
    async def upload(sha: str, kind: str, request: Request):
        target = service.blob(sha)
        if kind not in {'photo', 'audio'}:
            raise HTTPException(422, '仅接收照片和驱动音频')
        limit = 20 * 1024**2 if kind == 'photo' else 100 * 1024**2
        size = request.headers.get('x-content-bytes', '')
        if not size.isdigit() or not 0 < int(size) <= limit:
            raise HTTPException(413, '上传大小超限')
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(sha + '.' + uuid.uuid4().hex + '.part')
        count = 0
        try:
            with part.open('wb') as out:
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > int(size):
                        raise HTTPException(413, '实际上传大小超限')
                    out.write(chunk)
            if count != int(size) or digest(part) != sha:
                raise HTTPException(422, '输入摘要或大小不符')
            # Temporary input remains unpublished until real format checks pass.
            service.media.inspect(part, 'photo' if kind == 'photo' else 'audio', min_duration=.1 if kind == 'audio' else None)
            os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)
        return {'sha256': sha, 'bytes': count}
    @app.post('/v1/jobs', dependencies=protected, status_code=202)
    def submit(body: dict):
        return service.submit(body)
    @app.get('/v1/jobs/{jid}', dependencies=protected)
    def get(jid: str):
        return service.get(jid)
    @app.post('/v1/jobs/{jid}/cancel', dependencies=protected)
    def cancel(jid: str):
        return service.cancel(jid)
    @app.get('/v1/jobs/{jid}/result', dependencies=protected)
    def result(jid: str):
        job = service.get(jid)
        if job['state'] != 'completed':
            raise HTTPException(409, '任务未完成')
        path = (service.root / job['output']['path']).resolve()
        if not path.is_relative_to(service.root) or not path.is_file() or digest(path) != job['output']['sha256']:
            raise HTTPException(422, '输出摘要不符')
        return FileResponse(path, media_type='video/mp4', filename=jid + '.mp4')
    return app
