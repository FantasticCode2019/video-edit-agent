from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple, Optional, Union

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id
from openharness.capcut.pyJianYingDraft import ScriptFile, TrackType
from openharness.capcut.pyJianYingDraft.effect_segment import EffectSegment
from openharness.capcut.pyJianYingDraft.time_util import Timerange
from openharness.capcut.pyJianYingDraft.metadata import VideoSceneEffectType, VideoCharacterEffectType


class EffectInfo(BaseModel):
    """单个特效信息"""
    effect_title: str = Field(description="特效名称")
    start: int = Field(description="开始时间（微秒）")
    end: int = Field(description="结束时间（微秒）")


class CapcutAddEffectsInput(BaseModel):
    """添加特效参数"""
    draft_id: str = Field(description="草稿 ID")
    effect_infos: List[EffectInfo] = Field(description="特效信息列表")


def _find_effect_type(name: str) -> Optional[Union[VideoSceneEffectType, VideoCharacterEffectType]]:
    for et in VideoSceneEffectType:
        if et.value.name == name:
            return et
    for et in VideoCharacterEffectType:
        if et.value.name == name:
            return et
    return None


def _add_effects_impl(
    draft_id: str, effect_infos: List[Dict[str, Any]],
) -> Tuple[str, str, List[str], List[str]]:
    if not effect_infos:
        raise ValueError("effect_infos cannot be empty")
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"effect_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.effect, track_name=track_name)
    effect_ids, segment_ids = [], []
    for eff in effect_infos:
        title = eff.get("effect_title")
        if not title:
            raise ValueError("effect_title is required")
        effect_type = _find_effect_type(title)
        if effect_type is None:
            raise ValueError(f"Effect not found: {title}")
        duration = eff["end"] - eff["start"]
        segment = EffectSegment(
            effect_type=effect_type,
            target_timerange=Timerange(start=eff["start"], duration=duration),
        )
        script.add_segment(segment, track_name)
        effect_ids.append(segment.effect_inst.global_id)
        segment_ids.append(segment.segment_id)
    script.save()
    track_id = get_track_id(script, track_name)
    return draft_id, track_id, effect_ids, segment_ids


class CapcutAddEffectsTool(BaseTool):
    name = "capcut_add_effects"
    description = "向剪映草稿添加特效（场景特效/人物特效）。返回 track_id、effect_ids 和 segment_ids。"
    input_model = CapcutAddEffectsInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            effect_data = [e.model_dump() for e in arguments.effect_infos]
            draft_id, track_id, effect_ids, seg_ids = _add_effects_impl(arguments.draft_id, effect_data)
            return ToolResult(
                output=f"添加特效成功，draft_id: {draft_id}, track_id: {track_id}, "
                       f"effect_ids: {effect_ids}, segment_ids: {seg_ids}",
                metadata={"draft_id": draft_id, "track_id": track_id,
                          "effect_ids": effect_ids, "segment_ids": seg_ids},
            )
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(output=f"添加特效失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加特效失败：{e}", is_error=True)
