from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid

from mooc_m1.core import Failure, stamp


DEFAULTS = {"course_name": "新课程", "chapter": "", "audience": "", "detail": "标准",
            "target_seconds": 90, "resolution": "1080p", "subtitles": True, "mode": "photo",
            "show_teacher": True, "position": "bottom-right", "size": 0.25,
            "speed": 1.0, "pause_before": 0.0, "pause_after": 0.0, "terms": {}, "layout": "overlay"}
PAGE_KEYS = {"show_teacher", "position", "size", "speed", "pause_before", "pause_after", "terms", "target_seconds", "layout"}
PAUSE = re.compile(r"\{\{pause:([0-9]+(?:\.[0-9]+)?)\}\}")


def uid():
    return str(uuid.uuid4())


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def reject(code, message, source=None, remedy=None):
    raise Failure(code, message, source, remedy)


def config_patch(values, page=False):
    if not isinstance(values, dict) or set(values) - (PAGE_KEYS if page else set(DEFAULTS)):
        reject("INPUT_INCOMPATIBLE", "配置字段不支持")
    for key, value in values.items():
        if key in {"size", "speed", "pause_before", "pause_after", "target_seconds"}:
            bounds = {"size": (.1, .6), "speed": (.5, 2), "pause_before": (0, 10), "pause_after": (0, 10), "target_seconds": (1, 1800)}[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not bounds[0] <= value <= bounds[1]:
                reject("INPUT_INCOMPATIBLE", f"{key} 超出范围 {bounds}")
        elif key in {"show_teacher", "subtitles"} and not isinstance(value, bool):
            reject("INPUT_INCOMPATIBLE", f"{key} 应为布尔值")
        elif key == "terms":
            if not isinstance(value, dict) or len(value) > 200 or any(not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip() for k, v in value.items()):
                reject("INPUT_INCOMPATIBLE", "术语表必须是非空术语与读法的映射")
        elif key in {"mode", "position", "resolution", "detail", "layout"}:
            choices = {"mode": {"photo", "video"}, "position": {"bottom-right", "bottom-left", "top-right", "top-left"}, "resolution": {"720p", "1080p"}, "detail": {"简略", "标准", "详细"}, "layout": {"overlay", "sidebar"}}
            if value not in choices[key]:
                reject("INPUT_INCOMPATIBLE", f"{key} 选项不支持")
        elif key in {"course_name", "chapter", "audience"} and (not isinstance(value, str) or len(value) > 300):
            reject("INPUT_INCOMPATIBLE", f"{key} 文本无效")
    return copy.deepcopy(values)


def effective(project, scene):
    result = copy.deepcopy(DEFAULTS)
    result.update(project["config"])
    result.update(scene["overrides"])
    return result


def speech(text, terms):
    """Only {{pause:N}} is a directive. Mathematical brackets stay literal."""
    clean, events, last = "", [], 0
    for match in PAUSE.finditer(text):
        clean += text[last:match.start()]
        seconds = float(match[1])
        if not 0 <= seconds <= 10:
            reject("INPUT_INCOMPATIBLE", "单次停顿必须在 0–10 秒之间")
        events.append({"type": "pause", "offset": len(clean), "seconds": seconds})
        last = match.end()
    clean += text[last:]
    if "{{pause:" in clean:
        reject("INPUT_INCOMPATIBLE", "停顿语法错误，请使用 {{pause:1.0}}")
    if terms:
        pattern = re.compile("|".join(re.escape(k) for k in sorted(terms, key=len, reverse=True)))
        # Translate offsets as each section is replaced, without cascading replacements.
        final, cursor, converted = "", 0, []
        for event in events:
            final += pattern.sub(lambda m: terms[m[0]], clean[cursor:event["offset"]])
            converted.append({**event, "offset": len(final)})
            cursor = event["offset"]
        final += pattern.sub(lambda m: terms[m[0]], clean[cursor:])
        return final, converted
    return clean, events


def current(scene):
    return next((v for v in scene["versions"] if v["id"] == scene["current_version"]), None)


def find_scene(project, scene_id):
    if not isinstance(scene_id, str):
        reject("INPUT_INCOMPATIBLE", "片段标识必须是字符串")
    item = next((s for s in project["scenes"] if s["id"] == scene_id), None)
    if item is None:
        reject("NOT_FOUND", "片段不存在", scene_id)
    return item


def invalidate(scene, review=True):
    if review:
        scene["confirmed"] = None
    if scene.get("audition"):
        scene["audition"]["stale"] = True
    scene["media_state"] = "needs_update"


def add_version(project, scene, mode, display, reading=None, provenance=None, checks=None, reading_normalized=False):
    if mode not in {"ai", "notes", "external", "manual", "rollback"}:
        reject("INPUT_INCOMPATIBLE", "讲稿来源无效")
    if not isinstance(display, str) or len(display) > 30000 or (reading is not None and (not isinstance(reading, str) or len(reading) > 30000)):
        reject("INPUT_INCOMPATIBLE", "讲稿文本无效或过长")
    clean_display, _ = speech(display, {})
    spoken, events = speech(display if reading is None else reading, {} if reading_normalized else effective(project, scene)["terms"])
    version = {"id": uid(), "number": len(scene["versions"]) + 1, "mode": mode,
               "raw_display": display, "raw_reading": display if reading is None else reading,
               "display_text": clean_display, "reading_text": spoken, "control_events": events,
               "provenance": provenance or {}, "created_at": stamp(), "author": "local-teacher",
               "checks": checks or {"knowledge_points": [], "questions": [], "terms": [], "pending": []},
               "teacher_review": None}
    scene["versions"].append(version)
    scene["current_version"] = version["id"]
    scene["mode"] = mode
    invalidate(scene)
    return version


def new_scene(source_ids, kind="lecture"):
    return {"id": uid(), "source_page_ids": list(source_ids), "play_page_id": source_ids[0],
            "kind": kind, "skipped": False, "mode": "manual", "versions": [], "current_version": None,
            "confirmed": None, "overrides": {}, "config_version": 1, "audition": None, "media_state": "needs_update"}


def check_mapping(project):
    valid = {s["source_page_id"] for s in project["slides"]}
    ids = [s["id"] for s in project["scenes"]]
    if len(ids) != len(set(ids)):
        reject("MAPPING_INVALID", "片段标识重复")
    for scene in project["scenes"]:
        sources = scene["source_page_ids"]
        if not sources or len(sources) != len(set(sources)) or set(sources) - valid or scene["play_page_id"] not in sources:
            reject("MAPPING_INVALID", "来源页或播放页映射无效", scene["id"])


def structure(project, operation):
    action = operation.get("action")
    if action == "reorder":
        order = operation.get("scene_ids", [])
        if len(order) != len(project["scenes"]) or set(order) != {s["id"] for s in project["scenes"]}:
            reject("MAPPING_INVALID", "重排必须包含每个片段且仅一次")
        project["scenes"] = [find_scene(project, i) for i in order]
    elif action == "skip":
        scene = find_scene(project, operation["scene_id"])
        scene["skipped"] = bool(operation["skipped"])
    elif action == "merge":
        ids = operation.get("scene_ids", [])
        if len(ids) < 2 or len(set(ids)) != len(ids):
            reject("MAPPING_INVALID", "合并至少选择两个不同片段")
        items = [find_scene(project, i) for i in ids]
        indexes = [project["scenes"].index(s) for s in items]
        if indexes != list(range(min(indexes), max(indexes) + 1)):
            reject("MAPPING_INVALID", "合并范围必须按播放顺序相邻")
        sources = list(dict.fromkeys(i for s in items for i in s["source_page_ids"]))
        merged = new_scene(sources)
        merged["merged_from"] = copy.deepcopy(items)
        versions = [current(s) for s in items]
        if all(versions):
            add_version(project, merged, "manual", "\n".join(v["raw_display"] for v in versions), "\n".join(v["raw_reading"] for v in versions), {"merged_versions": [v["id"] for v in versions]})
        project["scenes"][min(indexes):max(indexes) + 1] = [merged]
    elif action == "split":
        scene = find_scene(project, operation["scene_id"])
        parts = operation.get("parts", [])
        if not 2 <= len(parts) <= 20 or any(not isinstance(t, str) or not t.strip() for t in parts):
            reject("INPUT_INCOMPATIBLE", "拆分需要 2–20 个非空讲稿片段")
        items = []
        for index, text in enumerate(parts):
            item = new_scene(scene["source_page_ids"], scene["kind"])
            item.update(split_from=scene["id"], split_order=index, overrides=copy.deepcopy(scene["overrides"]), archived_parent=copy.deepcopy(scene))
            add_version(project, item, "manual", text, provenance={"split_from": scene["id"]})
            items.append(item)
        at = project["scenes"].index(scene)
        project["scenes"][at:at + 1] = items
    elif action == "plan":
        scene = find_scene(project, operation["scene_id"])
        if operation.get("kind") not in {"intro", "lecture", "transition", "summary"}:
            reject("INPUT_INCOMPATIBLE", "讲解用途无效")
        scene["kind"] = operation["kind"]
        invalidate(scene)
    elif action == "play_page":
        scene = find_scene(project, operation["scene_id"])
        if operation.get("source_page_id") not in scene["source_page_ids"]:
            reject("MAPPING_INVALID", "播放页必须属于当前片段来源页")
        scene["play_page_id"] = operation["source_page_id"]
        scene["media_state"] = "needs_recompose"
    else:
        reject("INPUT_INCOMPATIBLE", "结构操作不支持")
    check_mapping(project)


def import_scripts(project, payload):
    if payload.get("schema_version") != "m2.scripts.v1":
        reject("MAPPING_INVALID", "外部稿 schema_version 应为 m2.scripts.v1")
    records = payload.get("pages", [])
    if not isinstance(records, list) or any(not isinstance(r, dict) or not isinstance(r.get("source_page_id"), str) for r in records):
        reject("MAPPING_INVALID", "外部稿 pages 必须为含稳定页标识的对象数组")
    ids = [r.get("source_page_id") for r in records]
    valid = {s["source_page_id"] for s in project["slides"]}
    if len(ids) != len(set(ids)) or set(ids) != valid:
        reject("MAPPING_INVALID", "外部稿须精确覆盖所有稳定原页标识；禁止按位置猜测")
    for scene in project["scenes"]:
        if len(scene["source_page_ids"]) != 1 or sum(s["source_page_ids"] == scene["source_page_ids"] for s in project["scenes"]) != 1:
            reject("MAPPING_INVALID", "合并/拆分后请按片段编辑；逐页稿导入要求一页一片段")
    by_id = {r["source_page_id"]: r for r in records}
    for scene in project["scenes"]:
        record = by_id[scene["source_page_ids"][0]]
        if "display_text" not in record:
            reject("INPUT_INCOMPATIBLE", "外部稿缺少 display_text")
        add_version(project, scene, "external", record["display_text"], record.get("reading_text"), {"source_page_id": record["source_page_id"], "import_sha256": fingerprint(payload)})


def review(scene, checks, teacher_note):
    v = current(scene)
    if v and v.get('teaching_check_state') == 'pending':
        reject('TEACHING_CHECK_REQUIRED', '教学核查尚未完成，请重试核查或保存教师填写的完整核查表', scene['id'])
    if not v or not v["display_text"].strip() or not v["reading_text"].strip():
        reject("EMPTY_SCRIPT", "请先补齐非空显示稿与读法稿", scene["id"])
    if not isinstance(teacher_note, str) or not teacher_note.strip():
        reject("REVIEW_REQUIRED", "请输入教师核查记录")
    if not isinstance(checks, dict) or set(checks) != {"knowledge_points", "questions", "terms", "pending"} or any(not isinstance(checks[k], list) for k in checks):
        reject("INPUT_INCOMPATIBLE", "教学核查需要知识点、问题、术语和待确认项数组")
    if checks["pending"]:
        reject("REVIEW_REQUIRED", "待确认项尚未清零", scene["id"])
    if not checks["knowledge_points"] or any(not isinstance(p, str) or not p.strip() for p in checks["knowledge_points"]):
        reject("REVIEW_REQUIRED", "请登记知识点")
    for q in checks["questions"]:
        if not isinstance(q, dict) or not all(isinstance(q.get(k), str) and q[k].strip() for k in ["question", "answer", "source_page_id"]) or q["source_page_id"] not in scene["source_page_ids"]:
            reject("REVIEW_REQUIRED", "理解问题须有答案和有效原页来源")
    for term in checks["terms"]:
        if not isinstance(term, dict) or not all(isinstance(term.get(k), str) and term[k].strip() for k in ["text", "reading"]):
            reject("REVIEW_REQUIRED", "术语/数字/公式须记录显示文本与确认读法")
    if v.get("teacher_review"):
        reject("REVIEW_LOCKED", "已锁定审核版本；修改请创建新版本")
    v["checks"] = copy.deepcopy(checks)
    v["teacher_review"] = {"reviewer": "local-teacher", "note": teacher_note, "at": stamp()}
    scene["confirmed"] = v["id"]


def audition_key(project, scene):
    v = current(scene)
    c = effective(project, scene)
    asset = project["assets"].get("reference_audio", {})
    return fingerprint({"version": v, "speech": {k: c[k] for k in ["speed", "pause_before", "pause_after", "terms"]}, "reference": asset})
