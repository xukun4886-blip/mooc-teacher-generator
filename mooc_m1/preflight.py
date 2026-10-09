from pathlib import Path

from .core import Failure, digest
from .ppt import parse_pptx


DEFAULT_LIMITS = {"pptx": 100, "photo": 20, "video": 500, "reference_audio": 50}


def check_constraints(role, inputs, constraints):
    for key, meta in inputs.items():
        constraint = constraints.get(key, {})
        duration = meta.get("duration_seconds")
        for bound, comparison in [("min_seconds", lambda a, b: a < b), ("max_seconds", lambda a, b: a > b)]:
            limit = constraint.get(bound)
            if limit is not None and duration is not None and comparison(duration, limit):
                raise Failure("INPUT_INCOMPATIBLE", f"{key} violates adapter {bound}", role,
                              "Select an explicit compatible input segment; do not silently switch providers")
        size = constraint.get("min_short_edge")
        if size is not None and min(meta.get("width", 0), meta.get("height", 0)) < size:
            raise Failure("INPUT_INCOMPATIBLE", f"{key} resolution violates model requirement", role)


def preflight(manifest, adapters, media, storage, limits=None, max_ppt_pages=50):
    limits = {**DEFAULT_LIMITS, **(limits or {})}
    blockers, warnings, inspected = [], [], {}
    assets = manifest.get("assets", {})
    teacher_ids = set()
    for role in ["pptx", "photo", "video", "reference_audio"]:
        asset = assets.get(role, {})
        path = Path(asset.get("path") or "__missing_input__")
        if not path.is_file():
            blockers.append(Failure("INPUT_MISSING", "Required sample is missing", role,
                                    "Supply a local authorized sample and authorization record").record())
            continue
        rights = asset.get("authorization", {})
        scopes = {"pptx": {"course_material_processing"}, "photo": {"portrait_animation"},
                  "video": {"video_lip_sync"}, "reference_audio": {"voice_synthesis"}}[role]
        if rights.get("confirmed") is not True or not rights.get("record") or not scopes.issubset(set(rights.get("scopes", []))):
            blockers.append(Failure("AUTHORIZATION_MISSING", "Authorization is missing or does not cover this processing", role).record())
        if role != "pptx":
            if not asset.get("teacher_id"):
                blockers.append(Failure("AUTHORIZATION_MISSING", "Teacher identity mapping is missing", role).record())
            else:
                teacher_ids.add(asset["teacher_id"])
        if path.stat().st_size > limits[role] * 1024 * 1024:
            blockers.append(Failure("INPUT_INCOMPATIBLE", "Asset exceeds configured byte limit", role).record())
            continue
        try:
            if role == "pptx":
                parsed = parse_pptx(path, Path(storage) / "preflight-ppt", max_ppt_pages)
                inspected[role] = {"sha256": parsed["source_sha256"], "page_count": parsed["page_count"]}
                if parsed["page_count"] != 10:
                    warnings.append({"source": role, "code": "SAMPLE_PAGE_COUNT", "message": "M1 comparison sample should be about 10 pages"})
            else:
                kind = "audio" if role == "reference_audio" else role
                inspected[role] = media.inspect(path, kind)
                if role == "photo" and min(inspected[role]["width"], inspected[role]["height"]) < 512:
                    warnings.append({"source": role, "code": "PHOTO_SIZE_SUGGESTION", "message": "Suggested short edge is at least 512 px"})
                if role == "video" and not 5 <= inspected[role]["duration_seconds"] <= 60:
                    blockers.append(Failure("INPUT_INCOMPATIBLE", "Teacher source video must be 5–60 seconds", role).record())
                if role == "reference_audio" and not 20 <= inspected[role]["duration_seconds"] <= 60:
                    warnings.append({"source": role, "code": "REFERENCE_LENGTH_SUGGESTION", "message": "20–60 seconds is suggested; obey actual model constraints"})
        except Failure as exc:
            error = exc.record()
            error["source"] = role
            blockers.append(error)
    if len(teacher_ids) > 1:
        blockers.append(Failure("INPUT_INCOMPATIBLE", "Photo, video and voice must identify the same teacher", "teacher_id").record())
    script = manifest.get("script", {})
    if script.get("confirmed") is not True or not script.get("reading_text", "").strip() or not script.get("review_record"):
        blockers.append(Failure("INPUT_INCOMPATIBLE", "Human-confirmed Chinese test script is missing", "script").record())
    health = {}
    for role, adapter in adapters.items():
        health[role] = adapter.health()
        blockers.extend(health[role]["blockers"])
        if health[role]["ready"]:
            relevant = {"reference_audio": inspected.get("reference_audio")} if role == "tts" else {role: inspected.get(role)}
            try:
                check_constraints(role, {k: v for k, v in relevant.items() if v}, adapter.config.get("constraints", {}))
            except Failure as exc:
                blockers.append(exc.record())
            warnings.append({"source": role, "code": "MODEL_LOAD_AND_QUALITY_UNVERIFIED",
                             "message": "File/dependency readiness does not prove loading, identity or lip sync"})
    return {"schema_version": "m1.preflight.v1", "ready": not blockers, "blockers": blockers,
            "warnings": warnings, "assets": inspected, "health": health,
            "generation_called": False, "estimated_seconds": None, "estimated_peak_vram_mib": None,
            "model_quality_passed": False}
