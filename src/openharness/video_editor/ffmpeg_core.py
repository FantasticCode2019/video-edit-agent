"""Self-contained FFmpeg pipeline for video_editor.

Consolidates video/audio processing, encoding, and effects from
ffmpeg_utils.py and ffmpeg_handler.py, with no dependency on conf.cnf
or external service modules.
"""
from __future__ import annotations

import logging
import math
import os
import random
import subprocess
import tempfile
import time
from typing import Any, Optional

import ffmpeg
from PIL import Image
from pydub import AudioSegment

logger = logging.getLogger(__name__)

# Default encoding settings
_DEFAULT_THREADS = 0
_DEFAULT_FONT_DIR = "/usr/share/fonts"


# ═══════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════


class FFmpegDecoderError(Exception):
    """FFmpeg decoder error (triggers retry in run_ffmpeg_with_retry)."""


# ═══════════════════════════════════════════════════════════════════════
# Utility functions — ffprobe, format helpers
# ═══════════════════════════════════════════════════════════════════════


def get_video_duration(path: str) -> float:
    """Get video duration in seconds via ffprobe."""
    prob = ffmpeg.probe(path)
    return float(prob["format"]["duration"])


def get_video_fps(path: str) -> float:
    """Get video frame rate via ffprobe."""
    prob = ffmpeg.probe(path)
    stream = next(s for s in prob["streams"] if s["codec_type"] == "video")
    num, den = stream["r_frame_rate"].split("/")
    return float(num) / float(den)


def get_video_codec(path: str) -> str:
    """Get video codec name via ffprobe."""
    prob = ffmpeg.probe(path)
    stream = next(s for s in prob["streams"] if s["codec_type"] == "video")
    return stream["codec_name"]


def get_stream_info(path: str) -> dict:
    """Get stream info via ffprobe."""
    return ffmpeg.probe(path)


def has_audio_stream(path: str) -> bool:
    """Check if a file has an audio stream."""
    try:
        prob = ffmpeg.probe(path)
        return any(s["codec_type"] == "audio" for s in prob["streams"])
    except Exception:
        return False


def is_animated_gif_pillow(filepath: str) -> bool:
    """Check if a file is an animated GIF. Raises on WEBP."""
    with Image.open(filepath) as img:
        if img.format == "WEBP":
            raise ValueError("暂不支持 WEBP 格式的贴纸")
        return img.format == "GIF" and getattr(img, "is_animated", False)


def calculate_bufsize(bitrate: str) -> str:
    """Calculate buffer size from bitrate string (e.g. '5000k' → '10000k')."""
    if bitrate.endswith("k") or bitrate.endswith("K"):
        val = int(bitrate[:-1]) * 2
        return f"{val}k"
    elif bitrate.endswith("M") or bitrate.endswith("m"):
        val = int(bitrate[:-1]) * 2
        return f"{val}M"
    return str(int(bitrate) * 2)


def _build_stderr_msg(stderr: bytes, trace_id: float = 0) -> str:
    """Format ffmpeg stderr for logging."""
    lines = stderr.decode(errors="ignore").split("\n") if stderr else []
    tagged = "\n".join(f"[{trace_id}]{l}" for l in lines)
    return f"[{trace_id}] finish run ffmpeg:\n{tagged}"


# ═══════════════════════════════════════════════════════════════════════
# Input stream helpers
# ═══════════════════════════════════════════════════════════════════════


def get_or_input_file(file_map: dict, file_path: str, input_type: str = "i", **kwargs):
    """Get or create a cached ffmpeg input stream for the given file."""
    index = file_map.get("__c", 0)
    file_map["__c"] = index + 1 if index else 1

    args_list = sorted(f"{k}={v}" for k, v in kwargs.items())
    file_key = f"{file_path}__{':'.join(args_list)}"

    if file_key in file_map:
        if input_type == "i":
            return file_map[file_key][index]
        elif input_type == "v":
            return [file_map[file_key][0][index], file_map[file_key][1][index]]
        elif input_type == "a":
            return file_map[file_key][index]
    else:
        stream = ffmpeg.input(file_path, **kwargs)
        if input_type == "i":
            file_map[file_key] = [stream, stream]
            return stream
        elif input_type == "v":
            vs = stream.video
            a_s = stream.audio if has_audio_stream(file_path) else None
            file_map[file_key] = [[vs, vs], [a_s, a_s]]
            return [vs, a_s]
        elif input_type == "a":
            a_s = stream.audio
            file_map[file_key] = [a_s, a_s]
            return a_s


