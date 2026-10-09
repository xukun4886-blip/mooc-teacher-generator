import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from mooc_m1.media import MediaTools


@pytest.fixture
def media():
    root = Path(__file__).resolve().parents[1]
    executable = next((root / ".tools/ffmpeg").glob("*/bin/ffmpeg.exe"), None)
    if executable is None:
        import shutil
        executable = shutil.which("ffmpeg")
        probe = shutil.which("ffprobe")
        if not executable or not probe:
            pytest.skip("Real FFmpeg and ffprobe are required")
    else:
        probe = str(executable.with_name("ffprobe.exe"))
    return MediaTools(str(executable), probe)
