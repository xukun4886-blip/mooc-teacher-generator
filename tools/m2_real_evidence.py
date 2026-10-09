"""Real M2 API/Office/TTS evidence. Engineering mapping is NOT course acceptance.

Uses existing authorized M1 inputs and previously user-confirmed Chinese text.
Does not fill human listening reviews or approve newly authored course content.
"""
import copy
import json
import re
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from mooc_m1.core import read_json, write_json, digest, stamp
from mooc_m2.api import create_app
from mooc_m2.content import add_version, effective, current, fingerprint


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/evidence/M2"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    app = create_app(worker=False)
    svc, store = app.state.service, app.state.service.store
    client = TestClient(app)
    client.post("/api/session", json={"token": store.token}).raise_for_status()
    p = client.post("/api/projects", json={"name": "M2 十页工程验证 · 待人工评审"}).json()
    pid = p["id"]
    fixtures = read_json(ROOT / "docs/evidence/M1/ppt-engineering.json")
    samples = read_json(ROOT / "config/samples.local.json")
    selection = read_json(ROOT / "storage/m1/reference-selection.json")
    uploads = {"pptx": Path(fixtures["source"]["path"]), "photo": Path(samples["assets"]["photo"]["path"]), "video": Path(samples["assets"]["video"]["path"]), "reference_audio": Path(samples["assets"]["reference_audio"]["path"])}
    for role, path in uploads.items():
        p = store.get(pid)
        with path.open("rb") as f:
            response = client.post(f"/api/projects/{pid}/assets/{role}", data={"authorization": "Existing user authorization 2026-10-01; local content evaluation; engineering PPT self authored", "teacher_id": "task-test-selected-teacher" if role != "pptx" else "", "revision": p["revision"]}, files={"file": (path.name, f)})
        response.raise_for_status()
        job = store.claim()
        svc.execute(job)
        if job["state"] != "completed":
            raise RuntimeError(job)
        print("asset", role, "completed", flush=True)
    p = store.get(pid)
    response = client.post(f"/api/projects/{pid}/assets/reference_audio/selection", json={"revision": p["revision"], "selection": {"start": selection["start_seconds"], "end": selection["end_seconds"], "transcript": selection["transcript"]}})
    response.raise_for_status()
    job = store.claim()
    svc.execute(job)
    assert job["state"] == "completed", job
    p = store.get(pid)
    assert len(p["slides"]) == 10
    expected_ids = [s["source_page_id"] for s in p["slides"]]
    from mooc_m2.store import Store
    reopened = Store(store.root).get(pid)
    assert [s["source_page_id"] for s in reopened["slides"]] == expected_ids
    # Validate literal notes and external imports via the actual HTTP API.
    first = p["scenes"][0]["id"]
    response = client.post(f"/api/projects/{pid}/commands", json={"revision": p["revision"], "action": "notes", "data": {"scene_id": first}})
    response.raise_for_status()
    p = response.json()
    assert current(p["scenes"][0])["display_text"] == p["slides"][0]["notes_original"]
    template = client.get(f"/api/projects/{pid}/import-template").json()
    for item in template["pages"]:
        item["display_text"] = "外部稿原文 [0,1]、[1,2,3]、[1]。"
        item["reading_text"] = "外部稿原文。"
    response = client.post(f"/api/projects/{pid}/commands", json={"revision": p["revision"], "action": "import", "data": template})
    response.raise_for_status()
    original_script = samples["script"]
    # Ten contiguous cuts of already confirmed reading text, no invented script.
    reading = original_script["reading_text"]
    boundaries = [m.end() for m in re.finditer("[，。]", reading)]
    cuts, prior = [], 0
    for index in range(1, 10):
        ideal = round(len(reading) * index / 10)
        candidate = min((n for n in boundaries if n > prior), key=lambda n: abs(n - ideal))
        cuts.append(reading[prior:candidate]); prior = candidate
    cuts.append(reading[prior:])
    assert "".join(cuts) == reading and all(t.strip() for t in cuts)
    with store.edit(pid) as p:
        p["engineering_only"] = True
        p["course_review"] = "pending_not_an_authorized_teaching_lesson"
        for i, (scene, text) in enumerate(zip(p["scenes"], cuts)):
            if i == 0:
                scene["overrides"] = {"show_teacher": False, "pause_before": .5}
            elif i == 1:
                scene["overrides"] = {"position": "top-left", "size": .35, "speed": .9, "pause_after": .7}
            elif i == 2:
                scene["overrides"] = {"position": "bottom-right", "size": .2, "speed": 1.1}
            v = add_version(p, scene, "manual", text, text, {"prior_user_confirmed_script_sha256": fingerprint(original_script), "scope": "M1 confirmed text contiguous extract; arbitrary engineering page mapping; NOT course approval"})
            v["teacher_review"] = {"reviewer": "prior_user_confirmation", "note": "Reused exact contiguous text from user-confirmed M1 script; course mapping still pending", "at": stamp()}
            scene["confirmed"] = v["id"]
    records = []
    summary = {"project_id": pid, "controlled_storage": str(store.folder(pid)), "engineering_only": True,
               "page_count": 10, "reopen_original_ids": True, "notes_literal": True, "external_literal": True,
               "authorization_reused_from": "M1 user-confirmed local material authorization", "auditions": records,
               "human_listening_review": "pending", "course_teacher_review": "pending", "ai_real_validation": "blocked_configuration_missing", "m1_passed": False, "m2_passed": False}
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(OUT / "real-content-chain.json", summary)
    for index in range(10):
        p = store.get(pid)
        sid = p["scenes"][index]["id"]
        response = client.post(f"/api/projects/{pid}/scenes/{sid}/audition", json={"revision": p["revision"]})
        response.raise_for_status()
        job = store.claim()
        svc.execute(job)
        record = {"source_index": index + 1, "scene_id": sid, "state": job["state"], "error": job["error"]}
        if job["state"] == "completed":
            audio = store.get(pid)["scenes"][index]["audition"]
            record.update(audio)
            record["controlled_path"] = str(store.file(pid, audio["path"]))
            record["effective_config"] = effective(store.get(pid), store.get(pid)["scenes"][index])
            assert client.get(f"/api/projects/{pid}/files/{audio['path']}").status_code == 200
            with wave.open(record["controlled_path"], "rb") as wav:
                assert wav.getnframes() > 0
                record["decoded_frames"] = wav.getnframes()
        records.append(record)
        write_json(OUT / "real-content-chain.json", summary)
        print("audition", index + 1, job["state"], job["error"], flush=True)
    p = store.get(pid)
    summary["preflight"] = svc.preflight(p)
    summary["all_ten_real_audio"] = all(r["state"] == "completed" for r in records)
    summary["finished_at"] = stamp()
    write_json(OUT / "real-content-chain.json", summary)
    print("Real evidence saved; human reviews and AI remain explicitly pending.", flush=True)


if __name__ == "__main__":
    main()
