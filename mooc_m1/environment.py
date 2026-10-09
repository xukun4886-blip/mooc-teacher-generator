import importlib.metadata
import platform
import shutil
import sys
from pathlib import Path

from .core import Failure, run, stamp


def inventory(config):
    tools = {}
    for name in ["ffmpeg", "ffprobe", "nvidia-smi", "nvcc", "git", "pdftoppm"]:
        executable = config.get("tools", {}).get(name) or shutil.which(name)
        if name in {"ffmpeg", "ffprobe"} and not executable:
            found = list(Path(".tools/ffmpeg").glob(f"*/bin/{name}.exe"))
            executable = str(found[0].resolve()) if found else None
        entry = {"path": executable, "available": bool(executable)}
        if executable:
            try:
                version_arg = "--version" if name == "git" else "-version" if name in {"ffmpeg", "ffprobe"} else "--version"
                if name not in {"nvidia-smi", "pdftoppm"}:
                    entry["version"] = run([executable, version_arg], 15)["stdout"].splitlines()[0]
            except Failure as exc:
                entry["error"] = exc.record()
        tools[name] = entry
    gpu = {"available": False, "devices": [], "peak_vram_mib": None}
    if tools["nvidia-smi"]["available"]:
        try:
            result = run([tools["nvidia-smi"]["path"], "--query-gpu=name,driver_version,memory.total,memory.used,memory.free",
                          "--format=csv,noheader,nounits"], 15)
            for line in result["stdout"].splitlines():
                name, driver, total, used, free = [p.strip() for p in line.split(",")]
                gpu["devices"].append({"name": name, "driver_version": driver,
                                       "total_mib": int(total), "used_mib_at_probe": int(used), "free_mib_at_probe": int(free)})
            gpu["available"] = True
        except Failure as exc:
            gpu["error"] = exc.record()
    packages = {}
    for name in ["python-pptx", "Pillow", "lxml", "XlsxWriter", "pywin32", "PyYAML", "pytest", "torch"]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    hardware = None
    if sys.platform == "win32":
        import json
        try:
            hardware = json.loads(run(["powershell", "-NoProfile", "-Command",
                "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $o=Get-CimInstance Win32_OperatingSystem; @{caption=$o.Caption; version=$o.Version; total_memory_kib=$o.TotalVisibleMemorySize; free_memory_kib=$o.FreePhysicalMemory} | ConvertTo-Json -Compress"], 30)["stdout"])
        except (Failure, ValueError):
            hardware = {"probe": "unavailable"}
    return {"schema_version": "m1.environment.v1", "recorded_at": stamp(),
            "os": platform.platform(), "hardware": hardware, "python": sys.version,
            "python_executable": sys.executable, "packages": packages, "tools": tools, "gpu": gpu,
            "cuda_note": "nvidia-smi driver CUDA compatibility is not an installed CUDA toolkit/PyTorch runtime",
            "model_environment_policy": "separate executable per model; no model dependency installed in validation environment"}
