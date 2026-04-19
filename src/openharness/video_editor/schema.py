"""Pydantic models defining the structured JSON schema for video editing requests.

LLM outputs JSON conforming to VideoEditRequest; Pydantic validates format and types
before the request reaches FFMPEGHandler.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Per-clip models
# ---------------------------------------------------------------------------


class VideoFilter(BaseModel):
    """视频滤镜（亮度/对比度/饱和度）。"""
    brightness: float = Field(default=0, description="亮度调整，0 为不变")
    contrast: float = Field(default=1, description="对比度，1 为不变")
    saturation: float = Field(default=1, description="饱和度，1 为不变")


class VideoClip(BaseModel):
    """单个视频片段，支持截取、变速、倒放、裁剪、独立调色。"""
    path: str = Field(description="视频文件本地路径")
    start_time: float = Field(default=0, description="截取起始时间（秒）")
    duration: Optional[float] = Field(default=None, description="截取时长（秒），None 表示到结尾")
    keep_original_audio: bool = Field(default=True, description="是否保留原声")

    # Tier 2 — per-clip effects
    speed: float = Field(default=1.0, description="播放速度倍率，<1 慢放，>1 快进，1.0 正常")
    reverse: bool = Field(default=False, description="是否倒放")
    crop: Optional[list[int]] = Field(default=None, description="裁剪区域 [x, y, width, height]")
    filter: Optional[VideoFilter] = Field(default=None, description="独立调色，覆盖全局 video_filter")

    @field_validator("start_time")
    @classmethod
    def start_time_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("start_time 必须 >= 0")
        return v

    @field_validator("duration")
    @classmethod
    def duration_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("duration 必须 > 0")
        return v

    @field_validator("speed")
    @classmethod
    def speed_range(cls, v: float) -> float:
        if v <= 0 or v > 100:
            raise ValueError("speed 必须 > 0 且 <= 100")
        return v

    @field_validator("crop")
    @classmethod
    def crop_four_elements(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        if v is not None and len(v) != 4:
            raise ValueError("crop 必须为 [x, y, width, height] 四个整数")
        return v


# ---------------------------------------------------------------------------
# Audio models
# ---------------------------------------------------------------------------


class AudioTrack(BaseModel):
    """音频轨道（TTS/BGM）。"""
    path: str = Field(description="音频文件本地路径")
    start_time: float = Field(default=0, description="音频截取起始时间（秒）")
    duration: Optional[float] = Field(default=None, description="音频截取时长（秒）")
    delay: float = Field(default=0, description="在输出时间轴上的延迟（秒）")
    is_bg_music: bool = Field(default=False, description="是否为背景音乐")
    fade_in_duration: Optional[float] = Field(default=None, description="淡入时长（秒）")
    fade_out_duration: Optional[float] = Field(default=None, description="淡出时长（秒）")
    volume: float = Field(default=1.0, description="音量倍数，1.0 为原始音量")

    @field_validator("start_time", "delay")
    @classmethod
    def non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("值必须 >= 0")
        return v

    @field_validator("duration", "fade_in_duration", "fade_out_duration")
    @classmethod
    def optional_positive(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("值必须 > 0")
        return v

    @field_validator("volume")
    @classmethod
    def volume_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("volume 必须 > 0")
        return v


# ---------------------------------------------------------------------------
# Subtitle models
# ---------------------------------------------------------------------------


class SubtitleStyle(BaseModel):
    """字幕视觉样式。所有字段可选，未设置则用 ASS 默认值。"""
    font: Optional[str] = Field(default=None, description="字体名称，如 '思源黑体'、'微软雅黑'")
    font_size: Optional[int] = Field(default=None, description="字体大小（像素）")
    font_color: Optional[str] = Field(default=None, description="字体颜色，如 '#FFFF00' 或 'FFFF00'")
    bold: bool = Field(default=False, description="是否加粗")
    italic: bool = Field(default=False, description="是否斜体")
    stroke_width: Optional[float] = Field(default=None, description="描边宽度（像素）")
    stroke_color: Optional[str] = Field(default=None, description="描边颜色")
    shadow_color: Optional[str] = Field(default=None, description="阴影颜色")
    bg_color: Optional[str] = Field(default=None, description="背景色（触发 OpaqueBG 样式）")
    alignment: Optional[int] = Field(default=None, description="对齐方式 1-9（数字键盘布局）")
    pos_x: Optional[int] = Field(default=None, description="字幕绝对定位 X 坐标")
    pos_y: Optional[int] = Field(default=None, description="字幕绝对定位 Y 坐标")
    rotate: int = Field(default=0, description="旋转角度")

    @field_validator("alignment")
    @classmethod
    def alignment_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 9):
            raise ValueError("alignment 必须为 1-9（数字键盘布局）")
        return v


class SubtitleConfig(BaseModel):
    """字幕配置：外部文件或 Whisper 语音识别，支持样式定制和关键词高亮。"""
    mode: Literal["file", "whisper"] = Field(description="字幕来源：file=外部文件, whisper=语音识别")
    file_path: Optional[str] = Field(default=None, description="mode=file 时的字幕文件路径（.ass/.srt）")
    language: str = Field(default="zh", description="mode=whisper 时的语言代码")
    style: Optional[SubtitleStyle] = Field(default=None, description="字幕样式（仅 whisper 模式生效）")
    highlight_keywords: Optional[list[str]] = Field(
        default=None, description="需要高亮的关键词列表（仅 whisper 模式生效）",
    )
    highlight_style: Optional[SubtitleStyle] = Field(
        default=None,
        description="高亮文本的样式（font_color、bold、stroke_width、bg_color 等），仅 whisper 模式生效",
    )

    @model_validator(mode="after")
    def file_path_required_for_file_mode(self) -> SubtitleConfig:
        if self.mode == "file" and not self.file_path:
            raise ValueError("mode=file 时必须提供 file_path")
        return self


# ---------------------------------------------------------------------------
# Overlay models
# ---------------------------------------------------------------------------


class ImageOverlay(BaseModel):
    """静态图片或 GIF 叠加。"""
    path: str = Field(description="图片文件本地路径")
    start_time: float = Field(description="叠加开始时间（秒）")
    end_time: float = Field(description="叠加结束时间（秒）")
    box: list[int] = Field(description="位置和大小 [x, y, width, height]")
    rotate: int = Field(default=0, description="旋转角度")

    @field_validator("box")
    @classmethod
    def box_four_elements(cls, v: list[int]) -> list[int]:
        if len(v) != 4:
            raise ValueError("box 必须为 [x, y, width, height] 四个整数")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> ImageOverlay:
        if self.end_time <= self.start_time:
            raise ValueError("end_time 必须大于 start_time")
        return self


class VideoOverlay(BaseModel):
    """画中画视频叠加（支持透明通道 webm）。"""
    path: str = Field(description="叠加视频文件路径（支持透明通道 webm）")
    start_time: float = Field(description="叠加开始时间（秒）")
    end_time: float = Field(description="叠加结束时间（秒）")
    box: list[int] = Field(description="位置和大小 [x, y, width, height]")
    keep_overlay_audio: bool = Field(default=False, description="是否保留叠加视频的原声")
    ss: float = Field(default=0, description="叠加视频的播放起始偏移（秒）")

    @field_validator("box")
    @classmethod
    def box_four_elements(cls, v: list[int]) -> list[int]:
        if len(v) != 4:
            raise ValueError("box 必须为 [x, y, width, height] 四个整数")
        return v

    @field_validator("ss")
    @classmethod
    def ss_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("ss 必须 >= 0")
        return v

    @model_validator(mode="after")
    def end_after_start(self) -> VideoOverlay:
        if self.end_time <= self.start_time:
            raise ValueError("end_time 必须大于 start_time")
        return self


# ---------------------------------------------------------------------------
# Transition model
# ---------------------------------------------------------------------------


class Transition(BaseModel):
    """两个视频片段之间的转场效果。"""
    type: Literal[
        "fade", "fadeblack", "fadewhite",
        "slideleft", "slideright", "slideup", "slidedown",
        "circlecrop", "circleopen", "circleclose",
        "dissolve", "pixelize", "radial",
        "smoothleft", "smoothright", "smoothup", "smoothdown",
        "wipeleft", "wiperight", "wipeup", "wipedown",
    ] = Field(description="转场类型")
    duration: float = Field(default=1.0, description="转场时长（秒）")

    @field_validator("duration")
    @classmethod
    def duration_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("转场 duration 必须 > 0")
        return v


# ---------------------------------------------------------------------------
# FillBackground model
# ---------------------------------------------------------------------------


class FillBackground(BaseModel):
    """视频宽高比不匹配时的背景填充方式。"""
    type: Literal["black", "blur", "image"] = Field(
        default="black",
        description="填充类型：black=黑边, blur=毛玻璃, image=自定义图片",
    )
    image_path: Optional[str] = Field(
        default=None,
        description="type=image 时的背景图片路径",
    )


# ---------------------------------------------------------------------------
# Top-level request model
# ---------------------------------------------------------------------------


class VideoEditRequest(BaseModel):
    """完整的视频编辑请求 — LLM 输出的目标结构。

    Agent 将自然语言解析为此结构的 JSON，由 Pydantic 校验后
    传给 executor 转换为 FFMPEGHandler 参数。
    """

    videos: list[VideoClip] = Field(description="视频片段列表，按拼接顺序排列")
    audios: list[AudioTrack] = Field(default_factory=list, description="音频轨道列表")
    subtitles: Optional[SubtitleConfig] = Field(default=None, description="字幕配置")
    images: list[ImageOverlay] = Field(default_factory=list, description="图片叠加列表")

    # Tier 1 — 暴露已有能力
    overlay_videos: list[VideoOverlay] = Field(default_factory=list, description="画中画视频叠加列表")
    fill_background: Optional[FillBackground] = Field(default=None, description="背景填充模式")
    fps: int = Field(default=30, description="输出帧率")
    bitrate: Optional[str] = Field(default=None, description="输出码率，如 '5000k' 或 '10M'")

    # Global filter
    resolution: str = Field(default="1920x1080", description="输出分辨率，格式 WIDTHxHEIGHT")
    video_filter: Optional[VideoFilter] = Field(default=None, description="全局视频滤镜")
    output_filename: str = Field(default="output.mp4", description="输出文件名")

    # Tier 3 — 转场
    transitions: Optional[list[Transition]] = Field(default=None, description="片段间转场列表，长度必须为 videos 数量 - 1")

    @field_validator("videos")
    @classmethod
    def at_least_one_video(cls, v: list[VideoClip]) -> list[VideoClip]:
        if not v:
            raise ValueError("至少需要一个视频片段")
        return v

    @field_validator("resolution")
    @classmethod
    def valid_resolution(cls, v: str) -> str:
        parts = v.lower().split("x")
        if len(parts) != 2:
            raise ValueError("resolution 格式应为 WIDTHxHEIGHT，如 1920x1080")
        try:
            w, h = int(parts[0]), int(parts[1])
            if w <= 0 or h <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("resolution 的宽高必须为正整数")
        return v

    @field_validator("fps")
    @classmethod
    def fps_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("fps 必须 > 0")
        return v

    @model_validator(mode="after")
    def transitions_count_matches_videos(self) -> VideoEditRequest:
        if self.transitions is not None:
            expected = len(self.videos) - 1
            if len(self.transitions) != expected:
                raise ValueError(
                    f"transitions 数量 ({len(self.transitions)}) "
                    f"应为 videos 数量 - 1 ({expected})"
                )
        return self
