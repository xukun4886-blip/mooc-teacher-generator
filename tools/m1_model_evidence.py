"""Publish metadata-only evidence from actual native requests; never infer quality."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mooc_m1.core import read_json, write_json, digest, stamp, run
from mooc_m1.__main__ import setup


def compact_media(media):
    if not media:
        return None
    fields = ["path", "sha256", "size_bytes", "duration_seconds", "width", "height", "fps",
              "sample_rate", "codec", "silence_ratio", "max_volume_db"]
    return {key: media[key] for key in fields if key in media}


def compact_request(state):
    resources = state.get("resources", {})
    return {"request_id": state["request_id"], "role": state["role"], "state": state["state"],
        "created_at": state.get("created_at"), "stage": state.get("stage"),
        "output": compact_media(state.get("output")), "warm_output": compact_media(state.get("warm_output")),
        "inputs": {key: compact_media(value) for key, value in state.get("inputs", {}).items()},
        "actual_provider": state.get("actual_provider"), "code_revision": state.get("code_revision"),
        "actual_weight_version": state.get("actual_weight_version"),
        "native_model_record": state.get("native_model_record"), "native_loads": state.get("native_loads"),
        "native_driving": state.get("native_driving"),
        "elapsed_seconds": state.get("elapsed_seconds"), "warm_seconds": state.get("warm_seconds"),
        "error": state.get("error"), "device_peak_used_mib": resources.get("device_peak_used_mib"),
        "device_sample_count": len(resources.get("samples", [])),
        "device_scope": resources.get("scope"), "quality_verified": False,
        "controlled_status_path": str(Path("storage/m1/requests", state["request_id"], "status.json").resolve())}


def main():
    config = read_json("config/m1.local.json")
    media, adapters, storage = setup(config)
    evidence = Path("docs/evidence/M1")
    states = sorted((read_json(p) for p in Path(storage).glob("requests/*/status.json")),
                    key=lambda s: s.get("created_at", ""))
    native = [s for s in states if (Path(storage)/"requests"/s["request_id"]/"native.log").exists()]
    summary = {"recorded_at": stamp(), "quality_verified": False,
               "scope": "actual native execution and decoded media; human voice/identity/lipsync review pending",
               "requests": [compact_request(s) for s in native]}
    write_json(evidence/"native-requests.json", summary)
    capability = {}
    baseline = {}
    for role, adapter in adapters.items():
        successes = [s for s in native if s["role"] == role and s["state"] == "media_ready"]
        failures = [s for s in native if s["role"] == role and s["state"] == "failed"]
        latest = successes[-1] if successes else None
        capability[role] = {"capabilities": adapter.capabilities(), "health": adapter.health(),
                           "actual_media_generated": bool(successes), "successful_request_ids": [s["request_id"] for s in successes],
                           "latest_success": compact_request(latest) if latest else None,
                           "quality_verified": False, "review_required": True}
        baseline[role] = {"latest_success": compact_request(latest) if latest else None,
                          "native_failures": [compact_request(s) for s in failures]}
    write_json(evidence/"local-model-capabilities.json", {"recorded_at": stamp(), "models": capability})
    write_json(evidence/"model-resource-readiness.json", {"recorded_at": stamp(), "models": baseline,
        "gpu_policy": "serialized inference on RTX 3050 Laptop 4096MiB; no simultaneous model residency claim",
        "whole_device_vram_note": "includes desktop and other processes; torch allocated/reserved reported separately",
        "long_task_estimate": None, "m1_passed": False})
    models = {}
    for role, c in config["models"].items():
        freeze = run([c["python"], "-m", "pip", "freeze"], timeout=60)["stdout"].splitlines()
        check = run([c["python"], "-m", "pip", "check"], timeout=60)["stdout"].strip()
        models[role] = {"python": c["python"], "repo": c["repo"], "code_revision": c["code_revision"],
                       "weight_version": c["weight_version"], "weight_sha256_list": c["weights"],
                       "runtime_requirements": freeze, "pip_check": check,
                       "memory_profile": c.get("memory_profile"), "tokenizer_backend": c.get("tokenizer_backend")}
    write_json(evidence/"model-environments.json", {"recorded_at": stamp(), "models": models})
    print({"native_requests": len(native), "roles_with_real_media": [r for r,v in capability.items() if v["actual_media_generated"]],
           "quality_verified": False, "m1_passed": False})


if __name__ == "__main__":
    main()