def create_black_video(duration: float, resolution: str, fps: int = 30):
    """Create a black video source stream."""
    w, h = resolution.lower().split("x")
    return (
        ffmpeg.input(f"color=c=black:size={w}x{h}:rate={fps}:duration={duration}", f="lavfi")
        .output(f"anullsrc=r=24000:cl=stereo", f="lavfi")
        .node
    )


def create_blurred_background(video_path: str, target_width: int, target_height: int):
    """Create a blurred background frame from a video file."""
    input_bg = ffmpeg.input(video_path, ss=0.3, t=0.1)
    frame = ffmpeg.filter(input_bg, "select", "eq(n,0)")
    scaled = ffmpeg.filter(frame, "scale", w=target_width, h=target_height, force_original_aspect_ratio="increase")
    cropped = ffmpeg.filter(scaled, "crop", w=target_width, h=target_height)
    blurred = ffmpeg.filter(cropped, "gblur", sigma=20)
    return ffmpeg.filter(blurred, "setsar", 1)


# ═══════════════════════════════════════════════════════════════════════
# Video / Audio / Image input pipelines
# ═══════════════════════════════════════════════════════════════════════


def get_input_videos(
    video_info_list: list[dict],
    overlay_videos: list[dict],
    resolution: Optional[str] = None,
    keep_original_audio: bool = True,
    fps: Optional[int] = None,
    fill_background: Optional[dict] = None,
) -> tuple[list, list, list]:
    """Process video inputs: scale, fill, extract audio streams.

    Returns: (video_streams, overlay_video_streams, overlay_audio_streams)
    """
    if fill_background is None:
        fill_background = {}

    w, h = (resolution or "1920x1080").lower().split("x")
    target_w, target_h = int(w), int(h)

    output_videos: list = []
    output_overlay_videos: list = []
    output_overlay_audios: list = []
    file_map: dict = {}

    for video_info in video_info_list:
        path = video_info.get("path")
        if not path:
            # Black video placeholder
            dur = video_info.get("duration", 5)
            black = create_black_video(dur, resolution or "1920x1080", fps or 30)
            output_videos.append(black)
            continue

        start_time = video_info.get("start_time", 0)
        duration = video_info.get("duration")

        kwargs = {}
        if start_time:
            kwargs["ss"] = start_time
        if duration:
            kwargs["t"] = duration

        try:
            vs, a_s = get_or_input_file(file_map, path, input_type="v", **kwargs)
        except Exception:
            vs, a_s = get_or_input_file(file_map, path, input_type="v")

        # FPS
        if fps:
            vs = ffmpeg.filter(vs, "fps", fps)

        # Scale to target resolution
        scaled = ffmpeg.filter(vs, "scale", size=f"{target_w}x{target_h}", force_original_aspect_ratio="decrease")
        padded = ffmpeg.filter(scaled, "pad", w=target_w, h=target_h, x="(ow-iw)/2", y="(oh-ih)/2", color="black")

        # Fill background modes
        fill_type = fill_background.get("selected_type", "black")
        if fill_type == "blur" and path:
            bg = create_blurred_background(path, target_w, target_h)
            final_video = ffmpeg.filter([bg, scaled], "overlay", x="(W-w)/2", y="(H-h)/2")
        elif fill_type == "image":
            bg_path = fill_background.get("image_vid")
            if bg_path and os.path.exists(bg_path):
                bg_input = ffmpeg.input(bg_path, loop=1, t=duration or 60)
                bg_scaled = ffmpeg.filter(bg_input, "scale", w=target_w, h=target_h)
                final_video = ffmpeg.filter([bg_scaled, scaled], "overlay", x="(W-w)/2", y="(H-h)/2")
            else:
                final_video = padded
        else:
            final_video = padded

        final_video = ffmpeg.filter(final_video, "setsar", 1)

        if keep_original_audio and a_s is not None:
            output_videos.append([final_video, a_s])
        else:
            output_videos.append([final_video])

    # Overlay videos (PiP)
    for ov_info in overlay_videos:
        ov_path = ov_info.get("path")
        if not ov_path:
            continue
        ov_kwargs = {}
        ss = ov_info.get("ss", 0)
        if ss:
            ov_kwargs["ss"] = ss
        ov_vs, ov_a = get_or_input_file(file_map, ov_path, input_type="v", **ov_kwargs)
        if fps:
            ov_vs = ffmpeg.filter(ov_vs, "fps", fps)
        bw, bh = ov_info["box"][2], ov_info["box"][3]
        ov_scaled = ffmpeg.filter(ov_vs, "scale", bw, bh)
        ov_final = ffmpeg.filter(ov_scaled, "setsar", 1)
        output_overlay_videos.append(ov_final)

        if ov_info.get("keep_original_audio") and ov_a is not None:
            delay_ms = int(ov_info.get("start_time", 0) * 1000)
            ov_a = ffmpeg.filter(ov_a, "adelay", f"{delay_ms}|{delay_ms}")
            ov_a = ffmpeg.filter(ov_a, "asetpts", "PTS-STARTPTS")
            output_overlay_audios.append(ov_a)

    return output_videos, output_overlay_videos, output_overlay_audios


