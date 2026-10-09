"""One serial SadTalker instance. All narration is inferred from current audio."""
from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
import time
from pathlib import Path

from mooc_m1.core import Failure, digest, read_json, run, write_json
from mooc_m2.content import fingerprint


def descriptor(config):
    repo = Path(config['repo']).resolve()
    revision = run(['git', '-C', repo, 'rev-parse', 'HEAD'], 15)['stdout'].strip()
    if revision != config['expected_code_revision']:
        raise Failure('MODEL_CHANGED', 'SadTalker commit 与配置的基线不一致')
    if run(['git', '-C', repo, 'diff', '--name-only', 'HEAD'], 15)['stdout'].strip():
        raise Failure('MODEL_CHANGED', 'SadTalker 源码存在未记录修改')
    weights = []
    for relative, expected in config['expected_weights'].items():
        path = repo / relative
        if not path.resolve().is_relative_to(repo) or not path.is_file() or digest(path) != expected:
            raise Failure('MODEL_CHANGED', 'SadTalker 权重缺失或摘要不符：' + relative)
        weights.append({'name': relative, 'sha256': expected, 'bytes': path.stat().st_size})
    if len(weights) < 4:
        raise Failure('MODEL_CONFIG_MISSING', '须配置全部主/辅助权重摘要')
    from mooc_m1 import sad_memory
    runtime = {}
    for package in ['torch', 'torchvision', 'safetensors', 'face-alignment', 'numpy', 'scipy',
                    'scikit-image', 'librosa', 'facexlib', 'gfpgan', 'basicsr', 'opencv-python',
                    'imageio', 'imageio-ffmpeg', 'pydub', 'kornia', 'PyYAML', 'yacs', 'Pillow',
                    'setuptools', 'numba', 'llvmlite']:
        try:
            runtime[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            runtime[package] = None
    runtime['python'] = sys.version.split()[0]
    runtime['ffmpeg'] = run([config.get('ffmpeg', 'ffmpeg'), '-version'], 10)['stdout'].splitlines()[0]
    return {'provider': 'SadTalker', 'code_revision': revision, 'weight_version': 'v0.0.2_256_full',
            'weights': weights, 'runtime': runtime,
            'implementation_sha256': fingerprint({'engine': digest(__file__), 'memory': digest(sad_memory.__file__)}),
            'render': {'size': 256, 'preprocess': 'full', 'enhancer': None, 'fps': 25, 'frame_storage': 'detached_cpu_per_frame_v1'}}


def runtime_readiness():
    import importlib.util
    missing = [name for name in ['torch', 'torchvision', 'scipy', 'cv2', 'skimage', 'safetensors',
                                 'facexlib', 'gfpgan', 'basicsr', 'librosa', 'kornia', 'yacs', 'face_alignment']
               if importlib.util.find_spec(name) is None]
    errors = [{'code': 'MODEL_DEPENDENCY_MISSING', 'message': '缺少模型依赖：' + ', '.join(missing)}] if missing else []
    if sys.version_info[:2] != (3, 10):
        errors.append({'code': 'MODEL_RUNTIME_UNVALIDATED', 'message': '当前部署基线要求独立 Python 3.10 环境'})
    if not missing:
        try:
            import importlib
            for name in ['torchvision', 'cv2', 'skimage', 'safetensors', 'facexlib',
                         'gfpgan', 'basicsr', 'librosa', 'kornia', 'yacs', 'face_alignment']:
                importlib.import_module(name)
            import torch
            if not torch.cuda.is_available():
                errors.append({'code': 'RESOURCE_INSUFFICIENT', 'message': 'CUDA GPU 不可用'})
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Model runtime import/CUDA readiness failed')
            errors.append({'code': 'MODEL_RUNTIME_UNVALIDATED', 'message': '模型依赖实际导入或 CUDA 探测失败，请检查服务启动日志'})
    return errors


class ResidentSadTalker:
    def __init__(self, config, model):
        self.config, self.model = config, model
        self.loaded = False
        self.boundary = lambda: None

    def load(self):
        if self.loaded:
            return 0.
        started = time.perf_counter()
        if descriptor(self.config) != self.model:
            raise Failure('MODEL_CHANGED', '服务启动后源码、权重、依赖或实现已变化，请重启并重新检查')
        repo = Path(self.config['repo']).resolve()
        sys.path.insert(0, str(repo))
        os.chdir(repo)  # Dedicated worker, no local workbench threads in this process.
        os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        import torch
        import weakref
        owner = weakref.proxy(self)
        import safetensors.torch
        from src.utils.init_path import init_path
        from src.utils.preprocess import CropAndExtract
        from src.test_audio2coeff import Audio2Coeff
        import src.facerender.animate as animate
        from mooc_m1.sad_memory import offload_predictions
        if not torch.cuda.is_available():
            raise Failure('RESOURCE_INSUFFICIENT', '云端 CUDA GPU 不可用')
        # Preserve the local long-page memory fix and add cancellation per frame.
        if not hasattr(animate, '_mooc_original_animation'):
            animate._mooc_original_animation = animate.make_animation
        original_animation = offload_predictions(animate._mooc_original_animation)
        def controlled(source, semantics, targets, generator, *args, **kwargs):
            before = time.perf_counter()
            def frame(*a, **kw):
                owner.boundary()
                return generator(*a, **kw)
            result = original_animation(source, semantics, targets, frame, *args, **kwargs)
            torch.cuda.synchronize()
            owner.phase_times['face_renderer_with_cpu_offload_seconds'] = time.perf_counter() - before
            return result
        animate.make_animation = controlled
        import src.utils.paste_pic as paste
        import src.utils.videoio as videoio
        def timed(obj, name, label):
            original_key = '_mooc_original_' + name
            if not hasattr(obj, original_key):
                setattr(obj, original_key, getattr(obj, name))
            original = getattr(obj, original_key)
            def call(*args, **kwargs):
                before = time.perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    owner.phase_times[label] = owner.phase_times.get(label, 0.) + time.perf_counter() - before
            setattr(obj, name, call)
        timed(animate.imageio, 'mimsave', 'small_video_encoding_seconds')
        timed(animate, 'paste_pic', 'full_photo_decode_clone_encode_mux_seconds')
        timed(paste.cv2, 'seamlessClone', 'seamless_clone_seconds')
        timed(videoio, 'save_video_with_watermark', 'ffmpeg_audio_mux_seconds')
        animate.save_video_with_watermark = videoio.save_video_with_watermark
        paste.save_video_with_watermark = videoio.save_video_with_watermark
        paths = init_path(str(repo / 'checkpoints'), str(repo / 'src/config'), 256, False, 'full')
        loads = []
        originals = (torch.load, safetensors.torch.load_file)
        def tracked(loader):
            def load(path, *args, **kwargs):
                result = loader(path, *args, **kwargs)
                if isinstance(path, (str, Path)) and Path(path).is_file():
                    loads.append({'name': str(Path(path).resolve().relative_to(repo)), 'sha256': digest(path)})
                return result
            return load
        torch.load, safetensors.torch.load_file = map(tracked, originals)
        try:
            self.preprocess = CropAndExtract(paths, 'cuda')
            self.coeff = Audio2Coeff(paths, 'cuda')
            self.animate = animate.AnimateFromCoeff(paths, 'cuda')
        finally:
            torch.load, safetensors.torch.load_file = originals
        expected = {item['name']: item['sha256'] for item in self.model['weights']}
        if not loads or any(expected.get(item['name']) != item['sha256'] for item in loads):
            raise Failure('MODEL_CHANGED', '实际加载权重与服务器声明不符')
        self.actual_loads = loads
        self.loaded = True
        return time.perf_counter() - started

    def generate(self, photo, audio, folder, batch_size, boundary):
        self.boundary = boundary
        self.phase_times = {}
        boundary()
        import torch
        torch.cuda.reset_peak_memory_stats()
        load_seconds = self.load()
        from src.generate_batch import get_data
        from src.generate_facerender_batch import get_facerender_data
        started = time.perf_counter()
        key = fingerprint({'photo': digest(photo), 'model': self.model})
        cache = Path(self.config['storage']) / 'photo-preprocess' / key
        manifest = cache / 'manifest.json'
        prep = read_json(manifest) if manifest.is_file() else None
        hit = bool(prep and all((cache / f['name']).is_file() and digest(cache / f['name']) == f['sha256'] for f in prep['files']))
        before = time.perf_counter()
        if not hit:
            # Keep prior failed pre-processing folders for diagnosis.
            cache.mkdir(parents=True, exist_ok=True)
            from PIL import Image
            with Image.open(photo) as image:
                extension = '.png' if image.format == 'PNG' else '.jpg'
            source_photo = cache / ('source' + extension)
            shutil.copyfile(photo, source_photo)  # Exact bytes; upstream dispatches by suffix.
            first, crop, info = self.preprocess.generate(str(source_photo), str(cache), 'full', source_image_flag=True, pic_size=256)
            if first is None:
                raise Failure('INPUT_INCOMPATIBLE', '教师照片未检出可用人脸')
            import json
            info = json.loads(json.dumps(info, default=lambda item: item.item()))
            prep = {'first': str(Path(first).relative_to(cache)), 'crop': str(Path(crop).relative_to(cache)), 'crop_info': info,
                    'source': source_photo.name,
                    'files': [{'name': str(Path(x).relative_to(cache)), 'sha256': digest(x)} for x in [first, crop, source_photo]]}
            write_json(manifest, prep)
        first, crop = str(cache / prep['first']), str(cache / prep['crop'])
        timings = {'model_load_seconds': load_seconds, 'model_warm': load_seconds == 0,
                   'photo_preprocess_cache_hit': hit, 'photo_preprocess_seconds': time.perf_counter() - before}
        boundary()
        before = time.perf_counter()
        data = get_data(first, str(audio), 'cuda', None, still=False)
        timings['audio_preprocess_seconds'] = time.perf_counter() - before
        before = time.perf_counter()
        coeff = self.coeff.generate(data, str(folder), 0, None)
        torch.cuda.synchronize()
        timings['audio_to_coeff_seconds'] = time.perf_counter() - before
        boundary()
        before = time.perf_counter()
        data = get_facerender_data(coeff, crop, first, str(audio), batch_size, None, None, None,
                                  expression_scale=1., still_mode=False, preprocess='full', size=256)
        timings['render_data_seconds'] = time.perf_counter() - before
        before = time.perf_counter()
        result = self.animate.generate(data, str(folder), str(cache / prep['source']), prep['crop_info'],
                                       enhancer=None, background_enhancer=None, preprocess='full', img_size=256)
        torch.cuda.synchronize()
        timings['render_clone_encode_seconds'] = time.perf_counter() - before
        timings['renderer_breakdown'] = self.phase_times.copy()
        boundary()
        output = folder / 'portrait.mp4'
        if Path(result).resolve() != output.resolve():
            shutil.copyfile(result, output)
        timings.update(inference_seconds=time.perf_counter() - started,
                       actual_loaded_weights=self.actual_loads, resources={
                           'peak_allocated_mib': torch.cuda.max_memory_allocated() / 1024**2,
                           'peak_reserved_mib': torch.cuda.max_memory_reserved() / 1024**2,
                           'device': torch.cuda.get_device_name(), 'device_total_mib': torch.cuda.get_device_properties(0).total_memory / 1024**2},
                       batch_size=batch_size, quality_verified=False)
        return output, timings
