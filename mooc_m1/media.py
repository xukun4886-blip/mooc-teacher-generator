from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path

from PIL import Image

from .core import Failure, digest, run


class MediaTools:
    def __init__(self, ffmpeg="ffmpeg", ffprobe="ffprobe", timeout=180,
                 silence_db=-45, silence_seconds=1, max_silence_ratio=0.95):
        self.ffmpeg, self.ffprobe, self.timeout = ffmpeg, ffprobe, timeout
        self.silence_db, self.silence_seconds = silence_db, silence_seconds
        self.max_silence_ratio = max_silence_ratio

    def inspect(self, path, kind, min_duration=None, expected_duration=None, tolerance=0.25):
        path = Path(path).resolve()
        if not path.is_file() or path.stat().st_size == 0:
            raise Failure("NO_VALID_MEDIA", "Missing or empty media", str(path))
        result = {"path": str(path), "sha256": digest(path), "size_bytes": path.stat().st_size}
        if kind == "photo":
            try:
                with Image.open(path) as im:
                    fmt, size = im.format, im.size
                    im.verify()
                with Image.open(path) as im:
                    im.load()
            except Exception as exc:
                raise Failure("UNDECODABLE", "Image cannot be decoded", str(path)) from exc
            if fmt not in {"PNG", "JPEG"}:
                raise Failure("INPUT_INCOMPATIBLE", "Expected real JPEG or PNG", str(path))
            result.update(format=fmt, width=size[0], height=size[1])
            return result
        try:
            probe = run([self.ffprobe, "-v", "error", "-show_format", "-show_streams",
                         "-of", "json", path], self.timeout)
            data = json.loads(probe["stdout"])
        except Failure as exc:
            if exc.code == "RUN_FAILED":
                raise Failure("UNDECODABLE", "Media probe failed", str(path)) from exc
            raise
        streams = data.get("streams", [])
        wanted = "video" if kind == "video" else "audio"
        matching = [s for s in streams if s.get("codec_type") == wanted]
        if not matching:
            raise Failure("INPUT_INCOMPATIBLE", f"No {wanted} stream", str(path))
        duration = float(matching[0].get("duration") or data.get("format", {}).get("duration") or 0)
        if not math.isfinite(duration) or duration <= 0:
            raise Failure("NO_VALID_MEDIA", "No positive finite duration", str(path))
        if min_duration is not None and duration < min_duration:
            raise Failure("INPUT_INCOMPATIBLE", "Duration below required minimum", str(path))
        if expected_duration is not None and abs(duration - expected_duration) > tolerance:
            raise Failure("DURATION_MISMATCH", "Output duration differs from driving audio", str(path))
        # Probe headers alone cannot detect truncated/corrupt packets. Decode all selected streams.
        try:
            decoded = run([self.ffmpeg, "-nostdin", "-v", "error", "-xerror", "-i", path,
                           "-map", f"0:{wanted[0]}:0", "-f", "null", "-"], self.timeout)
            if decoded["stderr"].strip():
                raise Failure("UNDECODABLE", "Decoder reported media errors", str(path))
        except Failure as exc:
            if exc.code == "RUN_FAILED":
                raise Failure("UNDECODABLE", "Media full decode failed", str(path)) from exc
            raise
        stream = matching[0]
        result.update(duration_seconds=duration, format=data.get("format", {}).get("format_name"),
                      codec=stream.get("codec_name"), streams=streams,
                      sample_rate=stream.get("sample_rate"), width=stream.get("width"), height=stream.get("height"))
        if kind == "video":
            result["fps"] = float(Fraction(stream.get("avg_frame_rate", "0/1")))
        else:
            detection = run([self.ffmpeg, "-nostdin", "-hide_banner", "-i", path, "-map", "0:a:0",
                             "-af", f"silencedetect=noise={self.silence_db}dB:d={self.silence_seconds},volumedetect",
                             "-f", "null", "-"], self.timeout)
            silence = sum(float(x) for x in re.findall(r"silence_duration: ([\d.]+)", detection["stderr"]))
            ratio = min(1, silence / duration)
            peaks = re.findall(r"max_volume: ([-\d.]+) dB", detection["stderr"])
            peak_db = float(peaks[-1]) if peaks else None
            result.update(silence_seconds=silence, silence_ratio=ratio,
                          max_volume_db=peak_db,
                          silence_policy={"noise_db": self.silence_db, "min_seconds": self.silence_seconds,
                                          "max_ratio": self.max_silence_ratio})
            if ratio >= self.max_silence_ratio or (peak_db is not None and peak_db <= self.silence_db):
                raise Failure("ABNORMAL_SILENCE", "Audio is predominantly silent", str(path))
        return result
