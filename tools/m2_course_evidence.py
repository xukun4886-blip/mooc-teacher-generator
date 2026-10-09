"""Prepare the authorized course; no teacher approval is fabricated.

Runs against the local HTTP service. Output contains hashes/counts, not scripts.
"""
import json
import sys
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mooc_m1.core import read_json, write_json, stamp

OUT = ROOT / "docs/evidence/M2/course-ai-real.json"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if OUT.exists():
        raise SystemExit("Existing real-course evidence retained. Use m2_finish_course.py to resume/check the existing batch.")
    samples = read_json(ROOT / "config/samples.local.json")
    selection = read_json(ROOT / "storage/m1/reference-selection.json")
    client = httpx.Client(base_url="http://127.0.0.1:8765/api", timeout=240, trust_env=False)
    client.post("/session", json={"token": (ROOT / "storage/m2/.session-token").read_text().strip()}).raise_for_status()
    def get(pid):
        r = client.get(f"/projects/{pid}"); r.raise_for_status(); return r.json()
    def wait(pid):
        while True:
            r = client.get(f"/projects/{pid}/jobs"); r.raise_for_status(); jobs = r.json()
            if not any(j["state"] in {"queued", "running"} for j in jobs): return jobs
            time.sleep(2)
    p = client.post("/projects", json={"name": "Lecture 2 · 整份课件 AI 草稿", "config": {"audience": "网络工程系大三本科", "detail": "标准", "target_seconds": 60}}).json()
    pid = p["id"]
    record = {"created_at": stamp(), "project_id": pid, "source_sha256": samples["assets"]["pptx"]["sha256"], "provider": "open.bigmodel.cn", "model": "glm-4.6v-flash", "teacher_review": "pending", "formal_scope": {"first": 5, "last": 14, "user_selected": True}}
    write_json(OUT, record)
    for role in ["pptx", "reference_audio", "photo", "video"]:
        path = Path(samples["assets"][role]["path"])
        with path.open("rb") as f:
            r = client.post(f"/projects/{pid}/assets/{role}", data={"revision": get(pid)["revision"], "authorization": "User authorized existing material processing 2026-10-01; real M2 AI course development 2026-10-02; no training", "teacher_id": "task-test-selected-teacher" if role != "pptx" else ""}, files={"file": (path.name, f)})
        r.raise_for_status()
        jobs = wait(pid)
        assert jobs[0]["state"] == "completed", jobs[0].get("error")
        print("uploaded", role, flush=True)
    r = client.post(f"/projects/{pid}/assets/reference_audio/selection", json={"revision": get(pid)["revision"], "selection": {"start": selection["start_seconds"], "end": selection["end_seconds"], "transcript": selection["transcript"]}})
    r.raise_for_status(); wait(pid)
    p = get(pid)
    r = client.post(f"/projects/{pid}/ai-batches", json={"revision": p["revision"]}); r.raise_for_status()
    record.update(batch_id=r.json()["batch_id"], total=r.json()["total"])
    write_json(OUT, record)
    previous = None
    while True:
        jobs = client.get(f"/projects/{pid}/jobs").json()
        ai = [j for j in jobs if j["kind"] == "ai"]
        counts = {state: sum(j["state"] == state for j in ai) for state in ["queued", "running", "completed", "failed"]}
        if counts != previous:
            record.update(counts=counts, checked_at=stamp(), failures=[{"scene_id": j["payload"]["scene_id"], "error": j["error"]} for j in ai if j["state"] == "failed"])
            write_json(OUT, record); print(counts, flush=True); previous = counts
        if not counts["queued"] and not counts["running"]: break
        time.sleep(3)
    p = get(pid)
    record["page_count"] = len(p["slides"])
    record["draft_versions"] = [{"scene_id": s["id"], "source_page_ids": s["source_page_ids"], "version_id": s["current_version"], "question_count": len(s["versions"][-1]["checks"]["questions"]) if s["versions"] else 0, "pending_count": len(s["versions"][-1]["checks"]["pending"]) if s["versions"] else 0, "teacher_confirmed": bool(s["confirmed"])} for s in p["scenes"]]
    write_json(OUT, record)
    print("AI batch finished; teacher review still pending", flush=True)


if __name__ == "__main__": main()