def get_input_audios(audio_info_list: list[dict]) -> list:
    """Process audio inputs: apply delay and return ffmpeg audio streams."""
    output_audios = []
    for audio_info in audio_info_list:
        path = audio_info["path"]
        a_stream = ffmpeg.input(path).audio
        delay = audio_info.get("delay", 0)
        if delay > 0:
            delay_ms = int(delay * 1000)
            a_stream = ffmpeg.filter(a_stream, "adelay", f"{delay_ms}|{delay_ms}")
            a_stream = ffmpeg.filter(a_stream, "asetpts", "PTS-STARTPTS")
        output_audios.append(a_stream)
    return output_audios


def get_input_images(images_info: list[dict]) -> list:
    """Process image inputs (static + animated GIF): scale, rotate."""
    output: list = []
    file_map: dict = {}

    for img_info in images_info:
        file_path = img_info["path"]
        is_gif = is_animated_gif_pillow(file_path)

        if is_gif:
            try:
                gif_dur = get_video_duration(file_path)
                total_needed = img_info["end_time"]
                loop_count = math.ceil(total_needed / gif_dur) if gif_dur > 0 else 1
                origin = get_or_input_file(file_map, file_path, stream_loop=loop_count - 1)
            except Exception:
                origin = get_or_input_file(file_map, file_path, stream_loop=1)
        else:
            origin = get_or_input_file(file_map, file_path)

        bw, bh = img_info["box"][2], img_info["box"][3]
        scaled = ffmpeg.filter(origin, "scale", size=f"{bw}x{bh}")

        rotate = img_info.get("rotate", 0)
        if rotate:
            hypot = math.hypot(bw, bh)
            w_delta = (hypot - bw) / 2
            h_delta = (hypot - bh) / 2
            img_info["box"][0] -= w_delta
            img_info["box"][1] -= h_delta
            scaled = ffmpeg.filter(
                scaled, "rotate", angle=f"{rotate}*PI/180",
                ow="hypot(iw,ih)", oh="hypot(iw,ih)", c="none",
            )

        output.append(scaled)
    return output


def fix_overlay_video_box(overlay_videos: list[dict], resolution: Optional[str]) -> None:
    """Auto-fix overlay box dimensions if missing."""
    if not resolution or not overlay_videos:
        return
    for v in overlay_videos:
        if any(v.get("box", [])):
            pass  # box is already set


# ═══════════════════════════════════════════════════════════════════════
# Audio volume management
# ═══════════════════════════════════════════════════════════════════════


def _get_audio_volume_db(path: str) -> float:
    """Get audio volume in dBFS using pydub."""
    audio = AudioSegment.from_file(path)
    return audio.dBFS


def _extract_audio(video_path: str, output_path: str) -> str:
    """Extract audio from video to a temp file."""
    (
        ffmpeg.input(video_path)
        .output(output_path, **{"q:a": 0, "map": "a"})
        .overwrite_output()
        .run(quiet=True)
    )
    return output_path


def _set_audio_volume(input_path: str, output_path: str, volume_db: float) -> str:
    """Set audio volume using ffmpeg volume + alimiter filter."""
    in_stream = ffmpeg.input(input_path)
    audio = in_stream.audio.filter("volume", f"{volume_db}dB").filter(
        "alimiter", limit=0.98, attack=5, release=50
    )
    ffmpeg.output(audio, output_path, acodec="aac").overwrite_output().run(quiet=True)
    return output_path


