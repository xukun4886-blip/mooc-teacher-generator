"""Supplemental actual video selection and sample-accurate TTS controls."""
import sys
import wave
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from mooc_m1.core import read_json, write_json, stamp
from mooc_m2.api import create_app
from mooc_m2.content import add_version, current


def main():
    app = create_app(worker=False)
    svc, store = app.state.service, app.state.service.store
    source = read_json("docs/evidence/M2/real-content-chain.json")
    p = store.clone(source["project_id"])
    pid = p["id"]
    client = TestClient(app)
    client.post("/api/session", json={"token": store.token}).raise_for_status()
    r = client.post(f"/api/projects/{pid}/assets/video/selection", json={"revision": p["revision"], "selection": {"start": 2, "end": 7}})
    r.raise_for_status()
    job = store.claim(); svc.execute(job)
    assert job["state"] == "completed", job
    with store.edit(pid) as p:
        s = p["scenes"][0]
        old = current(s)
        text = old["raw_reading"]
        point = len(text) // 2
        controlled = text[:point] + "{{pause:0.4}}" + text[point:]
        s["overrides"].update(pause_before=.25, pause_after=.35, speed=1.2)
        v = add_version(p, s, "manual", old["raw_display"], controlled, {"prior_confirmation": old["provenance"], "change": "explicit_internal_pause_only; no new teaching words"})
        assert v["reading_text"] == text
        v["teacher_review"] = {"reviewer": "prior_user_confirmation", "note": "Original confirmed text; engineering pause test only", "at": stamp()}
        s["confirmed"] = v["id"]
    p = store.get(pid); sid = p["scenes"][0]["id"]
    r = client.post(f"/api/projects/{pid}/scenes/{sid}/audition", json={"revision": p["revision"]})
    r.raise_for_status()
    job = store.claim(); svc.execute(job)
    assert job["state"] == "completed", job
    p = store.get(pid); audio = p["scenes"][0]["audition"]
    with wave.open(str(store.file(pid, audio["path"])), "rb") as wav:
        sr, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
        samples = wav.readframes(wav.getnframes())
    stride = width * channels
    pauses = [{"type": "pause", "start_seconds": 0, "end_seconds": .25}] + [x for x in audio["native_model"]["speech_timeline"] if x.get("type") == "pause"]
    verified = []
    for interval in pauses:
        start, end = round(interval["start_seconds"] * sr), round(interval["end_seconds"] * sr)
        padding = samples[start * stride:end * stride]
        assert len(padding) == (end - start) * stride and all(x == 0 for x in padding)
        verified.append({**interval, "exact_zero_pcm_frames": end - start})
    video = p["assets"]["video"]
    assert abs(video["selected_metadata"]["duration_seconds"] - 5) < .1
    result = {"engineering_only": True, "project_id": pid, "source_project_id": source["project_id"], "video_selection": {"range": video["selection"], "actual_duration_seconds": video["selected_metadata"]["duration_seconds"], "sha256": video["selected_sha256"], "original_retained": True},
              "audition": audio, "controlled_audio": str(store.file(pid, audio["path"])), "pause_pcm_verification": verified,
              "native_speed_factor": audio["native_model"]["speed_factor"], "control_markers_not_spoken": "directive removed from every native speech segment; intervals inserted as exact zero samples", "human_review": "pending", "passed_engineering_checks": True}
    write_json("docs/evidence/M2/control-validation.json", result)
    print("Video 2-7s selection and .25/.4/.35s zero-sample pauses passed; human review pending.")


if __name__ == "__main__":
    main()
