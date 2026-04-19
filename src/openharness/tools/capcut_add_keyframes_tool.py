from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple, Optional

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import find_segment
from openharness.capcut.pyJianYingDraft import ScriptFile
from openharness.capcut.pyJianYingDraft.keyframe import KeyframeProperty
from openharness.capcut.pyJianYingDraft.segment import VisualSegment


class KeyframeInfo(BaseModel):
    """单个关键帧信息"""
    segment_id: str = Field(description="目标片段 ID")
    property: str = Field(description="属性类型")
    offset: int = Field(description="时间偏移（微秒）")
    value: float = Field(description="属性值")


class CapcutAddKeyframesInput(BaseModel):
    """添加关键帧参数"""
    draft_id: str = Field(description="草稿 ID")
    keyframes: List[KeyframeInfo] = Field(description="关键帧列表")


def _add_keyframes_impl(
    draft_id: str, keyframes: List[Dict[str, Any]],
) -> Tuple[str, int, List[str]]:
    if not keyframes:
        raise ValueError("keyframes cannot be empty")
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    keyframes_added = 0
    affected_segments: List[str] = []
    supported = {
        "KFTypePositionX", "KFTypePositionY", "KFTypeScaleX", "KFTypeScaleY",
        "KFTypeRotation", "KFTypeAlpha", "UNIFORM_SCALE",
        "KFTypeSaturation", "KFTypeContrast", "KFTypeBrightness", "KFTypeVolume",
    }
    for kf in keyframes:
        seg_id = kf.get("segment_id")
        prop = kf.get("property")
        offset = kf.get("offset")
        value = kf.get("value")
        if not all([seg_id, prop, offset is not None, value is not None]):
            continue
        if prop not in supported:
            continue
        segment = find_segment(script, seg_id)
        if segment is None or not isinstance(segment, VisualSegment):
            continue
        try:
            prop_enum = KeyframeProperty(prop)
        except ValueError:
            continue
        segment_duration = segment.duration
        if segment_duration <= 0:
            continue
        relative_offset = max(0.0, min(1.0, float(offset) / segment_duration))
        time_offset = int(relative_offset * segment_duration)
        segment.add_keyframe(prop_enum, time_offset, float(value))
        keyframes_added += 1
        if seg_id not in affected_segments:
            affected_segments.append(seg_id)
    script.save()
    return draft_id, keyframes_added, affected_segments


class CapcutAddKeyframesTool(BaseTool):
    name = "capcut_add_keyframes"
    description = "向剪映草稿中的视频/图片片段添加关键帧动画。支持位移、缩放、旋转、透明度、饱和度、对比度、亮度、音量等属性。"
    input_model = CapcutAddKeyframesInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            keyframes = [k.model_dump() for k in arguments.keyframes]
            draft_id, kf_added, affected = _add_keyframes_impl(arguments.draft_id, keyframes)
            return ToolResult(
                output=f"添加关键帧成功，draft_id: {draft_id}, keyframes_added: {kf_added}, "
                       f"affected_segments: {affected}",
                metadata={"draft_id": draft_id, "keyframes_added": kf_added, "affected_segments": affected},
            )
        except ValueError as e:
            return ToolResult(output=f"添加关键帧失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加关键帧失败：{e}", is_error=True)
