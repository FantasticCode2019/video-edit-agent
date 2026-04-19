"""Business logic validation for VideoEditRequest.

Pydantic handles format/type validation; this module checks runtime constraints
like file existence, timeline consistency, and cross-field dependencies.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .schema import VideoEditRequest


class VideoEditValidationError(Exception):
    """Raised when a VideoEditRequest has fatal validation errors."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"校验失败: {'; '.join(errors)}")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def validate_request(req: VideoEditRequest) -> ValidationResult:
    """Validate a VideoEditRequest against runtime constraints.

    Returns a ValidationResult. Callers should check .ok before proceeding;
    .warnings contains non-fatal issues worth surfacing to the user.

    Raises VideoEditValidationError if there are fatal errors (convenience
    for callers who prefer exception-based flow).
    """
    result = ValidationResult()

    # --- video files ---
    for i, v in enumerate(req.videos):
        if not os.path.exists(v.path):
            result.errors.append(f"videos[{i}].path 文件不存在: {v.path}")

    # --- audio files ---
    for i, a in enumerate(req.audios):
        if not os.path.exists(a.path):
            result.errors.append(f"audios[{i}].path 文件不存在: {a.path}")

    # --- image overlays ---
    for i, img in enumerate(req.images):
        if not os.path.exists(img.path):
            result.errors.append(f"images[{i}].path 文件不存在: {img.path}")

    # --- video overlays (PiP) ---
    for i, ov in enumerate(req.overlay_videos):
        if not os.path.exists(ov.path):
            result.errors.append(f"overlay_videos[{i}].path 文件不存在: {ov.path}")

    # --- subtitle ---
    if req.subtitles:
        if req.subtitles.mode == "file":
            if req.subtitles.file_path and not os.path.exists(req.subtitles.file_path):
                result.errors.append(f"字幕文件不存在: {req.subtitles.file_path}")
        elif req.subtitles.mode == "whisper":
            try:
                import whisper as _  # noqa: F401
            except ImportError:
                result.errors.append(
                    "whisper 模式需要安装 openai-whisper 包: pip install openai-whisper"
                )

    # --- fill background ---
    if req.fill_background and req.fill_background.type == "image":
        if not req.fill_background.image_path:
            result.errors.append("fill_background.type=image 时必须提供 image_path")
        elif not os.path.exists(req.fill_background.image_path):
            result.errors.append(f"背景图片不存在: {req.fill_background.image_path}")

    # --- bitrate format ---
    if req.bitrate:
        if not re.match(r"^\d+[kKmM]?$", req.bitrate):
            result.errors.append(
                f"bitrate 格式无效: {req.bitrate}，应为 '5000k' 或 '10M' 等格式"
            )

    # --- timeline sanity ---
    total_video_duration = 0.0
    for i, v in enumerate(req.videos):
        if v.duration:
            total_video_duration += v.duration
            if v.start_time + v.duration > 7200:
                result.warnings.append(f"videos[{i}] 截取范围超过2小时，请确认是否正确")
        # speed affects effective duration
        if v.speed != 1.0:
            effective_dur = (v.duration or 60) / v.speed
            total_video_duration += effective_dur - (v.duration or 60)

    # audio delay vs video duration
    if total_video_duration > 0:
        for i, a in enumerate(req.audios):
            if a.delay > total_video_duration:
                result.warnings.append(
                    f"audios[{i}].delay ({a.delay}s) 超过视频总时长 ({total_video_duration:.1f}s)，"
                    "该音频可能不会被听到"
                )

    # --- per-clip speed extremes ---
    for i, v in enumerate(req.videos):
        if v.speed < 0.25:
            result.warnings.append(
                f"videos[{i}].speed={v.speed} 极慢，可能导致异常长的视频"
            )
        if v.speed > 4.0:
            result.warnings.append(
                f"videos[{i}].speed={v.speed} 极快，音频可能失真"
            )

    # --- transitions vs video count ---
    if req.transitions:
        # Pydantic already validates count, but double-check here for safety
        expected = len(req.videos) - 1
        if len(req.transitions) != expected:
            result.errors.append(
                f"transitions 数量 ({len(req.transitions)}) "
                f"应为 videos 数量 - 1 ({expected})"
            )
        # transition duration should be shorter than clip durations
        for i, t in enumerate(req.transitions):
            clip_dur = req.videos[i].duration
            if clip_dur and t.duration >= clip_dur:
                result.warnings.append(
                    f"transitions[{i}].duration ({t.duration}s) "
                    f">= 前一段视频时长 ({clip_dur}s)，转场可能异常"
                )

    # --- overlay timeline ---
    for i, img in enumerate(req.images):
        if total_video_duration > 0 and img.end_time > total_video_duration:
            result.warnings.append(
                f"images[{i}].end_time ({img.end_time}s) "
                f"超过视频总时长 ({total_video_duration:.1f}s)"
            )

    for i, ov in enumerate(req.overlay_videos):
        if total_video_duration > 0 and ov.end_time > total_video_duration:
            result.warnings.append(
                f"overlay_videos[{i}].end_time ({ov.end_time}s) "
                f"超过视频总时长 ({total_video_duration:.1f}s)"
            )

    if result.errors:
        raise VideoEditValidationError(result.errors)

    return result
