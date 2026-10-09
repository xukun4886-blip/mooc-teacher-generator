from __future__ import annotations

import copy
import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from mooc_m1.core import Failure, read_json, stamp
from .content import (DEFAULTS, config_patch, effective, find_scene, current, add_version,
                      invalidate, structure, import_scripts, review, audition_key, reject)
from .service import Service


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    action: str
    data: dict = {}


def create_app(config=None, root=None, worker=True):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    if config is None:
        local = root / "config/m2.local.json"
        config = read_json(local if local.is_file() else root / "config/m2.example.json")
    service = Service(config, root)
    store = service.store

    @asynccontextmanager
    async def lifespan(app):
        if worker:
            service.start()
        yield
        service.close()

    app = FastAPI(title="数字人教师 · 内容与视频工作台", version="0.3.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.service = service

    @app.exception_handler(Failure)
    async def failure(request, exc):
        status = 404 if exc.code == "NOT_FOUND" else 409 if exc.code in {"REVISION_CONFLICT", "PROJECT_BUSY", "REVIEW_LOCKED"} else 422
        return JSONResponse({"error": exc.record()}, status_code=status)

    @app.middleware("http")
    async def local_guard(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"error": {"message": "仅允许本机访问"}}, 403)
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            return JSONResponse({"error": {"message": "禁止跨站访问"}}, 403)
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("text/html"):
            # Revalidate the entry page after a local frontend upgrade.
            response.headers["cache-control"] = "no-store"
        return response

    def authorized(request: Request):
        candidate = request.cookies.get("mooc_session", "")
        if not candidate or not secrets.compare_digest(candidate, store.token):
            raise HTTPException(401, "请使用启动器提供的本地访问令牌登录")

    @app.post("/api/session")
    def login(request: Request, body: dict):
        if not secrets.compare_digest(str(body.get("token", "")), store.token):
            raise HTTPException(401, "访问令牌无效")
        response = JSONResponse({"creator": "local-teacher"})
        response.set_cookie("mooc_session", store.token, httponly=True, samesite="strict", max_age=86400)
        return response

    @app.post("/api/session/launch")
    def launch_login(request: Request, body: dict):
        # A short-lived one-use launcher ticket never becomes the session cookie.
        import time
        ticket = getattr(app.state, "launch_ticket", None)
        created = getattr(app.state, "launch_created", 0)
        if not ticket or time.monotonic() - created > 120 or not secrets.compare_digest(str(body.get("ticket", "")), ticket):
            raise HTTPException(401, "启动登录地址已失效，请重新运行启动器")
        app.state.launch_ticket = None
        return login(request, {"token": store.token})

    protected = [Depends(authorized)]

    @app.get('/api/health')
    def health():
        return {'application': 'mooc-workbench', 'version': app.version,
                'worker_alive': bool(service.thread and service.thread.is_alive()),
                'scope': 'local service liveness; does not certify model or teaching quality'}

    @app.post("/api/session/launch-ticket", dependencies=protected)
    def launch_ticket():
        import time
        app.state.launch_ticket = secrets.token_urlsafe(32)
        app.state.launch_created = time.monotonic()
        return {"ticket": app.state.launch_ticket, "expires_seconds": 120}

    @app.get("/api/settings", dependencies=protected)
    def settings():
        return {"defaults": DEFAULTS, "limits_mb": config["limits_mb"], "max_ppt_pages": config.get("max_ppt_pages", 50), "ai": service.ai_health(), "training_enabled": False}

    @app.get("/api/projects", dependencies=protected)
    def projects():
        return store.list()

    @app.post("/api/projects", dependencies=protected)
    def create(body: dict):
        return store.create(body.get("name"), body.get("config"))

    @app.get("/api/projects/{pid}", dependencies=protected)
    def project(pid: str):
        p = store.get(pid)
        result = copy.deepcopy(p)
        for scene in result["scenes"]:
            scene["effective_config"] = effective(p, scene)
            scene["config_sources"] = {k: "scene" if k in scene["overrides"] else "project" if k in p["config"] else "system" for k in DEFAULTS}
            for v in scene['versions']:
                if v.get('teaching_check_state')=='pending':
                    run=store.draft_run(v.get('provenance',{}).get('draft_run_id',''))
                    if run:
                        v['teaching_check_error']=run['stages'].get('teaching',{}).get('error')
        return result

    @app.post("/api/projects/{pid}/copy", dependencies=protected)
    def clone(pid: str):
        return store.clone(pid)

    @app.post('/api/projects/{pid}/photo-server/check', dependencies=protected)
    def photo_server_check(pid: str, body: dict):
        from mooc_cloud.protocol import settings, health
        store.get(pid)
        selected = settings(body, loopback=config.get('cloud_loopback_tunnel', False))
        if selected['mode'] != 'cloud':
            return {'ready': True, 'scope': '本机原有照片处理路径'}
        return health(selected)

    @app.put('/api/projects/{pid}/photo-server', dependencies=protected)
    def photo_server_save(pid: str, body: dict):
        from mooc_cloud.protocol import settings, health, pinned
        selected = settings(body.get('settings'), loopback=config.get('cloud_loopback_tunnel', False))
        # Check connection, version and quote, but never upload or generate here.
        if selected['mode'] == 'cloud':
            selected = pinned(selected, health(selected))
        revision = body.get('revision')
        if type(revision) is not int:
            reject('INPUT_INCOMPATIBLE', '须提供当前项目版本')
        with store.edit(pid, revision) as p:
            with store.connection() as db:
                if store.busy(pid, db):
                    reject('PROJECT_BUSY', '等待当前任务结束后切换人物服务器')
            before = copy.deepcopy(p.get('photo_execution', {'mode': 'local'}))
            p['photo_execution'] = selected
            p.setdefault('photo_execution_history', []).append({'at': stamp(), 'before': before, 'after': copy.deepcopy(selected)})
        return store.get(pid)

    @app.delete("/api/projects/{pid}", dependencies=protected)
    def delete(pid: str):
        store.delete(pid)
        return {"deleted": True}

    @app.post("/api/projects/{pid}/commands", dependencies=protected)
    def command(pid: str, body: Command):
        if any(j['kind'] == 'course' and j['state'] in {'queued', 'running'} for j in store.jobs(pid)):
            reject('PROJECT_BUSY', '正在自动制作，请等待完成后修订')
        data = body.data
        required = {"checks": {"scene_id", "checks"}, "category": {"category"}, "adopt_ai": {"scene_id", "version_id"}, "script": {"scene_id", "display_text"}, "notes": {"scene_id"}, "rollback": {"scene_id", "version_id"}, "review": {"scene_id", "checks", "note"}, "page_config": {"scene_ids", "overrides"}, "listen_review": {"scene_id", "checks", "note"}, "structure": {"action"}, "import": {"schema_version", "pages"}, "config": set()}
        if body.action not in required or not required[body.action].issubset(data):
            reject("INPUT_INCOMPATIBLE", "操作字段缺失或操作不支持")
        if "scene_ids" in data and (not isinstance(data["scene_ids"], list) or any(not isinstance(i, str) for i in data["scene_ids"])):
            reject("INPUT_INCOMPATIBLE", "scene_ids 须为字符串数组")
        if body.action == "structure":
            req = {"reorder": {"scene_ids"}, "skip": {"scene_id", "skipped"}, "merge": {"scene_ids"}, "split": {"scene_id", "parts"}, "plan": {"scene_id", "kind"}, "play_page": {"scene_id", "source_page_id"}}
            if data["action"] not in req or not req[data["action"]].issubset(data):
                reject("INPUT_INCOMPATIBLE", "结构操作字段不完整")
        if body.action == "listen_review" and (not isinstance(data["note"], str) or not isinstance(data["checks"], dict)):
            reject("INPUT_INCOMPATIBLE", "试听核查记录格式无效")
        with store.edit(pid, body.revision) as p:
            if body.action == "config":
                values = config_patch(data)
                old_mode = effective(p, {"overrides": {}})["mode"]
                p["config"].update(values)
                p["config_version"] += 1
                p["name"] = p["config"].get("course_name", p["name"])
                if "mode" in values and old_mode != values["mode"]:
                    p.setdefault("mode_history", []).append({"from": old_mode, "to": values["mode"], "at": stamp(), "actor": "local-teacher"})
                for scene in p["scenes"]:
                    if "terms" in values and "terms" not in scene["overrides"] and current(scene):
                        v = current(scene)
                        add_version(p, scene, "manual", v["raw_display"], v["raw_reading"], {"derived_from": v["id"], "change": "terms"}, copy.deepcopy(v["checks"]))
                    elif set(values) & {"speed", "pause_before", "pause_after"} - set(scene["overrides"]):
                        invalidate(scene, review=False)
                    else:
                        scene["media_state"] = "needs_recompose"
            elif body.action == "structure":
                structure(p, data)
            elif body.action == "import":
                import_scripts(p, data)
            elif body.action == "script":
                scene = find_scene(p, data["scene_id"])
                old = current(scene)
                add_version(p, scene, "manual", data["display_text"], data.get("reading_text"), {"edited_from": scene["current_version"]}, copy.deepcopy(old["checks"]) if old else None)
            elif body.action == "category":
                if data["category"] not in {"course", "development"}:
                    reject("INPUT_INCOMPATIBLE", "项目分类无效")
                p["category"] = data["category"]
            elif body.action == "checks":
                scene = find_scene(p, data["scene_id"])
                v = current(scene)
                checks = data["checks"]
                if not v or not isinstance(checks, dict) or set(checks) != {"knowledge_points", "questions", "terms", "pending"} or any(not isinstance(x, list) for x in checks.values()):
                    reject("INPUT_INCOMPATIBLE", "请先编写讲稿，核查表字段须完整")
                add_version(p, scene, "manual", v["raw_display"], v["raw_reading"], {"edited_from": v["id"], "change": "teaching_checks"}, copy.deepcopy(checks))
            elif body.action == "adopt_ai":
                scene = find_scene(p, data["scene_id"])
                old = next((v for v in scene["versions"] if v["id"] == data["version_id"] and v["mode"] == "ai"), None)
                if not old:
                    reject("NOT_FOUND", "AI 候选版本不存在")
                v=add_version(p, scene, "rollback", old["raw_display"], old["raw_reading"], {**copy.deepcopy(old['provenance']),"adopted_ai": old["id"]}, copy.deepcopy(old["checks"]),reading_normalized=bool(old['provenance'].get('reading_contract')))
                if old.get('teaching_check_state'):v['teaching_check_state']=old['teaching_check_state']
                scene.pop("ai_candidate", None)
            elif body.action == "notes":
                scene = find_scene(p, data["scene_id"])
                notes = "\n".join(s["notes_original"] for s in p["slides"] if s["source_page_id"] in scene["source_page_ids"])
                titles = {s["body"].split("\n")[0].strip() for s in p["slides"] if s["source_page_id"] in scene["source_page_ids"] and s["body"].strip()}
                if not notes.strip() or notes.strip() in titles or notes.strip().lower() in {"备注", "notes", "click to add notes", "单击此处添加备注"}:
                    reject("NOTES_EMPTY", "备注为空、占位或只有标题，请补充或选择其他入口", scene["id"])
                add_version(p, scene, "notes", notes, provenance={"source_page_ids": scene["source_page_ids"], "literal_original": True})
            elif body.action == "rollback":
                scene = find_scene(p, data["scene_id"])
                old = next((v for v in scene["versions"] if v["id"] == data["version_id"]), None)
                if old is None:
                    reject("NOT_FOUND", "讲稿版本不存在")
                v=add_version(p, scene, "rollback", old["raw_display"], old["raw_reading"], {**copy.deepcopy(old['provenance']),"rollback_to": old["id"]}, copy.deepcopy(old["checks"]),reading_normalized=bool(old['provenance'].get('reading_contract')))
                if old.get('teaching_check_state'):v['teaching_check_state']=old['teaching_check_state']
            elif body.action == "review":
                review(find_scene(p, data["scene_id"]), data["checks"], data["note"])
            elif body.action == "page_config":
                ids = data["scene_ids"]
                if not ids or len(ids) != len(set(ids)):
                    reject("INPUT_INCOMPATIBLE", "请选择明确且不重复的应用范围")
                values = config_patch(data["overrides"], page=True)
                for sid in ids:
                    scene = find_scene(p, sid)
                    old = copy.deepcopy(scene["overrides"])
                    scene["overrides"] = values if data.get("replace") else {**old, **values}
                    scene["config_version"] += 1
                    if old.get("terms") != scene["overrides"].get("terms") and current(scene):
                        v = current(scene)
                        add_version(p, scene, "manual", v["raw_display"], v["raw_reading"], {"derived_from": v["id"], "change": "terms"}, copy.deepcopy(v["checks"]))
                    elif any(old.get(k) != scene["overrides"].get(k) for k in ["speed", "pause_before", "pause_after"]):
                        invalidate(scene, review=False)
                    else:
                        scene["media_state"] = "needs_recompose"
            elif body.action == "listen_review":
                scene = find_scene(p, data["scene_id"])
                audio = scene.get("audition")
                if not audio or audio["stale"] or audio["input_key"] != audition_key(p, scene):
                    reject("AUDITION_REQUIRED", "请先生成当前版本试听")
                required = {"timbre", "pronunciation", "no_omission", "no_repetition"}
                if set(data.get("checks", {})) != required or not all(v is True for v in data["checks"].values()) or not data.get("note", "").strip():
                    reject("REVIEW_REQUIRED", "请完整核查音色、读法、漏句和重复并填写记录")
                audio["human_review"] = {"reviewer": "local-teacher", "checks": data["checks"], "note": data["note"], "at": stamp()}
            else:
                reject("INPUT_INCOMPATIBLE", "编辑操作不支持")
        return project(pid)

    @app.post("/api/projects/{pid}/assets/{role}", dependencies=protected)
    def upload(pid: str, role: str, file: UploadFile = File(...), authorization: str = Form(...), teacher_id: str = Form(""), revision: int = Form(...)):
        try:
            return service.accept_upload(pid, role, file.filename or "", file.file, authorization, teacher_id, revision)
        finally:
            file.file.close()

    @app.post("/api/projects/{pid}/assets/{role}/selection", dependencies=protected)
    def selection(pid: str, role: str, body: dict):
        return service.select(pid, role, body)

    @app.get("/api/projects/{pid}/files/{relative:path}", dependencies=protected)
    def media(pid: str, relative: str):
        store.get(pid)
        path = store.file(pid, relative)
        if not path.is_file():
            reject("NOT_FOUND", "文件不存在")
        return FileResponse(path, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/projects/{pid}/jobs", dependencies=protected)
    def jobs(pid: str):
        # Polling needs status and locators, not every page's full AI context.
        result = store.jobs(pid)
        result = [j for j in result if j['kind'] not in {'m3', 'course'}]
        for job in result:
            job["payload"] = {k: v for k, v in job["payload"].items() if k in {"scene_id", "asset_id", "role", "batch_id", "version_id", "draft_preview", "input_key"}}
        return result

    @app.post("/api/projects/{pid}/scenes/{sid}/ai", dependencies=protected)
    def ai(pid: str, sid: str, body: dict):
        return service.queue_ai(pid, body["revision"], [sid])["jobs"][0]

    @app.post('/api/projects/{pid}/scenes/{sid}/teaching-check', dependencies=protected)
    def teaching_check(pid: str, sid: str, body: dict):
        return service.queue_teaching(pid,sid,body['revision'])

    @app.post("/api/projects/{pid}/ai-batches", dependencies=protected)
    def ai_batch(pid: str, body: dict):
        return service.queue_ai(pid, body["revision"], body.get("scene_ids"), body.get("retry_failed") is True)

    @app.post("/api/projects/{pid}/scenes/{sid}/audition", dependencies=protected)
    def audition(pid: str, sid: str, body: dict):
        return service.queue_audition(pid, sid, body["revision"], body.get("draft_preview") is True)

    @app.post("/api/projects/{pid}/preflight", dependencies=protected)
    def preflight(pid: str):
        report = service.preflight(store.get(pid))
        store.save_preflight(pid, report)
        return report

    @app.post("/api/projects/{pid}/snapshots", dependencies=protected)
    def freeze(pid: str, body: dict):
        p = store.get(pid)
        if p["revision"] != body["revision"]:
            reject("REVISION_CONFLICT", "项目已更新")
        report = service.preflight(p)
        if not report["ready"]:
            return JSONResponse({"error": {"code": "PREFLIGHT_BLOCKED", "message": "内容预检未通过"}, "preflight": report}, 422)
        for scene in p["scenes"]:
            scene["effective_config"] = effective(p, scene)
        return store.snapshot(p, report)

    @app.get("/api/projects/{pid}/snapshots/{snapshot_id}", dependencies=protected)
    def snapshot(pid: str, snapshot_id: str):
        return store.get_snapshot(pid, snapshot_id)

    @app.get("/api/projects/{pid}/import-template", dependencies=protected)
    def template(pid: str):
        p = store.get(pid)
        return {"schema_version": "m2.scripts.v1", "pages": [{"source_page_id": s["source_page_id"], "display_text": "", "reading_text": ""} for s in p["slides"]]}

    @app.get('/api/projects/{pid}/m1-review', dependencies=protected)
    def m1_review(pid: str):
        return service.m3.review.state(pid)

    @app.post('/api/projects/{pid}/m1-review', dependencies=protected)
    def save_m1_review(pid: str, body: dict):
        return service.m3.review.save(pid, body)

    @app.get('/api/projects/{pid}/m1-review/media/{media_id}', dependencies=protected)
    def review_media(pid: str, media_id: str):
        item = next((a for a in service.m3.review.gallery(pid) if a['id'] == media_id), None)
        if not item or not Path(item['path']).is_file():
            reject('NOT_FOUND', '评审素材不存在')
        from mooc_m1.core import digest
        if digest(item['path']) != item['sha256']:
            reject('ASSET_CHANGED', '评审素材摘要不一致')
        return FileResponse(service.m3.review.playback(pid, item), headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/projects/{pid}/snapshots', dependencies=protected)
    def snapshots(pid: str):
        return service.m3.snapshot_list(pid)

    @app.post('/api/projects/{pid}/media-jobs', dependencies=protected, status_code=202)
    def submit_media(pid: str, body: dict):
        return service.m3.submit(pid, body)

    @app.get('/api/projects/{pid}/snapshots/{snapshot_id}/layout-review', dependencies=protected)
    def layout_review(pid: str, snapshot_id: str):
        return service.m3.layouts(pid, snapshot_id)

    @app.post('/api/projects/{pid}/snapshots/{snapshot_id}/layout-review', dependencies=protected)
    def save_layout_review(pid: str, snapshot_id: str, body: dict):
        return service.m3.save_layout(pid, snapshot_id, body)

    @app.get('/api/projects/{pid}/media-jobs', dependencies=protected)
    def media_jobs(pid: str):
        return service.m3.list(pid)

    @app.get('/api/projects/{pid}/media-jobs/{jid}', dependencies=protected)
    def media_job(pid: str, jid: str):
        return service.m3.public(service.m3.get(pid, jid))

    @app.post('/api/projects/{pid}/media-jobs/{jid}/cancel', dependencies=protected)
    def cancel_media(pid: str, jid: str):
        return service.m3.cancel(pid, jid)

    @app.post('/api/projects/{pid}/media-jobs/{jid}/retry', dependencies=protected, status_code=202)
    def retry_media(pid: str, jid: str):
        return service.m3.retry(pid, jid)

    @app.post('/api/projects/{pid}/media-jobs/{jid}/review', dependencies=protected)
    def confirm_sample(pid: str, jid: str, body: dict):
        return service.m3.sample_review(pid, jid, body)

    @app.get('/api/projects/{pid}/media-jobs/{jid}/exports/{kind}', dependencies=protected)
    def export_media(pid: str, jid: str, kind: str):
        job = service.m3.get(pid, jid)
        result = job.get('result')
        if job['state'] != 'completed' or not result or kind not in result['exports']:
            reject('NOT_FOUND', '有效成果尚未就绪')
        path = service.m3.verify(pid, result['exports'][kind], result['file_hashes'][kind])
        return FileResponse(path, filename=('draft-' if result['preview'] else '') + path.name, headers={'Cache-Control': 'private, no-store'})

    @app.post('/api/projects/{pid}/generate', dependencies=protected, status_code=202)
    def generate_course(pid: str):
        return service.course.submit(pid)

    @app.get('/api/projects/{pid}/generation', dependencies=protected)
    def course_generation(pid: str):
        store.get(pid)
        return service.course.latest(pid)

    @app.post('/api/projects/{pid}/generation/{jid}/retry', dependencies=protected, status_code=202)
    def retry_course(pid: str, jid: str):
        return service.course.retry(pid, jid)

    @app.post('/api/projects/{pid}/generation/{jid}/confirm', dependencies=protected)
    def confirm_course(pid: str, jid: str, body: dict):
        return service.course.confirm(pid, jid, body)

    @app.post('/api/projects/{pid}/quick-assets/{role}', dependencies=protected)
    def quick_upload(pid: str, role: str, file: UploadFile = File(...), revision: int = Form(...)):
        try:
            p = store.get(pid)
            peer_role = effective(p, {'overrides': {}})['mode'] if role == 'reference_audio' else 'reference_audio'
            teacher_id = (p['assets'].get(peer_role) or {}).get('teacher_id') or 'course-teacher'
            result = service.accept_upload(pid, role, file.filename or '', file.file,
                '用户通过上传入口确认有权用于本地课程制作；课件图文可发送至已配置讲稿服务，人物和语音仅在本机处理；不用于训练',
                teacher_id, revision, fork_ppt=True)
            if role in {'photo', 'video'}:
                with store.edit(pid) as p:
                    old_mode = effective(p, {'overrides': {}})['mode']
                    p['config']['mode'] = role
                    p['config_version'] += 1
                    if old_mode != role:
                        p.setdefault('mode_history', []).append({'from': old_mode, 'to': role, 'at': stamp(), 'actor': 'local-teacher', 'reason': '用户上传人物形象'})
            return result
        finally:
            file.file.close()

    @app.post('/api/projects/{pid}/asset-jobs/{jid}/retry', dependencies=protected, status_code=202)
    def retry_asset(pid: str, jid: str):
        j = next((j for j in store.jobs(pid) if j['id'] == jid), None)
        if not j or j['kind'] not in {'asset', 'derive'} or j['state'] != 'failed':
            reject('RETRY_BLOCKED', '只有失败的素材处理可以重试')
        with store.edit(pid) as p:
            a = p['assets'].get(j['payload']['role'])
            if not a or a['id'] != j['payload']['asset_id'] or store.busy(pid):
                reject('PROJECT_BUSY', '素材已替换或正在处理中')
            a.update(state='queued', error=None)
        return store.job(pid, j['kind'], copy.deepcopy(j['payload']))

    dist = root / "frontend/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="workbench")
    return app
