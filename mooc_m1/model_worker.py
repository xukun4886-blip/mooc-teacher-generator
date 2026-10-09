"""Real local model entry points; executed ONLY in the model's own environment.

These integrations are implemented but require native model/weight validation.
No weights are downloaded and no service is invoked by preflight.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .core import read_json, write_json, digest


def execute(payload):
    role, c, r = payload["role"], payload["config"], payload["request"]
    work, output = Path(payload["work_dir"]), Path(payload["output"])
    repo = Path(c["repo"]).resolve()
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    if c.get("device", "cuda") == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    if role == "tts":
        sys.path.insert(0, str(repo / "GPT_SoVITS"))
        # Explicit Windows tokenizer choice, never an automatic exception fallback.
        # Both packages use Jieba dictionaries; pronunciation must still be reviewed.
        if c.get("tokenizer_backend") == "jieba":
            import jieba
            import jieba.posseg
            sys.modules["jieba_fast"] = jieba
            sys.modules["jieba_fast.posseg"] = jieba.posseg
        import soundfile
        import yaml
        from GPT_SoVITS.TTS_infer_pack.TTS import TTS, TTS_Config
        # Upstream LangSegmenter resets its default detector during import.
        # Bind the explicit inventoried model AFTER that import and forbid fallback.
        import fast_langdetect.infer
        fast_langdetect.infer._default_detector = fast_langdetect.infer.LangDetector(
            fast_langdetect.infer.LangDetectConfig(
                custom_model_path=str(Path(c["fasttext_cache"]) / "lid.176.bin"), allow_fallback=False))
        selected = yaml.safe_load(Path(c["tts_config"]).read_text(encoding="utf-8"))["custom"]
        runtime_config = work / "runtime-tts.yaml"
        shutil.copyfile(c["tts_config"], runtime_config)
        # Upstream updates its inference YAML while loading weights. Keep that
        # mutation inside this request rather than changing the pinned checkout.
        explicit = TTS_Config(str(runtime_config))
        for field in ["t2s_weights_path", "vits_weights_path", "bert_base_path", "cnhuhbert_base_path"]:
            if Path(getattr(explicit, field)).resolve() != Path(selected[field]).resolve():
                raise RuntimeError("Upstream attempted model fallback: " + field)
        if str(explicit.device) != str(selected["device"]):
            raise RuntimeError("Upstream attempted device fallback")
        before_load = time.perf_counter()
        engine = TTS(explicit)
        after_load = time.perf_counter()
        args = {"text": r["text"], "text_lang": "zh", "ref_audio_path": r["reference_audio"],
                "prompt_text": r.get("reference_transcript", ""), "prompt_lang": "zh",
                "text_split_method": "cut5", "batch_size": 1, "speed_factor": r.get("speed_factor", 1.0),
                "streaming_mode": False, "return_fragment": False, "seed": 42}
        segments = r.get("speech_segments")
        timeline = []
        if segments is not None:
            import numpy as np
            if not isinstance(segments, list) or not segments:
                raise ValueError("Empty audition speech segments")
            sr, arrays, offset = None, [], 0
            before = float(r.get("pause_before", 0))
            if not 0 <= before <= 10 or not .5 <= float(args["speed_factor"]) <= 2:
                raise ValueError("Invalid audition controls")
            for segment_index, part in enumerate(segments):
                pause = float(part.get("pause_after", 0))
                if not 0 <= pause <= 10:
                    raise ValueError("Invalid pause")
                text = part["text"]
                if text.strip():
                    part_sr, audio = next(engine.run({**args, "text": text}))
                    if sr is None:
                        sr = part_sr
                        pad = np.zeros(round(sr * before), dtype=audio.dtype)
                        arrays.append(pad)
                        offset += len(pad)
                    if part_sr != sr:
                        raise ValueError("Inconsistent native sample rates")
                    timeline.append({"segment_index": segment_index, "text_sha256": __import__("hashlib").sha256(text.encode()).hexdigest(), "start_seconds": offset / sr, "end_seconds": (offset + len(audio)) / sr})
                    arrays.append(audio)
                    offset += len(audio)
                if sr is not None and pause:
                    padding = np.zeros(round(sr * pause), dtype=arrays[-1].dtype)
                    arrays.append(padding)
                    timeline.append({"type": "pause", "start_seconds": offset / sr, "end_seconds": (offset + len(padding)) / sr})
                    offset += len(padding)
                elif sr is None:
                    before += pause
            if sr is None:
                raise ValueError("No nonempty speech")
            samples = np.concatenate(arrays)
        else:
            sr, samples = next(engine.run(args))
        after_inference = time.perf_counter()
        soundfile.write(output, samples, sr)
        warm = None
        if r.get("measure_warm") is True:
            before_warm = time.perf_counter()
            warm_sr, warm_samples = next(engine.run(args))
            warm = time.perf_counter() - before_warm
            soundfile.write(work / "audio-warm.wav", warm_samples, warm_sr)
        loaded = {field: {"path": str(Path(getattr(engine.configs, field)).resolve()),
                          "sha256": digest(getattr(engine.configs, field))}
                  for field in ["t2s_weights_path", "vits_weights_path"]}
        write_json(work / "native-model.json", {"provider": "GPT-SoVITS", "actual_weight_version": engine.configs.version,
                   "loaded_primary_weights": loaded, "inference_config_sha256": digest(c["tts_config"]),
                   "cold_load_seconds": after_load - before_load,
                   "tokenizer_backend": c.get("tokenizer_backend", "jieba_fast"),
                   "first_inference_seconds": after_inference - after_load, "warm_seconds": warm,
                   "speed_factor": args["speed_factor"], "speech_timeline": timeline})
    elif role == "photo":
        import copy
        import torch
        # Retain the native instances only for an explicitly requested same-process
        # warm measurement. A second, different audio is rendered from scratch.
        import src.utils.preprocess as sad_preprocess
        import src.test_audio2coeff as sad_audio
        import src.facerender.animate as sad_animate
        from .sad_memory import offload_predictions
        # Upstream retains one CUDA prediction per frame until the entire clip
        # is stacked. Host storage prevents VRAM growing with narration length.
        sad_animate.make_animation = offload_predictions(sad_animate.make_animation)
        load_times = []
        def retained(original):
            instance = None
            def create(*args, **kwargs):
                nonlocal instance
                if instance is None:
                    before = time.perf_counter()
                    instance = original(*args, **kwargs)
                    load_times.append(time.perf_counter() - before)
                return instance
            return create
        sad_preprocess.CropAndExtract = retained(sad_preprocess.CropAndExtract)
        sad_audio.Audio2Coeff = retained(sad_audio.Audio2Coeff)
        sad_animate.AnimateFromCoeff = retained(sad_animate.AnimateFromCoeff)
        # Source is always a photograph in this adapter, never a source-video frame.
        command = [sys.executable, "inference.py", "--driven_audio", r["audio"],
                   "--source_image", r["photo"], "--result_dir", str(work / "native"),
                   "--checkpoint_dir", str(repo / "checkpoints"), "--size", str(c.get("size", 256)),
                   "--batch_size", "1",
                   "--preprocess", "full"]
        if c.get("device", "cuda") == "cpu":
            command.append("--cpu")
        import runpy
        sys.argv = command[1:]
        before_first = time.perf_counter()
        namespace = runpy.run_path(str(repo / "inference.py"), run_name="__main__")
        first_seconds = time.perf_counter() - before_first
        candidates = list((work / "native").glob("*.mp4"))
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one fresh SadTalker result")
        shutil.copyfile(candidates[0], output)
        warm_seconds = None
        if r.get("warm_audio"):
            args = copy.copy(namespace["args"])
            args.driven_audio = r["warm_audio"]
            args.result_dir = str(work / "warm-native")
            before_warm = time.perf_counter()
            namespace["main"](args)
            warm_seconds = time.perf_counter() - before_warm
            warm_candidates = list((work / "warm-native").glob("*.mp4"))
            if len(warm_candidates) != 1:
                raise RuntimeError("Expected exactly one fresh warm SadTalker result")
            shutil.copyfile(warm_candidates[0], work / "video-warm.mp4")
        write_json(work / "native-model.json", {"provider": "SadTalker", "actual_weight_version": "v0.0.2_" + str(c.get("size",256)),
                   "cold_model_load_seconds": sum(load_times), "first_generation_seconds": first_seconds,
                   "warm_seconds": warm_seconds, "warm_scope": "same native instances; different current audio" if warm_seconds else None,
                   "enhancer": None, "preprocess": "full", "size": c.get("size",256),
                   "frame_storage_policy": "detached_cpu_per_frame_v1",
                   "worker_sha256": digest(__file__), "quality_passed": False})
    elif role == "video":
        import yaml
        import hashlib
        from musetalk.utils.audio_processor import AudioProcessor
        original_features = AudioProcessor.get_audio_feature
        original_chunks = AudioProcessor.get_whisper_chunk
        driving_records = []
        def measured_features(instance, wav_path, *args, **kwargs):
            result = original_features(instance, wav_path, *args, **kwargs)
            features, length = result
            feature_hash = hashlib.sha256()
            for tensor in features:
                feature_hash.update(tensor.detach().cpu().contiguous().numpy().tobytes())
            driving_records.append({"audio_path": str(Path(wav_path).resolve()), "audio_sha256": digest(wav_path),
                "decoded_samples_16k": length, "mel_features_sha256": feature_hash.hexdigest()})
            write_json(work / "native-driving.json", driving_records)
            return result
        def measured_chunks(instance, *args, **kwargs):
            result = original_chunks(instance, *args, **kwargs)
            driving_records[-1].update(whisper_chunks_shape=list(result.shape),
                whisper_chunks_sha256=hashlib.sha256(result.detach().cpu().contiguous().numpy().tobytes()).hexdigest())
            write_json(work / "native-driving.json", driving_records)
            return result
        AudioProcessor.get_audio_feature = measured_features
        AudioProcessor.get_whisper_chunk = measured_chunks
        if c.get("memory_profile") == "cpu_staged_fp16":
            if c.get("device", "cuda") != "cuda":
                raise ValueError("cpu_staged_fp16 requires explicit CUDA inference")
            # Native model classes and identical weights, with an explicit loading
            # policy: saved CUDA tensors are staged on CPU, halved before transfer.
            # Upstream otherwise transfers the 3.4GB float32 UNet before halving.
            import torch
            from musetalk.utils import utils as native_utils
            original_load = torch.load
            cached_core = None
            unet_path = (repo / "models/musetalkV15/unet.pth").resolve()
            def load_cpu(path, *args, **kwargs):
                if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == unet_path:
                    kwargs["map_location"] = "cpu"
                return original_load(path, *args, **kwargs)
            def load_staged(unet_model_path, vae_type, unet_config, device=None):
                nonlocal cached_core
                if cached_core is not None:
                    return cached_core
                before = time.perf_counter()
                vae = native_utils.VAE(model_path=str(repo / "models" / vae_type), use_float16=True)
                torch.load = load_cpu
                try:
                    unet = native_utils.UNet(unet_config=unet_config, model_path=unet_model_path,
                                             use_float16=True, device=torch.device("cpu"))
                finally:
                    torch.load = original_load
                unet.model.to(device)
                pe = native_utils.PositionalEncoding(d_model=384)
                write_json(work / "native-model.json", {
                    "provider": "MuseTalk", "actual_weight_version": "v15",
                    "memory_profile": "cpu_staged_fp16", "inference_device": str(device),
                    "same_primary_weight_sha256": digest(unet_path),
                    "cold_core_load_seconds": time.perf_counter() - before,
                    "warm_seconds": None, "quality_passed": False})
                cached_core = (vae, unet, pe)
                return cached_core
            native_utils.load_all_model = load_staged
            # Retain the actual auxiliary instances for a requested warm run.
            from transformers import WhisperModel
            from musetalk.utils import face_parsing
            whisper_loader = WhisperModel.from_pretrained
            parser_class = face_parsing.FaceParsing
            cached_aux = {}
            def warm_whisper(*args, **kwargs):
                if "whisper" not in cached_aux:
                    cached_aux["whisper"] = whisper_loader(*args, **kwargs)
                return cached_aux["whisper"]
            def warm_parser(*args, **kwargs):
                if "parser" not in cached_aux:
                    cached_aux["parser"] = parser_class(*args, **kwargs)
                return cached_aux["parser"]
            WhisperModel.from_pretrained = staticmethod(warm_whisper)
            face_parsing.FaceParsing = warm_parser
        # Stage in ASCII paths: upstream MuseTalk uses shell-built ffmpeg commands.
        # This preserves every source frame; no portrait extraction is performed.
        native = Path(c.get("ascii_work_root", str(work))) / work.name
        if any(ch.isspace() or ord(ch) > 127 for ch in str(native)):
            raise ValueError("MuseTalk requires a configured ASCII path without spaces")
        native.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(r["video"], native / "source.mp4")
        shutil.copyfile(r["audio"], native / "driver.wav")
        task = native / "inference.yaml"
        task.write_text(yaml.safe_dump({"m1": {"video_path": str(native / "source.mp4"),
                        "audio_path": str(native / "driver.wav"), "bbox_shift": c.get("bbox_shift", 0)}}), encoding="utf-8")
        command = [sys.executable, "-m", "scripts.inference", "--inference_config", str(task),
                   "--result_dir", str(native / "results"), "--output_vid_name", "m1.mp4",
                   "--batch_size", "1", "--version", "v15",
                   "--unet_config", str(repo / "models/musetalkV15/musetalk.json"),
                   "--unet_model_path", str(repo / "models/musetalkV15/unet.pth"),
                   "--saved_coord",
                   "--ffmpeg_path", str(Path(payload["ffmpeg"]).parent)]
        if c.get("device", "cuda") == "cuda":
            command.append("--use_float16")
        import runpy
        sys.argv = ["scripts.inference"] + command[3:]
        before_first = time.perf_counter()
        namespace = runpy.run_module("scripts.inference", run_name="__main__")
        first_seconds = time.perf_counter() - before_first
        candidates = list((native / "results").rglob("m1.mp4"))
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one fresh MuseTalk result")
        shutil.copyfile(candidates[0], output)
        native_record = read_json(work / "native-model.json") if (work / "native-model.json").exists() else {
            "provider": "MuseTalk", "actual_weight_version": "v15", "memory_profile": "native"}
        native_record["first_generation_seconds"] = first_seconds
        if r.get("warm_audio"):
            import copy
            shutil.copyfile(r["warm_audio"], native / "driver-warm.wav")
            warm_task = native / "warm-inference.yaml"
            warm_task.write_text(yaml.safe_dump({"m1": {"video_path": str(native / "source.mp4"),
                "audio_path": str(native / "driver-warm.wav"), "bbox_shift": c.get("bbox_shift",0)}}), encoding="utf-8")
            args = copy.copy(namespace["args"])
            args.inference_config = str(warm_task)
            args.result_dir = str(native / "warm-results")
            before_warm = time.perf_counter()
            namespace["main"](args)
            native_record["warm_seconds"] = time.perf_counter() - before_warm
            native_record["warm_scope"] = "same native models; original full sequence; different current audio; fresh preprocessing"
            warm_candidates = list((native / "warm-results").rglob("m1.mp4"))
            if len(warm_candidates) != 1:
                raise RuntimeError("Expected exactly one fresh warm MuseTalk result")
            shutil.copyfile(warm_candidates[0], work / "video-warm.mp4")
        write_json(work / "native-model.json", native_record)
    else:
        raise ValueError("Unknown provider role")


def main():
    payload = read_json(sys.argv[1])
    import torch
    import safetensors.torch
    loaded = []
    def tracked(original):
        def call(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if isinstance(path, (str, os.PathLike)) and Path(path).is_file():
                resolved = str(Path(path).resolve())
                if resolved not in loaded:
                    loaded.append(resolved)
            return result
        return call
    torch.load = tracked(torch.load)
    safetensors.torch.load_file = tracked(safetensors.torch.load_file)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    try:
        execute(payload)
    finally:
        write_json(Path(payload["work_dir"]) / "native-loads.json", {
            "loaded_files": [{"path": p, "sha256": digest(p)} for p in loaded],
            "scope": "successful torch.load and safetensors.load_file calls in isolated native process",
            "elapsed_native_seconds": time.perf_counter() - started,
            "torch_peak_allocated_mib": torch.cuda.max_memory_allocated()/1024**2 if torch.cuda.is_available() else None,
            "torch_peak_reserved_mib": torch.cuda.max_memory_reserved()/1024**2 if torch.cuda.is_available() else None,
            "quality_passed": False})


if __name__ == "__main__":
    main()
