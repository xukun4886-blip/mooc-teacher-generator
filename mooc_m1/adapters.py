from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

from .core import Failure, digest, read_json, run, stamp, write_json
from .resources import GPUSampler


PROVIDERS = {"tts": "GPT-SoVITS", "photo": "SadTalker", "video": "MuseTalk"}
RUNTIME_MODULES = {
    "tts": ["soundfile", "yaml", "transformers", "fast_langdetect", "jieba", "pytorch_lightning",
            "matplotlib", "librosa", "onnxruntime", "cn2an", "peft", "split_lang", "x_transformers", "g2p_en", "wordsegment"],
    "photo": ["scipy", "cv2", "skimage", "safetensors", "facexlib", "gfpgan", "basicsr", "librosa", "kornia", "yacs"],
    "video": ["diffusers", "accelerate", "cv2", "transformers", "soundfile", "librosa", "omegaconf", "mmcv", "mmengine", "mmdet", "mmpose"]}


class LocalModelAdapter:
    """Pinned local subprocess adapter. Each model uses its own Python executable.

    Health checks never generate. Dependencies ready is distinct from weights loaded
    or quality passed. Only a successful native model run may produce media_ready.
    """
    def __init__(self, role, config, media, storage):
        self.role, self.config, self.media = role, config or {}, media
        self.storage = Path(storage).resolve()

    def capabilities(self):
        c = self.config
        return {"schema_version": "m1.adapter.v1", "role": self.role,
                "provider": PROVIDERS[self.role], "configured": bool(c),
                "code_revision": c.get("code_revision"), "weight_version": c.get("weight_version"),
                "input_types": {"tts": ["confirmed_chinese_text", "reference_audio"],
                                "photo": ["photo", "current_audio"],
                                "video": ["video_sequence", "current_audio"]}[self.role],
                "chinese": {"declared": c.get("chinese"), "verified": False},
                "reference_timbre": {"declared": c.get("reference_timbre"), "verified": False},
                "constraints": c.get("constraints", {}),
                "quality_verified": False, "immediate_cancellation": False,
                "execution": "isolated_local_process", "fee": 0,
                "cold_seconds": None, "warm_seconds": None, "peak_model_vram_mib": None}

    def health(self):
        errors = []
        c = self.config
        if not c:
            errors.append(Failure("SERVICE_CONFIG_MISSING", "Local model configuration missing", self.role,
                                  "Configure an isolated interpreter, pinned code and complete weights").record())
            return {"role": self.role, "ready": False, "blockers": errors, "model_loaded": False}
        for field in ["repo", "python", "code_revision", "weight_version", "weights", "usage_review"]:
            if not c.get(field):
                errors.append(Failure("SERVICE_CONFIG_MISSING", f"Missing {field}", self.role).record())
        for field in ["repo", "python"]:
            if c.get(field) and not Path(c[field]).exists():
                errors.append(Failure("MODEL_NOT_READY", f"Configured {field} does not exist", self.role).record())
        if c.get("usage_review") and c["usage_review"].get("accepted") is not True:
            errors.append(Failure("MODEL_NOT_READY", "Model/auxiliary weight usage review is incomplete", self.role).record())
        if c.get("repo") and Path(c["repo"]).is_dir():
            try:
                actual = run(["git", "rev-parse", "HEAD"], cwd=c["repo"])["stdout"].strip()
                dirty = run(["git", "diff", "HEAD", "--name-only"], cwd=c["repo"])["stdout"].strip()
                if actual != c.get("code_revision") or dirty:
                    errors.append(Failure("MODEL_NOT_READY", "Code revision differs or tracked code is modified", self.role).record())
            except Failure as exc:
                errors.append(exc.record())
        for item in c.get("weights", []):
            path = Path(item.get("path", ""))
            if not path.is_file() or not item.get("sha256"):
                errors.append(Failure("MODEL_NOT_READY", "Weight missing or checksum unconfigured", self.role).record())
            elif digest(path) != item["sha256"]:
                errors.append(Failure("MODEL_NOT_READY", "Weight checksum mismatch", self.role).record())
        if self.role == "tts" and not (c.get("tts_config") and Path(c["tts_config"]).is_file()):
            errors.append(Failure("SERVICE_CONFIG_MISSING", "GPT-SoVITS inference YAML is missing", self.role).record())
        elif self.role == "tts":
            try:
                import yaml
                selected = yaml.safe_load(Path(c["tts_config"]).read_text(encoding="utf-8"))["custom"]
                if str(selected.get("device")) != c.get("device", "cuda"):
                    errors.append(Failure("INPUT_INCOMPATIBLE", "Declared device differs from TTS inference YAML", self.role).record())
                inventoried = {Path(item["path"]).resolve() for item in c.get("weights", [])}
                for field in ["t2s_weights_path", "vits_weights_path", "bert_base_path", "cnhuhbert_base_path"]:
                    configured = Path(selected[field])
                    configured = configured if configured.is_absolute() else Path(c["repo"]) / configured
                    if not configured.exists():
                        errors.append(Failure("MODEL_NOT_READY", f"Configured {field} missing; upstream fallback forbidden", self.role).record())
                    elif configured.is_file() and configured.resolve() not in inventoried:
                        errors.append(Failure("MODEL_NOT_READY", f"Configured {field} is not in checksum inventory", self.role).record())
            except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
                errors.append(Failure("SERVICE_CONFIG_MISSING", "Invalid explicit GPT-SoVITS custom configuration", self.role).record())
        if self.role == "tts":
            assets = [("fasttext_cache", "lid.176.bin"), ("nltk_data", "corpora/cmudict"),
                      ("nltk_data", "taggers/averaged_perceptron_tagger_eng")]
            for field, relative in assets:
                if not c.get(field) or not (Path(c[field]) / relative).exists():
                    errors.append(Failure("MODEL_NOT_READY", f"Explicit offline language asset missing: {field}/{relative}", self.role,
                                          "Install the inventoried language asset; automatic download/fallback is disabled").record())
        if self.role == "video" and c.get("memory_profile", "native") not in {"native", "cpu_staged_fp16"}:
            errors.append(Failure("INPUT_INCOMPATIBLE", "Unknown video memory profile", self.role).record())
        if self.role == "tts" and (c.get("chinese") is not True or c.get("reference_timbre") is not True):
            errors.append(Failure("INPUT_INCOMPATIBLE", "Chinese/reference timbre support must be explicitly declared", self.role).record())
        dependency = None
        if not errors:
            try:
                import json
                module_probe = repr(RUNTIME_MODULES[self.role])
                native_probe = "; import mmcv.ops" if self.role == "video" else ""
                probe = run([c["python"], "-c",
                    "import torch,json,importlib.util" + native_probe + "; modules=" + module_probe + "; "
                    "print(json.dumps({'torch':torch.__version__,'cuda_runtime':torch.version.cuda,'cuda_available':torch.cuda.is_available(),"
                    "'missing_modules':[name for name in modules if importlib.util.find_spec(name) is None]}))"],
                    timeout=30, cwd=c["repo"])
                health_log = self.storage / "health" / (self.role + "-runtime.log")
                health_log.parent.mkdir(parents=True, exist_ok=True)
                health_log.write_text(probe["stdout"] + probe["stderr"], encoding="utf-8")
                dependency = json.loads(probe["stdout"].strip().splitlines()[-1])
                if dependency["missing_modules"]:
                    errors.append(Failure("MODEL_NOT_READY", "Required runtime modules missing: " + ", ".join(dependency["missing_modules"]), self.role).record())
                if c.get("device", "cuda") == "cuda" and not dependency["cuda_available"]:
                    errors.append(Failure("RESOURCE_INSUFFICIENT", "Model environment cannot access CUDA", self.role).record())
            except (Failure, ValueError, IndexError) as exc:
                code = exc.code if isinstance(exc, Failure) and exc.code == "TIMEOUT" else "MODEL_NOT_READY"
                errors.append(Failure(code, "Runtime dependency probe failed; inspect the isolated interpreter", self.role,
                                      "Repair the pinned runtime; no native generation was called").record())
        return {"role": self.role, "ready": not errors, "model_loaded": False,
                "readiness_scope": "configuration_checksums_runtime_module_discovery_torch_cuda_and_mmcv_binary; no native generation", "dependencies": dependency,
                "blockers": errors, "quality_verified": False}

    def status(self, request_id):
        try:
            uuid.UUID(request_id)
        except ValueError as exc:
            raise Failure("INPUT_INCOMPATIBLE", "Invalid request ID") from exc
        path = self.storage / "requests" / request_id / "status.json"
        if not path.is_file():
            raise Failure("INPUT_INCOMPATIBLE", "Unknown request ID", request_id)
        state = read_json(path)
        if state["state"] == "running" and not self._pid_alive(state.get("pid")):
            state.update(state="failed", error=Failure("RUN_FAILED", "Owner process stopped before completion", request_id).record())
            write_json(path, state)
        return state

    @staticmethod
    def _pid_alive(pid):
        if not pid:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = wintypes.DWORD()
                return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def generate(self, request):
        request_id = str(uuid.uuid4())
        folder = self.storage / "requests" / request_id
        folder.mkdir(parents=True)
        state = {"request_id": request_id, "role": self.role, "state": "running",
                 "stage": "preflight", "created_at": stamp(), "pid": os.getpid(), "output": None}
        write_json(folder / "status.json", state)
        started = time.perf_counter()
        try:
            health = self.health()
            if not health["ready"]:
                first = health["blockers"][0]
                raise Failure(first["code"], first["message"], self.role, first.get("remedy"))
            if request.get("authorized") is not True or not request.get("authorization_record"):
                raise Failure("AUTHORIZATION_MISSING", "Generation requires traceable material authorization", self.role)
            if self.role == "tts":
                draft_preview = request.get("purpose") == "audition" and request.get("draft_preview") is True
                if (request.get("script_confirmed") is not True and not draft_preview) or not request.get("text", "").strip():
                    raise Failure("INPUT_INCOMPATIBLE", "Confirmed nonempty Chinese script is required", self.role)
                inputs = {"reference_audio": self.media.inspect(request["reference_audio"], "audio")}
            else:
                inputs = {"audio": self.media.inspect(request["audio"], "audio", min_duration=0.1 if request.get("purpose") == "m3_segment" else 30),
                          self.role: self.media.inspect(request[self.role], "photo" if self.role == "photo" else "video")}
            from .preflight import check_constraints
            check_constraints(self.role, inputs, self.config.get("constraints", {}))
            if request.get("warm_audio"):
                if self.role not in {"photo", "video"}:
                    raise Failure("INPUT_INCOMPATIBLE", "warm_audio requires a portrait adapter", self.role)
                if self.role == "video" and self.config.get("memory_profile") != "cpu_staged_fp16":
                    raise Failure("INPUT_INCOMPATIBLE", "Warm video measurement requires cpu_staged_fp16", self.role)
                inputs["warm_audio"] = self.media.inspect(request["warm_audio"], "audio", min_duration=30)
            state.update(stage="native_generation", inputs=inputs)
            write_json(folder / "status.json", state)
            output = folder / ("audio.wav" if self.role == "tts" else "video.mp4")
            worker_request = {"role": self.role, "config": self.config, "request": request,
                              "output": str(output), "work_dir": str(folder), "ffmpeg": self.media.ffmpeg}
            write_json(folder / "worker-request.json", worker_request)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            environment["PATH"] = str(Path(self.media.ffmpeg).parent) + os.pathsep + environment["PATH"]
            environment["HF_HUB_OFFLINE"] = "1"
            environment["TRANSFORMERS_OFFLINE"] = "1"
            if self.config.get("fasttext_cache"):
                environment["FTLANG_CACHE"] = self.config["fasttext_cache"]
            if self.config.get("nltk_data"):
                environment["NLTK_DATA"] = self.config["nltk_data"]
            # Requests/text and complete logs stay in ignored controlled storage.
            with GPUSampler() as sampler:
                try:
                    result = run([self.config["python"], "-m", "mooc_m1.model_worker", folder / "worker-request.json"],
                                 timeout=self.config.get("timeout_seconds", 900), cwd=self.config["repo"], env=environment,
                                 log_path=folder / "native.log")
                finally:
                    state["resources"] = sampler.report()
            (folder / "native.log").write_text(result["stdout"] + result["stderr"], encoding="utf-8")
            kind = "audio" if self.role == "tts" else "video"
            minimum = 0.1 if request.get("purpose") in {"audition", "m3_segment"} else 30
            media = self.media.inspect(output, kind, min_duration=minimum,
                                       expected_duration=inputs["audio"]["duration_seconds"] if "audio" in inputs else None)
            if self.role != "tts":
                # Validate the final voice track too; source-video sound must not replace current speech.
                self.media.inspect(output, "audio", expected_duration=inputs["audio"]["duration_seconds"])
            state.update(state="media_ready", stage="awaiting_human_review", output=media,
                         actual_provider=PROVIDERS[self.role], code_revision=self.config["code_revision"],
                         configured_weight_version=self.config["weight_version"], actual_weight_version=None,
                         configured_weights=self.config["weights"], weight_load_attestation="pending_native_validation",
                         elapsed_seconds=time.perf_counter() - started,
                         quality_verified=False, baseline_phase="cold_process", warm_seconds=None,
                         peak_model_vram_mib=None)
            if (folder / "native-model.json").is_file():
                state["native_model_record"] = read_json(folder / "native-model.json")
                state["actual_weight_version"] = state["native_model_record"].get("actual_weight_version")
                state["warm_seconds"] = state["native_model_record"].get("warm_seconds")
            if (folder / "audio-warm.wav").is_file():
                state["warm_output"] = self.media.inspect(folder / "audio-warm.wav", "audio", min_duration=30)
            if (folder / "video-warm.mp4").is_file():
                state["warm_output"] = self.media.inspect(folder / "video-warm.mp4", "video", min_duration=30,
                                                          expected_duration=inputs["warm_audio"]["duration_seconds"])
                self.media.inspect(folder / "video-warm.mp4", "audio", expected_duration=inputs["warm_audio"]["duration_seconds"])
        except Failure as exc:
            state.update(state="failed", stage=state["stage"], error=exc.record(),
                         elapsed_seconds=time.perf_counter() - started, output=None)
        except Exception:
            state.update(state="failed", error=Failure("RUN_FAILED", "Unexpected native adapter failure; inspect local configuration", request_id).record(), output=None)
        state["updated_at"] = stamp()
        if (folder / "native-loads.json").is_file():
            state["native_loads"] = read_json(folder / "native-loads.json")
            if state["native_loads"]["loaded_files"]:
                state["weight_load_attestation"] = "instrumented_native_loads"
        if (folder / "native-driving.json").is_file():
            state["native_driving"] = read_json(folder / "native-driving.json")
        write_json(folder / "status.json", state)
        return state
