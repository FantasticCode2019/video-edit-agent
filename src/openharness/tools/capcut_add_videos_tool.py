from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id, find_transition_type
from openharness.capcut.pyJianYingDraft import ScriptFile, TrackType
from openharness.capcut.pyJianYingDraft.video_segment import VideoSegment
from openharness.capcut.pyJianYingDraft.local_materials import VideoMaterial
from openharness.capcut.pyJianYingDraft.segment import ClipSettings
from openharness.capcut.pyJianYingDraft.time_util import Timerange


class VideoInfo(BaseModel):
    """单个视频信息"""
    video_path: str = Field(description="视频文件本地路径")
    start: int = Field(description="时间轴开始时间（微秒）")
    end: int = Field(description="时间轴结束时间（微秒）")
    duration: int | None = Field(default=None, description="视频总时长（微秒，可选）")
    transition: str | None = Field(default=None, description="转场效果名称（可选）")
    transition_duration: int = Field(default=500000, description="转场持续时间（微秒）")
    volume: float = Field(default=1.0, description="音量 [0, 10]")


class CapcutAddVideosInput(BaseModel):
    """添加视频参数"""
    draft_id: str = Field(description="草稿 ID")
    video_infos: List[VideoInfo] = Field(description="视频信息列表")
    alpha: float = Field(default=1.0, ge=0, le=1, description="全局透明度")
    scale_x: float = Field(default=1.0, description="X 轴缩放")
    scale_y: float = Field(default=1.0, description="Y 轴缩放")
    transform_x: int = Field(default=0, description="X 轴位置偏移（像素）")
    transform_y: int = Field(default=0, description="Y 轴位置偏移（像素）")


def _parse_video_data(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("video_infos should be a list")
    result = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"the {i}th item should be a dict")
        required = ["video_path", "start", "end"]
        missing = [f for f in required if f not in item]
        if missing:
            raise ValueError(f"the {i}th item is missing required fields: {', '.join(missing)}")
        duration = item.get("duration", item["end"] - item["start"])
        result.append({
            "video_path": item["video_path"],
            "width": item.get("width"),
            "height": item.get("height"),
            "start": item["start"],
            "end": item["end"],
            "duration": duration,
            "transition": item.get("transition"),
            "transition_duration": item.get("transition_duration", 500000),
            "volume": item.get("volume", 1.0),
        })
    return result


def _add_video_to_draft(
    script: ScriptFile, track_name: str, video: Dict[str, Any],
    alpha: float, scale_x: float, scale_y: float,
    transform_x: int, transform_y: int,
) -> Tuple[str, int]:
    video_material = VideoMaterial(video["video_path"])
    display_duration = video["end"] - video["start"]
    clip_settings = ClipSettings(
        alpha=alpha, scale_x=scale_x, scale_y=scale_y,
        transform_x=transform_x / script.width,
        transform_y=transform_y / script.height,
    )
    video_segment = VideoSegment(
        material=video_material,
        target_timerange=Timerange(start=video["start"], duration=display_duration),
        source_timerange=Timerange(start=0, duration=min(video_material.duration, display_duration)),
        volume=video.get("volume", 1.0),
        clip_settings=clip_settings,
    )
    if video.get("transition"):
        tt = find_transition_type(video["transition"])
        if tt:
            video_segment.add_transition(tt, duration=video.get("transition_duration", 500000))
    script.add_segment(video_segment, track_name)
    return video_segment.segment_id, display_duration


def _add_videos_impl(
    draft_id: str, video_infos: List[Dict[str, Any]],
    alpha: float, scale_x: float, scale_y: float,
    transform_x: int, transform_y: int,
) -> Tuple[str, str, List[str], List[str]]:
    if not video_infos:
        raise ValueError("video_infos cannot be empty")
    videos = _parse_video_data(video_infos)
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"video_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.video, track_name=track_name, relative_index=10)
    segment_ids = []
    current_track_end = 0
    for i, video in enumerate(videos):
        if i > 0 and current_track_end > 0:
            original_duration = video["end"] - video["start"]
            video["start"] = current_track_end
            video["end"] = video["start"] + original_duration
        segment_id, actual_duration = _add_video_to_draft(
            script, track_name, video, alpha, scale_x, scale_y, transform_x, transform_y,
        )
        segment_ids.append(segment_id)
        current_track_end = video["start"] + actual_duration
    script.save()
    track_id = get_track_id(script, track_name)
    video_ids = [v.material_id for v in script.materials.videos]
    return draft_id, track_id, video_ids, segment_ids


class CapcutAddVideosTool(BaseTool):
    name = "capcut_add_videos"
    description = "向剪映草稿批量添加视频素材。支持设置透明度、缩放、位置偏移和转场效果。返回 track_id、video_ids 和 segment_ids。"
    input_model = CapcutAddVideosInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            video_infos = [v.model_dump() for v in arguments.video_infos]
            draft_id, track_id, video_ids, segment_ids = _add_videos_impl(
                draft_id=arguments.draft_id, video_infos=video_infos,
                alpha=arguments.alpha, scale_x=arguments.scale_x,
                scale_y=arguments.scale_y, transform_x=arguments.transform_x,
                transform_y=arguments.transform_y,
            )
            return ToolResult(
                output=f"添加视频成功，draft_id: {draft_id}, track_id: {track_id}, "
                       f"video_ids: {video_ids}, segment_ids: {segment_ids}",
                metadata={"draft_id": draft_id, "track_id": track_id,
                          "video_ids": video_ids, "segment_ids": segment_ids},
            )
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(output=f"添加视频失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加视频失败：{e}", is_error=True)
