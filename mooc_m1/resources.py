"""Sample device-level memory, keeping process-specific attribution explicitly unknown."""
import shutil
import threading
import time

from .core import Failure, run


class GPUSampler:
    def __init__(self, interval=1):
        self.executable = shutil.which("nvidia-smi")
        self.interval = interval
        self.samples = []
        self.stop = threading.Event()
        self.thread = None

    def __enter__(self):
        self.started = time.perf_counter()
        if self.executable:
            self.thread = threading.Thread(target=self._collect, daemon=True)
            self.thread.start()
        return self

    def _collect(self):
        while not self.stop.is_set():
            try:
                result = run([self.executable, "--query-gpu=index,memory.used,memory.free,utilization.gpu",
                              "--format=csv,noheader,nounits"], timeout=5)
                for row in result["stdout"].splitlines():
                    idx, used, free, util = [x.strip() for x in row.split(",")]
                    self.samples.append({"elapsed_seconds": time.perf_counter() - self.started,
                                         "gpu_index": int(idx), "device_used_mib": int(used),
                                         "device_free_mib": int(free), "device_utilization_pct": int(util)})
            except (Failure, ValueError):
                pass
            self.stop.wait(self.interval)

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=6)

    def report(self):
        return {"sample_interval_seconds": self.interval, "samples": list(self.samples),
                "device_peak_used_mib": max((s["device_used_mib"] for s in self.samples), default=None),
                "peak_model_vram_mib": None,
                "scope": "whole device including desktop and other processes; not model allocated VRAM"}