def _merge_audio_with_video(video_path: str, audio_path: str, output_path: str) -> str:
    """Merge audio track into video (replace existing audio)."""
    video = ffmpeg.input(video_path)
    audio = ffmpeg.input(audio_path)
    ffmpeg.output(video, audio, output_path, **{"c:v": "copy", "map": "0:v:0", "map": "1:a:0", "shortest": None}).overwrite_output().run(quiet=True)
    return output_path


def apply_audio_fade(
    input_path: str,
    output_path: str,
    fade_in: Optional[float] = None,
    fade_out: Optional[float] = None,
    duration: Optional[float] = None,
) -> str:
    """Apply fade-in and/or fade-out to an audio file."""
    in_stream = ffmpeg.input(input_path)
    audio = in_stream.audio

    filters = ""
    if fade_in and fade_in > 0:
        filters += f"afade=t=in:st=0:d={fade_in}:curve=tri,"
    if fade_out and fade_out > 0 and duration:
        start = duration - fade_out
        filters += f"afade=t=out:st={start}:d={fade_out}:curve=tri,"

    if filters:
        audio = audio.filter_multi(f"{filters.rstrip(',')}")
    ffmpeg.output(audio, output_path, acodec="aac").overwrite_output().run(quiet=True)
    return output_path


def pre_adjust_audio_volume(audio_info_list: list[dict], video_info_list: list[dict]) -> None:
    """Auto-adjust audio volumes based on priority: TTS > Original > BGM.

    Mutates audio_info_list and video_info_list in place.
    """
    # Determine categories
    tts_audios = [a for a in audio_info_list if not a.get("is_bg_music", False)]
    bgm_audios = [a for a in audio_info_list if a.get("is_bg_music", False)]
    has_original = any(v.get("keep_original_audio", True) for v in video_info_list)

    # Volume levels (5dB steps)
    if tts_audios:
        tts_vol = 0       # loudest
        orig_vol = -5     # medium
        bgm_vol = -10     # quietest
    elif has_original:
        orig_vol = 0
        bgm_vol = -5
    else:
        bgm_vol = 0

    # Apply to videos (original audio)
    for v in video_info_list:
        if v.get("keep_original_audio", True) and orig_vol != 0:
            v["_volume_db"] = orig_vol

    # Apply to TTS
    for a in tts_audios:
        if tts_vol != 0:
            a["_volume_db"] = tts_vol

    # Apply to BGM
    for a in bgm_audios:
        if bgm_vol != 0:
            a["_volume_db"] = bgm_vol


# ═══════════════════════════════════════════════════════════════════════
# Effects: speed, reverse
# ═══════════════════════════════════════════════════════════════════════


def apply_speed(input_path: str, output_path: str, speed: float) -> str:
    """Apply speed change to video (setpts + chained atempo)."""
    video_speed = 1.0 / speed

    # Build atempo chain (atempo only supports 0.5–2.0)
    atempo_filters: list[str] = []
    remaining = speed
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining}")

    in_stream = ffmpeg.input(input_path)
    video = in_stream.video.filter("setpts", f"{video_speed}*PTS")

    if has_audio_stream(input_path):
        audio = in_stream.audio
        for af in atempo_filters:
            audio = ffmpeg.filter(audio, af.split("=")[0], af.split("=")[1])
        ffmpeg.output(video, audio, output_path, vcodec="libx264", acodec="aac").overwrite_output().run(quiet=True)
    else:
        ffmpeg.output(video, output_path, vcodec="libx264").overwrite_output().run(quiet=True)

    return output_path


def reverse_video(input_path: str, output_path: str) -> str:
    """Reverse video and audio playback."""
    in_stream = ffmpeg.input(input_path)
    video = in_stream.video.filter("reverse")

    if has_audio_stream(input_path):
        audio = in_stream.audio.filter("areverse")
        ffmpeg.output(video, audio, output_path, vcodec="libx264", acodec="aac").overwrite_output().run(quiet=True)
    else:
        ffmpeg.output(video, output_path, vcodec="libx264").overwrite_output().run(quiet=True)

    return output_path


# ═══════════════════════════════════════════════════════════════════════
# Main pipeline: run_ffmpeg (concat / hard-cut)
# ═══════════════════════════════════════════════════════════════════════


