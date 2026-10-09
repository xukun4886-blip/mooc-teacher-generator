"""Real tool fault injections; none of these stimuli are teacher capability media."""
import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mooc_m1.__main__ import setup
from mooc_m1.adapters import LocalModelAdapter
from mooc_m1.core import Failure, digest, run, write_json


def main():
    root = Path("storage/m1/faults").resolve()
    root.mkdir(parents=True, exist_ok=True)
    media, adapters, _ = setup({"storage": str(root)})
    records = []
    def check(name, expected, action, asset=None):
        try:
            action()
            raise AssertionError(f"{name} unexpectedly succeeded")
        except Failure as exc:
            assert exc.code == expected
            records.append({"scenario": name, "expected": expected, "actual": exc.record(),
                            "input_sha256": digest(asset) if asset else None, "success_output": False})
    empty, invalid, silent = root / "empty.wav", root / "invalid.mp4", root / "silence.wav"
    empty.write_bytes(b"")
    invalid.write_bytes(b"not a decodable media container")
    with wave.open(str(silent), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(b"\x00\x00" * 32000)
    check("empty_audio", "NO_VALID_MEDIA", lambda: media.inspect(empty, "audio"), empty)
    check("undecodable_video", "UNDECODABLE", lambda: media.inspect(invalid, "video"), invalid)
    check("decodable_but_silent_audio", "ABNORMAL_SILENCE", lambda: media.inspect(silent, "audio"), silent)
    check("process_timeout", "TIMEOUT", lambda: run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1))
    check("forced_worker_failure", "RUN_FAILED", lambda: run([sys.executable, "-c", "raise RuntimeError('forced local process failure')"]))
    check("oom_error_classification", "RESOURCE_INSUFFICIENT", lambda: run([sys.executable, "-c", "raise RuntimeError('CUDA out of memory')"]))
    for role, adapter in adapters.items():
        result = adapter.generate({})
        assert result["state"] == "failed" and result["output"] is None
        records.append({"scenario": f"{role}_missing_configuration", "actual": result["error"],
                        "request_id": result["request_id"], "success_output": False})
    missing = LocalModelAdapter("video", {"repo": str(root), "python": sys.executable,
        "code_revision": "not-installed", "weight_version": "unknown", "usage_review": {"accepted": False},
        "weights": [{"path": str(root / "missing.pth"), "sha256": "0" * 64}]}, media, root)
    records.append({"scenario": "missing_weight", "health": missing.health(), "success_output": False})
    write_json("docs/evidence/M1/faults.json", {"scope": "real media-tool and control-process faults only",
        "native_model_failure_validation": "blocked: no native model installed",
        "not_voice_or_avatar_capability_evidence": True, "cases": records})
    print(f"{len(records)} real tool/control fault cases recorded; native model cases remain blocked.")


if __name__ == "__main__":
    main()
