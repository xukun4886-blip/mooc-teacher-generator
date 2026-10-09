from __future__ import annotations

import copy
import json
import os
import secrets
import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from mooc_m1.core import stamp, digest
from .content import uid, reject, DEFAULTS, config_patch


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            from mooc_m1.core import run
            # All project, session and model files inherit a private Windows ACL.
            sid = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"], 15)["stdout"].strip()
            if not sid.startswith("S-1-"):
                reject("STORAGE_ACCESS_FAILED", "无法取得当前 Windows 用户 SID")
            run(["icacls", self.root, "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"], 15)
        self.db = self.root / "content.sqlite3"
        with self.connection() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, revision INTEGER, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT, state TEXT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, project_id TEXT, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS draft_runs(id TEXT PRIMARY KEY, project_id TEXT, scene_id TEXT, data TEXT NOT NULL);
            """)
        token = self.root / ".session-token"
        if not token.exists():
            token.write_text(secrets.token_urlsafe(32), encoding="ascii")
        self.token = token.read_text(encoding="ascii").strip()

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def list(self):
        with self.connection() as db:
            projects = [json.loads(r[0]) for r in db.execute("SELECT data FROM projects")]
        return [{**{k: p[k] for k in ["id", "revision", "name", "updated_at", "state", "source_project_id"]}, "engineering_only": p.get("engineering_only", False), "category": p.get("category", "development" if p.get("engineering_only") else "course")} for p in sorted(projects, key=lambda p: p["updated_at"], reverse=True)]

    def create(self, name, values=None):
        if not isinstance(name, str) or not name.strip() or len(name) > 300:
            reject("INPUT_INCOMPATIBLE", "课程名不能为空或过长")
        project = {"id": uid(), "revision": 1, "config_version": 1, "name": name, "creator": "local-teacher",
                   "source_project_id": None, "created_at": stamp(), "updated_at": stamp(), "state": "editing",
                   "config": {"course_name": name, **config_patch(values or {})}, "assets": {}, "slides": [], "scenes": [],
                   "preflight": None, "training_enabled": False}
        self.folder(project["id"]).mkdir(parents=True)
        with self.connection() as db:
            db.execute("INSERT INTO projects VALUES(?,?,?)", (project["id"], 1, json.dumps(project, ensure_ascii=False)))
        return project

    def get(self, project_id, db=None):
        if db is None:
            with self.connection() as conn:
                return self.get(project_id, conn)
        row = db.execute("SELECT data FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            reject("NOT_FOUND", "项目不存在", project_id)
        return json.loads(row[0])

    @contextmanager
    def edit(self, project_id, revision=None):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            project = self.get(project_id, db)
            if revision is not None and revision != project["revision"]:
                reject("REVISION_CONFLICT", "项目已更新，请重新加载后保存", project_id)
            yield project
            project["revision"] += 1
            project["updated_at"] = stamp()
            project["state"] = "editing"
            project["preflight"] = None
            db.execute("UPDATE projects SET revision=?,data=? WHERE id=?", (project["revision"], json.dumps(project, ensure_ascii=False), project_id))

    def folder(self, project_id):
        try:
            if str(__import__("uuid").UUID(project_id)) != project_id:
                raise ValueError()
        except (ValueError, TypeError):
            reject("INPUT_INCOMPATIBLE", "项目标识无效")
        return self.root / "projects" / project_id

    def file(self, project_id, relative):
        base = self.folder(project_id)
        target = (base / relative).resolve()
        if not target.is_relative_to(base.resolve()) or target == base or any(p.is_symlink() or (os.name == "nt" and p.exists() and bool(p.lstat().st_file_attributes & 1024)) for p in [base, *target.parents] if p.is_relative_to(base)):
            reject("INPUT_INCOMPATIBLE", "文件路径越界或重解析点")
        return target

    def busy(self, project_id, db=None):
        if db is None:
            with self.connection() as conn:
                return self.busy(project_id, conn)
        return bool(db.execute("SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')", (project_id,)).fetchone())

    def clone(self, project_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            original = self.get(project_id, db)
            if self.busy(project_id, db):
                reject("PROJECT_BUSY", "等待当前素材/试听任务完成后复制")
            project = copy.deepcopy(original)
            # A copy retains provenance, but external-material consent is per course.
            if project.get('photo_execution', {}).get('mode') == 'cloud':
                project['photo_execution'] = {'mode': 'local'}
            project.update(id=uid(), revision=1, name=original["name"] + " 副本", source_project_id=project_id, created_at=stamp(), updated_at=stamp(), preflight=None)
            project["config"]["course_name"] = project["name"]
            # Each project owns a physical copy, including audio and original pages.
            shutil.copytree(self.folder(project_id), self.folder(project["id"]))
            for scene in project["scenes"]:
                scene["id"] = uid()
            db.execute("INSERT INTO projects VALUES(?,?,?)", (project["id"], 1, json.dumps(project, ensure_ascii=False)))
        return project

    def fork_with_ppt(self, project_id, revision, asset):
        """Own copies of teacher inputs; never carry old page mappings or reviews."""
        new_id = uid()
        folder = self.folder(new_id).resolve()
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                original = self.get(project_id, db)
                if original['revision'] != revision:
                    reject('REVISION_CONFLICT', '项目已更新，请重新加载后更换课件')
                if self.busy(project_id, db):
                    reject('PROJECT_BUSY', '等待当前任务完成后更换课件')
                name = Path(asset['filename']).stem[:300] or '新课程'
                now = stamp()
                project = {'id': new_id, 'revision': 1, 'config_version': 1, 'name': name,
                    'creator': original.get('creator', 'local-teacher'), 'source_project_id': project_id,
                    'created_at': now, 'updated_at': now, 'state': 'editing',
                    'config': copy.deepcopy(original['config']), 'assets': {}, 'slides': [], 'scenes': [],
                    'preflight': None, 'training_enabled': False,
                    'category': original.get('category', 'course'), 'engineering_only': original.get('engineering_only', False),
                    'creation_reason': '用户重新选择课程PPT，保留原课程与审核记录'}
                project['config']['course_name'] = name
                mode = project['config'].get('mode', 'photo')
                for role in [mode, 'reference_audio']:
                    old = original['assets'].get(role)
                    if not old or old['state'] != 'ready':
                        continue
                    item = copy.deepcopy(old)
                    item.update(id=uid(), source_project_id=project_id, source_asset_id=old['id'])
                    for key in ['original', 'selected']:
                        source = self.file(project_id, old[key])
                        expected = old.get('selected_sha256', old['sha256']) if key == 'selected' else old['sha256']
                        if digest(source) != expected:
                            reject('INPUT_CHANGED', '教师素材文件已变化，请重新上传')
                        if key == 'selected' and old[key] == old['original']:
                            item[key] = item['original']
                            continue
                        relative = f"assets/{item['id']}/{key}{source.suffix}"
                        target = self.file(new_id, relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, target)
                        item[key] = relative
                    project['assets'][role] = item
                target = self.file(new_id, asset['original'])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.file(project_id, asset['original']), target)
                project['assets']['pptx'] = copy.deepcopy(asset)
                job = {'id': uid(), 'project_id': new_id, 'kind': 'asset',
                    'payload': {'role': 'pptx', 'asset_id': asset['id']}, 'state': 'queued',
                    'stage': 'queued', 'created_at': now, 'result': None, 'error': None}
                db.execute('INSERT INTO projects VALUES(?,?,?)', (new_id, 1, json.dumps(project, ensure_ascii=False)))
                db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (job['id'], new_id, 'queued', json.dumps(job, ensure_ascii=False)))
            return {**job, 'source_project_id': project_id}
        except BaseException:
            # Only this unpublished, UUID-owned folder can have been created here.
            if folder.exists():
                if not folder.is_relative_to((self.root / 'projects').resolve()):
                    raise RuntimeError('Unexpected fork cleanup path')
                for path in [folder, *folder.rglob('*')]:
                    if path.is_symlink() or (os.name == 'nt' and bool(path.lstat().st_file_attributes & 1024)):
                        raise RuntimeError('Unsafe fork cleanup path')
                shutil.rmtree(folder)
            raise

    def delete(self, project_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self.get(project_id, db)
            if self.busy(project_id, db):
                reject("PROJECT_BUSY", "项目有运行或排队任务，请完成后删除")
            folder = self.folder(project_id).resolve()
            if not folder.is_relative_to((self.root / "projects").resolve()) or folder.is_symlink():
                reject("INPUT_INCOMPATIBLE", "删除路径无效")
            # Validate every descendant before recursive deletion, on Windows too.
            for path in [folder, *folder.rglob("*")]:
                if path.is_symlink() or (os.name == "nt" and bool(path.lstat().st_file_attributes & 1024)):
                    reject("INPUT_INCOMPATIBLE", "删除范围含重解析点")
            shutil.rmtree(folder)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='m3_cache'").fetchone():
                db.execute('DELETE FROM m3_cache WHERE project_id=?', (project_id,))
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='m3_reviews'").fetchone():
                for row in db.execute('SELECT key,data FROM m3_reviews').fetchall():
                    value = json.loads(row['data'])
                    if row['key'] == 'm1:' + project_id or value.get('project_id') == project_id:
                        db.execute('DELETE FROM m3_reviews WHERE key=?', (row['key'],))
                        if db.execute("SELECT 1 FROM sqlite_master WHERE name='m3_review_history'").fetchone():
                            db.execute('DELETE FROM m3_review_history WHERE key=?', (row['key'],))
            db.execute("DELETE FROM snapshots WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM draft_runs WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM jobs WHERE project_id=?", (project_id,))
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def job(self, project_id, kind, payload):
        job = {"id": uid(), "project_id": project_id, "kind": kind, "payload": payload, "state": "queued", "stage": "queued", "created_at": stamp(), "result": None, "error": None}
        with self.connection() as db:
            self.get(project_id, db)
            db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job["id"], project_id, "queued", json.dumps(job, ensure_ascii=False)))
        return job

    def jobs(self, project_id):
        self.get(project_id)
        with self.connection() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM jobs WHERE project_id=? ORDER BY rowid DESC", (project_id,))]

    def enqueue_ai(self, project_id, revision, items):
        # Revision and duplicate checks plus the whole batch insert are atomic.
        batch_id = uid()
        jobs = []
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.get(project_id, db)["revision"] != revision:
                reject("REVISION_CONFLICT", "项目已更新，请重新加载")
            active = [json.loads(r[0]) for r in db.execute("SELECT data FROM jobs WHERE project_id=? AND state IN ('queued','running')", (project_id,))]
            if any(j["kind"] == "ai" and j["payload"]["scene_id"] in {x["scene_id"] for x in items} for j in active):
                reject("PROJECT_BUSY", "选中页面已有 AI 任务，请等待完成")
            for item in items:
                job = {"id": uid(), "project_id": project_id, "kind": "ai", "payload": {**item, "batch_id": batch_id}, "state": "queued", "stage": "queued", "created_at": stamp(), "result": None, "error": None}
                db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job["id"], project_id, "queued", json.dumps(job, ensure_ascii=False)))
                jobs.append(job)
        return {"batch_id": batch_id, "jobs": jobs, "total": len(jobs)}

    def update_job(self, job):
        with self.connection() as db:
            db.execute("UPDATE jobs SET state=?,data=? WHERE id=?", (job["state"], json.dumps(job, ensure_ascii=False), job["id"]))

    def draft_run(self, run_id, value=None, db=None):
        if db is None:
            with self.connection() as conn:
                return self.draft_run(run_id, value, conn)
        if value is not None:
            db.execute('INSERT OR IGNORE INTO draft_runs VALUES(?,?,?,?)',
                       (run_id, value['project_id'], value['scene_id'], json.dumps(value, ensure_ascii=False)))
        row = db.execute('SELECT data FROM draft_runs WHERE id=?', (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_draft_run(self, value, db=None):
        if db is None:
            with self.connection() as conn:
                return self.save_draft_run(value, conn)
        db.execute('UPDATE draft_runs SET data=? WHERE id=?', (json.dumps(value, ensure_ascii=False), value['id']))

    def claim(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return None
            job = json.loads(row[0])
            job.update(state="running", stage="starting", started_at=stamp())
            db.execute("UPDATE jobs SET state='running',data=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job["id"]))
            return job

    def recover(self):
        with self.connection() as db:
            for row in db.execute("SELECT data FROM jobs WHERE state='running'").fetchall():
                job = json.loads(row[0])
                if job['kind'] == 'm3':
                    continue
                job.update(state="failed", stage="interrupted", error={"code": "WORKER_INTERRUPTED", "message": "服务重启中断任务，请重新运行；没有把部分输出标记成功"})
                db.execute("UPDATE jobs SET state='failed',data=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job["id"]))

    def snapshot(self, project, report):
        value = copy.deepcopy(project)
        value.update(schema_version="m2.snapshot.v1", snapshot_id=uid(), frozen_at=stamp(), preflight=report)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.get(project["id"], db)["revision"] != project["revision"]:
                reject("REVISION_CONFLICT", "预检期间项目已修改，请重试")
            db.execute("INSERT INTO snapshots VALUES(?,?,?)", (value["snapshot_id"], project["id"], json.dumps(value, ensure_ascii=False)))
        return value

    def save_preflight(self, project_id, report):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            p = self.get(project_id, db)
            if p["revision"] != report["revision"]:
                reject("REVISION_CONFLICT", "预检期间项目已修改，请重试")
            p["preflight"] = report
            p["state"] = "content_ready" if report["ready"] else "editing"
            db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(p, ensure_ascii=False), project_id))

    def get_snapshot(self, project_id, snapshot_id):
        self.get(project_id)
        with self.connection() as db:
            row = db.execute("SELECT data FROM snapshots WHERE id=? AND project_id=?", (snapshot_id, project_id)).fetchone()
        if not row:
            reject("NOT_FOUND", "审核快照不存在")
        return json.loads(row[0])
