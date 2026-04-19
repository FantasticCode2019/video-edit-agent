"""Executor: converts a validated VideoEditRequest into FFMPEGHandler parameters and runs it.

This is the bridge between the structured schema layer and the existing ffmpeg pipeline.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any, Optional

from .schema import VideoEditRequest
from .validator import validate_request

logger = logging.getLogger(__name__)


def to_ffmpeg_params(req: VideoEditRequest) -> dict[str, Any]:
    """Convert a VideoEditRequest to the parameter dict expected by run_ffmpeg / FFMPEGHandler."""

    video_info_list: list[dict[str, Any]] = []
    for v in req.videos:
        info: dict[str, Any] = {
            "path": v.path,
            "start_time": v.start_time,
            "keep_original_audio": v.keep_original_audio,
        }
        if v.duration is not None:
            info["duration"] = v.duration
        video_info_list.append(info)

    audio_info_list: list[dict[str, Any]] = []
    for a in req.audios:
        info = {
            "path": a.path,
            "start_time": a.start_time,
            "delay": a.delay,
            "is_bg_music": a.is_bg_music,
            "volume": a.volume,
        }
        if a.duration is not None:
            info["duration"] = a.duration
        if a.fade_in_duration is not None:
            info["fade_in_duration"] = a.fade_in_duration
        if a.fade_out_duration is not None:
            info["fade_out_duration"] = a.fade_out_duration
        audio_info_list.append(info)

    image_info_list: list[dict[str, Any]] = []
    for img in req.images:
        image_info_list.append({
            "path": img.path,
            "start_time": img.start_time,
            "end_time": img.end_time,
            "box": img.box,
            "rotate": img.rotate,
        })

    # 画中画视频叠加
    overlay_video_list: list[dict[str, Any]] = []
    for ov in req.overlay_videos:
        overlay_video_list.append({
            "path": ov.path,
            "ss": ov.ss,
            "start_time": ov.start_time,
            "end_time": ov.end_time,
            "box": ov.box,
            "keep_original_audio": ov.keep_overlay_audio,
        })

    # 背景填充
    fill_background: dict[str, Any] = {}
    if req.fill_background:
        fill_background["selected_type"] = req.fill_background.type
        if req.fill_background.type == "image" and req.fill_background.image_path:
            fill_background["image_vid"] = req.fill_background.image_path

    # 全局滤镜
    video_filter: Optional[dict[str, Any]] = None
    if req.video_filter:
        video_filter = req.video_filter.model_dump()

    # 转场
    transitions: Optional[list[dict[str, Any]]] = None
    if req.transitions:
        transitions = [{"type": t.type, "duration": t.duration} for t in req.transitions]

    return {
        "video_info_list": video_info_list,
        "audio_info_list": audio_info_list,
        "image_info_list": image_info_list,
        "overlay_video_list": overlay_video_list,
        "subtitle_list": [],
        "resolution": req.resolution,
        "video_filter": video_filter,
        "fill_background": fill_background,
        "fps": req.fps,
        "bitrate": req.bitrate,
        "transitions": transitions,
    }


def _resolve_subtitle(req: VideoEditRequest, temp_dir: str) -> Optional[str]:
    """Resolve subtitle config to a file path, generating via Whisper if needed."""
    if req.subtitles is None:
        return None

    if req.subtitles.mode == "file":
        return req.subtitles.file_path

    # whisper mode
    from .subtitle_handler import generate_subtitles

    # 从 resolution 解析视频尺寸
    w, h = 0, 0
    if req.resolution:
        parts = req.resolution.lower().split("x")
        if len(parts) == 2:
            try:
                w, h = int(parts[0]), int(parts[1])
            except ValueError:
                pass

    style_dict = req.subtitles.style.model_dump() if req.subtitles.style else None
    highlight_style_dict = (
        req.subtitles.highlight_style.model_dump() if req.subtitles.highlight_style else None
    )
    return generate_subtitles(
        audio_source=req.videos[0].path,
        language=req.subtitles.language,
        output_dir=temp_dir,
        style=style_dict,
        highlight_keywords=req.subtitles.highlight_keywords,
        highlight_style=highlight_style_dict,
        video_width=w,
        video_height=h,
    )


def _preprocess_clips(req: VideoEditRequest, temp_dir: str) -> VideoEditRequest:
    """对需要预处理的视频片段执行倒放/变速操作。

    这些效果无法在 run_ffmpeg 的 filter graph 中以 per-clip 方式应用，
    所以在执行前先预处理成临时文件。
    """
    from .ffmpeg_core import reverse_video, apply_speed

    needs_preprocess = any(v.reverse or (v.speed != 1.0) for v in req.videos)
    if not needs_preprocess:
        return req

    new_videos = []
    for i, v in enumerate(req.videos):
        path = v.path

        # 倒放
        if v.reverse:
            reversed_path = os.path.join(temp_dir, f"reversed_{i}.mp4")
            reverse_video(path, reversed_path)
            path = reversed_path

        # 变速
        if v.speed != 1.0:
            speed_path = os.path.join(temp_dir, f"speed_{i}_{v.speed}x.mp4")
            apply_speed(path, speed_path, v.speed)
            path = speed_path

        new_videos.append(v.model_copy(update={"path": path}))

    return req.model_copy(update={"videos": new_videos})


def build_dry_run(req: VideoEditRequest) -> dict[str, Any]:
    """Validate and convert without executing — useful for previewing the ffmpeg params.

    Returns:
        dict with keys: "params" (ffmpeg params dict), "warnings" (list[str]),
        "subtitle_mode" (str or None).
    """
    validation = validate_request(req)
    params = to_ffmpeg_params(req)
    return {
        "params": params,
        "warnings": validation.warnings,
        "subtitle_mode": req.subtitles.mode if req.subtitles else None,
    }


def execute(req: VideoEditRequest, output_dir: Optional[str] = None) -> str:
    """Full pipeline: validate → convert → resolve subtitles → run ffmpeg.

    Args:
        req: A VideoEditRequest.
        output_dir: Directory for the output file. Uses a temp dir if None.

    Returns:
        Absolute path to the output video file.
    """
    validation = validate_request(req)
    if validation.warnings:
        for w in validation.warnings:
            logger.warning(f"[video_editor] {w}")

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="video_editor_out_")
    os.makedirs(output_dir, exist_ok=True)

    # Per-clip 预处理（倒放/变速）
    req = _preprocess_clips(req, output_dir)

    params = to_ffmpeg_params(req)
    output_file = os.path.join(output_dir, req.output_filename)

    # 解析字幕
    subtitle_file = _resolve_subtitle(req, output_dir)

    # 导入现有 ffmpeg 管道
    from .ffmpeg_core import run_ffmpeg_with_retry, run_ffmpeg_with_transitions, pre_adjust_audio_volume

    # 音量优先级预处理
    if params["audio_info_list"] or any(
        v.get("keep_original_audio") for v in params["video_info_list"]
    ):
        pre_adjust_audio_volume(params["audio_info_list"], params["video_info_list"])

    # 选择执行路径：有转场走 xfade，否则走 concat
    if params["transitions"]:
        run_ffmpeg_with_transitions(
            video_info_list=params["video_info_list"],
            transitions=params["transitions"],
            resolution=params["resolution"],
            output_file=output_file,
            input_audios=params["audio_info_list"],
            overlay_videos=params["overlay_video_list"],
            images_info=params["image_info_list"],
            subtitle_file=subtitle_file or "",
            video_filter=params["video_filter"] or {},
            fill_background=params["fill_background"],
            Bitrate_control=params["bitrate"],
            fps=params["fps"],
        )
    else:
        run_ffmpeg_with_retry(
            input_videos=params["video_info_list"],
            resolution=params["resolution"],
            input_audios=params["audio_info_list"],
            overlay_videos=params["overlay_video_list"],
            images_info=params["image_info_list"],
            subtitle_file=subtitle_file or "",
            output_file=output_file,
            video_filter=params["video_filter"] or {},
            fill_background=params["fill_background"],
            Bitrate_control=params["bitrate"],
            fps=params["fps"],
        )

    logger.info(f"[video_editor] 输出文件: {output_file}")
    return output_file