def run_ffmpeg(
    input_videos: list[dict],
    resolution: Optional[str] = None,
    output_file: str = "output.mp4",
    input_audios: Optional[list[dict]] = None,
    overlay_videos: Optional[list[dict]] = None,
    images_info: Optional[list[dict]] = None,
    subtitle_file: str = "",
    video_filter: Optional[dict] = None,
    fill_background: Optional[dict] = None,
    Bitrate_control: Optional[str] = None,
    fps: int = 30,
    font_dir: str = _DEFAULT_FONT_DIR,
    threads: int = _DEFAULT_THREADS,
) -> str:
    """Main FFmpeg pipeline: concat videos, mix audio, overlay images, apply filters."""
    if input_audios is None:
        input_audios = []
    if overlay_videos is None:
        overlay_videos = []
    if images_info is None:
        images_info = []
    if video_filter is None:
        video_filter = {}
    if fill_background is None:
        fill_background = {}

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    fix_overlay_video_box(overlay_videos, resolution)
    output_list: list = []

    # 1. Build input video streams
    keep_original_audio = any(v.get("keep_original_audio", True) for v in input_videos)
    input_streams, input_overlay_videos, input_overlay_audios = get_input_videos(
        input_videos, overlay_videos, resolution,
        keep_original_audio=keep_original_audio, fps=fps, fill_background=fill_background,
    )

    if not input_streams:
        raise ValueError("input_videos is required")

    # 2. Concat (hard-cut)
    concat_node = ffmpeg.concat(*input_streams, v=1, a=1 if keep_original_audio else 0).node
    concatenated_video = concat_node[0]

    # 3. Audio mixing
    audio_streams = get_input_audios(input_audios) + input_overlay_audios
    if audio_streams:
        if keep_original_audio:
            audio_streams.append(concat_node[1])
        audio_mix = ffmpeg.filter(audio_streams, "amix", inputs=len(audio_streams), normalize=0)
        audio_mix = ffmpeg.filter(audio_mix, "alimiter", limit=0.98, attack=5, release=50)
        output_list.append(audio_mix)
    else:
        if keep_original_audio:
            output_list.append(concat_node[1])

    # 4. Overlay videos (PiP)
    for ov_stream, ov_info in zip(input_overlay_videos, overlay_videos):
        concatenated_video = ffmpeg.filter(
            [concatenated_video, ov_stream], "overlay",
            enable=f"between(t,{ov_info['start_time']},{ov_info['end_time']})",
            x=ov_info["box"][0], y=ov_info["box"][1],
        )

    # 5. Image overlays (stickers, GIFs)
    image_inputs = get_input_images(images_info)
    for img_input, img_info in zip(image_inputs, images_info):
        overlay_args = {
            "enable": f"between(t,{img_info['start_time']},{img_info['end_time']})",
            "x": img_info["box"][0],
            "y": img_info["box"][1],
        }
        if is_animated_gif_pillow(img_info["path"]):
            overlay_args["eof_action"] = "pass"
        concatenated_video = ffmpeg.filter([concatenated_video, img_input], "overlay", **overlay_args)

    # 6. Color filter
    if video_filter:
        concatenated_video = ffmpeg.filter(
            [concatenated_video], "eq",
            brightness=video_filter.get("brightness", 0),
            contrast=video_filter.get("contrast", 1),
            saturation=video_filter.get("saturation", 1),
        )

    # 7. Subtitles
    if subtitle_file:
        concatenated_video = ffmpeg.filter([concatenated_video], "subtitles", subtitle_file, fontsdir=font_dir)

    output_list.append(concatenated_video)

    # 8. Build and run ffmpeg command
    if Bitrate_control:
        cmd = (
            ffmpeg.output(*output_list, output_file, threads=threads, vsync="2", fps_mode="cfr", **{
                "c:v": "libx264", "b:v": Bitrate_control,
                "minrate": Bitrate_control, "maxrate": Bitrate_control,
                "bufsize": calculate_bufsize(Bitrate_control), "nal-hrd": "cbr",
            })
            .overwrite_output()
            .global_args("-fflags", "+genpts", "-nostdin")
        )
    else:
        cmd = (
            ffmpeg.output(*output_list, output_file, threads=threads, vsync="2", fps_mode="cfr")
            .overwrite_output()
            .global_args("-fflags", "+genpts", "-nostdin")
        )

    logger.info(f"FFmpeg cmd: {' '.join(cmd.get_args())}")

    try:
        _, stderr = cmd.run(capture_stderr=True)
        if stderr:
            if b"Error submitting packet to decoder" in stderr:
                raise FFmpegDecoderError("Error submitting packet to decoder")
            if b"Invalid data found when processing input" in stderr:
                raise FFmpegDecoderError("Invalid data found when processing input")
    except ffmpeg.Error as e:
        stderr = e.stderr
        err_text = stderr.decode(errors="ignore") if stderr else ""
        err_lines = [l for l in err_text.split("\n") if "error" in l.lower() or "invalid" in l.lower()][-5:]
        raise RuntimeError(f"FFmpeg error:\n{''.join(err_lines)}\nCommand: {' '.join(cmd.get_args())}")

    logger.info(f"FFmpeg output: {output_file}")
    return output_file


