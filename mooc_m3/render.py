from __future__ import annotations

import math
from pathlib import Path
from mooc_m1.core import Failure, run
from .timeline import srt


def duration_for_frames(duration, fps=25):
    return math.ceil(duration * fps - 1e-7) / fps


def compose(media, image, audio, portrait, captions, config, output, draft=False, timeout=300):
    """Use original slide, preserve aspect ratio, normalize all streams.

    Pad only the last visual frame for sub-frame rounding, never loop a talking clip.
    A sidebar reserves slide space; overlay placement remains subject to human review.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    width, height = (1280, 720) if config['resolution'] == '720p' else (1920, 1080)
    duration = duration_for_frames(media.inspect(audio, 'audio')['duration_seconds'])
    args = [media.ffmpeg, '-nostdin', '-v', 'error', '-y', '-loop', '1', '-i', image, '-i', audio]
    filters = []
    sidebar = bool(portrait and config.get('layout', 'overlay') == 'sidebar')
    reserved = round(width * config['size'] / 2) * 2 if sidebar else 0
    slide_width = width - reserved
    filters.append(f'[0:v]scale={slide_width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:0:(oh-ih)/2:color=0x172033,setsar=1,fps=25[page]')
    label = 'page'
    if portrait:
        args += ['-i', portrait]
        box_width = reserved if sidebar else round(width * config['size'] / 2) * 2
        box_height = height if sidebar else round(height * .65 / 2) * 2
        filters.append(f'[2:v]scale={box_width}:{box_height}:force_original_aspect_ratio=decrease,setsar=1,fps=25,tpad=stop_mode=clone:stop_duration=0.2[person]')
        position = config['position']
        x = 'W-w-16' if 'right' in position else '16'
        y = 'H-h-64' if 'bottom' in position else '16'
        if sidebar:
            x, y = str(slide_width), '(H-h)/2'
        filters.append(f'[page][person]overlay=x={x}:y={y}:eof_action=pass[overlay]')
        label = 'overlay'
    subtitle = output.parent / 'captions.srt'
    subtitle.write_text(srt(captions), encoding='utf-8')
    if config['subtitles']:
        # SRT's implicit ASS canvas is small; FontSize=22 otherwise becomes
        # ~83 output pixels at 1080p. Set the actual canvas and pixel-sized type.
        font_px = round(height / 30)
        margin = round(height / 40)
        filters.append(f"[{label}]subtitles=filename=captions.srt:force_style='PlayResX={width},PlayResY={height},FontName=Microsoft YaHei,FontSize={font_px},Outline=2,Shadow=0,MarginV={margin},MarginL={font_px},MarginR={font_px}'[captioned]")
        label = 'captioned'
    if draft:
        font = Path('C:/Windows/Fonts/msyh.ttc')
        font_option = "fontfile='" + str(font).replace('\\', '/').replace(':', '\\:') + "':" if font.is_file() else ''
        draft_label = '未审核草稿' if font.is_file() else 'DRAFT - NOT REVIEWED'
        filters.append(f"[{label}]drawtext={font_option}text='{draft_label}':fontcolor=white:fontsize=24:box=1:boxcolor=red@0.8:x=16:y=16[draft]")
        label = 'draft'
    filters.append('[1:a]aresample=48000,aformat=channel_layouts=stereo,apad[audio]')
    temp = output.with_name('publishing.mp4')
    try:
        run(args + ['-filter_complex', ';'.join(filters), '-map', f'[{label}]', '-map', '[audio]', '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '25',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', temp], timeout, cwd=output.parent)
        info = media.inspect(temp, 'video', expected_duration=duration)
        audio_info = media.inspect(temp, 'audio', expected_duration=duration)
        temp.replace(output)
        return {**{k: v for k, v in info.items() if k not in {'path', 'streams'}}, 'audio_check': {k: audio_info[k] for k in ['duration_seconds', 'silence_ratio', 'max_volume_db']},
                'frame_padding_seconds': duration - media.inspect(audio, 'audio')['duration_seconds']}
    finally:
        temp.unlink(missing_ok=True)


def join(media, paths, output, expected, timeout=600):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    listing = output.parent / 'concat.txt'
    # Names are controlled UUID/hash files. Quote paths for FFmpeg concat syntax.
    lines = []
    for p in paths:
        duration = media.inspect(p, 'video')['duration_seconds']
        lines.extend(["file '" + str(Path(p).resolve()).replace('\\', '/').replace("'", "'\\''") + "'", f'duration {duration:.6f}'])
    listing.write_text('\n'.join(lines), encoding='utf-8')
    temp = output.with_name('publishing-course.mp4')
    try:
        # AAC packet-copy can shift video start by its 1024-sample encoder delay.
        # Normalize the shared zero and encode once; explicit scene durations keep
        # source-page transitions exactly on the measured frame timeline.
        run([media.ffmpeg, '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', listing,
             '-map', '0:v:0', '-map', '0:a:0', '-vf', 'setpts=PTS-STARTPTS', '-af', 'aresample=async=1:first_pts=0',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '25',
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', str(expected), '-movflags', '+faststart', temp], timeout)
        video = media.inspect(temp, 'video', expected_duration=expected)
        audio = media.inspect(temp, 'audio', expected_duration=expected)
        temp.replace(output)
        video_start = float(next(s for s in video['streams'] if s['codec_type'] == 'video').get('start_time', 0))
        audio_start = float(next(s for s in audio['streams'] if s['codec_type'] == 'audio').get('start_time', 0))
        video_end = video_start + video['duration_seconds']
        audio_end = audio_start + audio['duration_seconds']
        if abs(video_start) > .001:
            raise Failure('TIMELINE_MISMATCH', 'Final video does not begin at the shared zero')
        return {'sha256': video['sha256'], 'duration_seconds': video['duration_seconds'], 'video_start_seconds': video_start, 'export_version': 2, 'width': video['width'], 'height': video['height'],
                'audio_start_seconds': audio_start, 'video_end_seconds': video_end, 'audio_end_seconds': audio_end,
                'av_end_delta_seconds': abs(video_end - audio_end),
                'fps': video['fps'], 'audio_check': {k: audio[k] for k in ['duration_seconds', 'silence_ratio', 'max_volume_db']}}
    finally:
        temp.unlink(missing_ok=True)
