from pydantic import BaseModel, Field
from typing import Tuple

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id
from openharness.capcut.pyJianYingDraft import TrackType
from openharness.capcut.pyJianYingDraft.video_segment import StickerSegment
from openharness.capcut.pyJianYingDraft.segment import ClipSettings
from openharness.capcut.pyJianYingDraft.time_util import Timerange


class CapcutAddStickerInput(BaseModel):
    """添加贴纸参数"""
    draft_id: str = Field(description="草稿 ID")
    sticker_id: str = Field(description="贴纸资源 ID")
    start: int = Field(description="开始时间（微秒）")
    end: int = Field(description="结束时间（微秒）")
    scale: float = Field(default=1.0, description="缩放比例")
    transform_x: int = Field(default=0, description="X 轴偏移（像素）")
    transform_y: int = Field(default=0, description="Y 轴偏移（像素）")


def _add_sticker_impl(
    draft_id: str, sticker_id: str, start: int, end: int,
    scale: float, transform_x: int, transform_y: int,
) -> Tuple[str, str, str, str, int]:
    if end <= start:
        raise ValueError(f"Invalid time range: end ({end}) must be greater than start ({start})")
    duration = end - start
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"sticker_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.sticker, track_name=track_name)
    clip_settings = ClipSettings(
        scale_x=scale, scale_y=scale,
        transform_x=transform_x / script.width,
        transform_y=transform_y / script.height,
    )
    sticker_segment = StickerSegment(
        resource_id=sticker_id,
        target_timerange=Timerange(start=start, duration=duration),
        clip_settings=clip_settings,
    )
    script.add_segment(sticker_segment, track_name)
    script.save()
    track_id = get_track_id(script, track_name)
    return draft_id, sticker_id, track_id, sticker_segment.segment_id, duration


class CapcutAddStickerTool(BaseTool):
    name = "capcut_add_sticker"
    description = "向剪映草稿添加贴纸。支持设置缩放和位置偏移。返回 sticker_id、track_id、segment_id 和 duration。"
    input_model = CapcutAddStickerInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            draft_id, sticker_id, track_id, seg_id, dur = _add_sticker_impl(
                draft_id=arguments.draft_id, sticker_id=arguments.sticker_id,
                start=arguments.start, end=arguments.end, scale=arguments.scale,
                transform_x=arguments.transform_x, transform_y=arguments.transform_y,
            )
            return ToolResult(
                output=f"添加贴纸成功，draft_id: {draft_id}, sticker_id: {sticker_id}, "
                       f"track_id: {track_id}, segment_id: {seg_id}, duration: {dur}",
                metadata={"draft_id": draft_id, "sticker_id": sticker_id,
                          "track_id": track_id, "segment_id": seg_id, "duration": dur},
            )
        except ValueError as e:
            return ToolResult(output=f"添加贴纸失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加贴纸失败：{e}", is_error=True)