def run_ffmpeg_with_retry(*args, max_retries: int = 5, **kwargs) -> str:
    """Run FFmpeg with automatic retry on decoder errors."""
    for attempt in range(1, max_retries + 1):
        try:
            return run_ffmpeg(*args, **kwargs)
        except FFmpegDecoderError as e:
            logger.warning(f"FFmpeg attempt {attempt} failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(3 + random.randint(1, 3))


# ═══════════════════════════════════════════════════════════════════════
# Main pipeline: run_ffmpeg_with_transitions (xfade)
# ═══════════════════════════════════════════════════════════════════════


def run_ffmpeg_with_transitions(
    video_info_list: list[dict],
    transitions: list[dict],
    resolution: Optional[str] = None,
    output_file: str = "output.mp4",
    input_audios: Optional[list[dict]] = None,
    overlay_videos: Optional[list[dict]] = None,
    images_info: Optional[list[dict]] = None,
    subtitle_file: str = "",
    video_filter: Optional[dict] = None,
    fill_background: Optional[dict] = None,
    Bitrate_control: Optional[str] = None,
    fps: int = 30,
    font_dir: str = _DEFAULT_FONT_DIR,
    threads: int = _DEFAULT_THREADS,
) -> str:
    """FFmpeg pipeline with xfade transitions between clips."""
    if input_audios is None:
        input_audios = []
    if overlay_videos is None:
        overlay_videos = []
    if images_info is None:
        images_info = []
    if video_filter is None:
        video_filter = {}
    if fill_background is None:
        fill_background = {}

    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    fix_overlay_video_box(overlay_videos, resolution)
    output_list: list = []

    keep_original_audio = any(v.get("keep_original_audio", True) for v in video_info_list)

    # Get clip durations
    clip_durations: list[float] = []
    for v_info in video_info_list:
        if v_info.get("duration"):
            dur = v_info["duration"]
        elif v_info.get("path"):
            try:
                total = get_video_duration(v_info["path"])
                dur = total - v_info.get("start_time", 0)
            except Exception:
                dur = 5.0
        else:
            dur = 5.0
        clip_durations.append(dur)

    # Build input streams
    input_streams, _, _ = get_input_videos(
        video_info_list, overlay_videos, resolution,
        keep_original_audio=keep_original_audio, fps=fps, fill_background=fill_background,
    )

    # Separate video and audio streams
    video_streams = []
    audio_streams = []
    for s in input_streams:
        if isinstance(s, list):
            video_streams.append(s[0])
            audio_streams.append(s[1] if len(s) > 1 else None)
        else:
            video_streams.append(s)
            audio_streams.append(None)

    # --- Video xfade chain ---
    first_offset = clip_durations[0] - transitions[0]["duration"]
    xfade_result = ffmpeg.filter(
        [video_streams[0], video_streams[1]],
        "xfade",
        transition=transitions[0]["type"],
        duration=transitions[0]["duration"],
        offset=first_offset,
    )
    cumulative = clip_durations[0] + clip_durations[1] - transitions[0]["duration"]

    for i in range(2, len(video_streams)):
        t = transitions[i - 1]
        current_offset = cumulative - t["duration"]
        xfade_result = ffmpeg.filter(
            [xfade_result, video_streams[i]],
            "xfade",
            transition=t["type"],
            duration=t["duration"],
            offset=current_offset,
        )
        cumulative += clip_durations[i] - t["duration"]

    concatenated_video = xfade_result

    # --- Audio crossfade chain ---
    valid_audio = [(i, a) for i, a in enumerate(audio_streams) if a is not None]
    if len(valid_audio) >= 2:
        indices, auds = zip(*valid_audio)
        acf = ffmpeg.filter(
            [auds[0], auds[1]], "acrossfade",
            d=transitions[min(indices[1] - 1, len(transitions) - 1)]["duration"],
            c1="tri", c2="tri",
        )
        for j in range(2, len(auds)):
            t_idx = min(indices[j] - 1, len(transitions) - 1)
            acf = ffmpeg.filter(
                [acf, auds[j]], "acrossfade",
                d=transitions[t_idx]["duration"], c1="tri", c2="tri",
            )
        mixed_audio = acf
    elif len(valid_audio) == 1:
        mixed_audio = valid_audio[0][1]
    else:
        mixed_audio = None

    # Mix with extra audio tracks
    extra_audios = get_input_audios(input_audios)
    if mixed_audio and extra_audios:
        all_audio = [mixed_audio] + extra_audios
        audio_mix = ffmpeg.filter(all_audio, "amix", inputs=len(all_audio), normalize=0)
        audio_mix = ffmpeg.filter(audio_mix, "alimiter", limit=0.98, attack=5, release=50)
        output_list.append(audio_mix)
    elif extra_audios:
        if len(extra_audios) > 1:
            audio_mix = ffmpeg.filter(extra_audios, "amix", inputs=len(extra_audios), normalize=0)
            audio_mix = ffmpeg.filter(audio_mix, "alimiter", limit=0.98, attack=5, release=50)
            output_list.append(audio_mix)
        else:
            output_list.append(extra_audios[0])
    elif mixed_audio:
        output_list.append(mixed_audio)

    # Overlay videos (PiP)
    for ov_info in overlay_videos:
        if ov_info.get("path"):
            ov_stream = get_input_images([{"path": ov_info["path"], "box": ov_info["box"], "start_time": 0, "end_time": 999}])[0]
            concatenated_video = ffmpeg.filter(
                [concatenated_video, ov_stream], "overlay",
                enable=f"between(t,{ov_info['start_time']},{ov_info['end_time']})",
                x=ov_info["box"][0], y=ov_info["box"][1],
            )

    # Image overlays
    image_inputs = get_input_images(images_info)
    for img_input, img_info in zip(image_inputs, images_info):
        overlay_args = {
            "enable": f"between(t,{img_info['start_time']},{img_info['end_time']})",
            "x": img_info["box"][0],
            "y": img_info["box"][1],
        }
        if is_animated_gif_pillow(img_info["path"]):
            overlay_args["eof_action"] = "pass"
        concatenated_video = ffmpeg.filter([concatenated_video, img_input], "overlay", **overlay_args)

    # Color filter
    if video_filter:
        concatenated_video = ffmpeg.filter(
            [concatenated_video], "eq",
            brightness=video_filter.get("brightness", 0),
            contrast=video_filter.get("contrast", 1),
            saturation=video_filter.get("saturation", 1),
        )

    # Subtitles
    if subtitle_file:
        concatenated_video = ffmpeg.filter([concatenated_video], "subtitles", subtitle_file, fontsdir=font_dir)

    output_list.append(concatenated_video)

    # Build and run
    if Bitrate_control:
        cmd = (
            ffmpeg.output(*output_list, output_file, threads=threads, vsync="2", fps_mode="cfr", **{
                "c:v": "libx264", "b:v": Bitrate_control,
                "minrate": Bitrate_control, "maxrate": Bitrate_control,
                "bufsize": calculate_bufsize(Bitrate_control), "nal-hrd": "cbr",
            })
            .overwrite_output()
            .global_args("-fflags", "+genpts", "-nostdin")
        )
    else:
        cmd = (
            ffmpeg.output(*output_list, output_file, threads=threads, vsync="2", fps_mode="cfr")
            .overwrite_output()
            .global_args("-fflags", "+genpts", "-nostdin")
        )

    logger.info(f"FFmpeg (xfade) cmd: {' '.join(cmd.get_args())}")

    try:
        _, stderr = cmd.run(capture_stderr=True)
    except ffmpeg.Error as e:
        stderr = e.stderr
        err_text = stderr.decode(errors="ignore") if stderr else ""
        err_lines = [l for l in err_text.split("\n") if "error" in l.lower() or "invalid" in l.lower()][-5:]
        raise RuntimeError(f"FFmpeg xfade error:\n{''.join(err_lines)}\nCommand: {' '.join(cmd.get_args())}")

    logger.info(f"FFmpeg (xfade) output: {output_file}")
    return output_file
