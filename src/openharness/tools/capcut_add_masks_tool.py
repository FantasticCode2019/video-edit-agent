from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple, Optional

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id, find_segment, hex_to_rgb
from openharness.capcut.pyJianYingDraft import ScriptFile, MaskType
from openharness.capcut.pyJianYingDraft.video_segment import VideoSegment


class CapcutAddMasksInput(BaseModel):
    """添加遮罩参数"""
    draft_id: str = Field(description="草稿 ID")
    segment_ids: List[str] = Field(description="目标片段 ID 列表")
    name: str = Field(default="线性", description="遮罩类型（线性、镜面、圆形、矩形、爱心、星形）")
    X: int = Field(default=0, description="遮罩中心 X 坐标（像素）")
    Y: int = Field(default=0, description="遮罩中心 Y 坐标（像素）")
    width: int = Field(default=512, description="遮罩宽度（像素）")
    height: int = Field(default=512, description="遮罩高度（像素）")
    feather: int = Field(default=0, description="羽化程度（0-100）")
    rotation: int = Field(default=0, description="旋转角度（度）")
    invert: bool = Field(default=False, description="是否反转遮罩")
    round_corner: int = Field(default=0, description="圆角半径（0-100），仅矩形遮罩有效")


def _find_mask_type_by_name(mask_name: str) -> Optional[MaskType]:
    for mask_type in MaskType:
        if mask_type.value.name == mask_name:
            return mask_type
    return None


def _calculate_mask_size_params(mask_type: MaskType, width: int, height: int, material_width: int, material_height: int) -> Tuple[float, Optional[float]]:
    size = height / material_height
    if mask_type == MaskType.矩形:
        rect_width = width / material_width
        return size, rect_width
    return size, None


def _add_mask_to_segment(
    script: ScriptFile, segment_id: str, mask_type: MaskType,
    center_x: int, center_y: int, width: int, height: int,
    feather: int, rotation: int, invert: bool, round_corner: int,
) -> str:
    segment = find_segment(script, segment_id)
    if segment is None:
        raise ValueError(f"Segment not found: {segment_id}")
    if not isinstance(segment, VideoSegment):
        raise ValueError(f"Segment {segment_id} is not a video segment, cannot add mask")
    if segment.mask is not None:
        return segment.mask.global_id
    material_width, material_height = segment.material_size
    size, rect_width = _calculate_mask_size_params(mask_type, width, height, material_width, material_height)
    if mask_type == MaskType.矩形:
        segment.add_mask(mask_type=mask_type, center_x=float(center_x), center_y=float(center_y),
                        size=size, rotation=float(rotation), feather=float(feather), invert=invert,
                        rect_width=rect_width, round_corner=float(round_corner))
    else:
        segment.add_mask(mask_type=mask_type, center_x=float(center_x), center_y=float(center_y),
                        size=size, rotation=float(rotation), feather=float(feather), invert=invert)
    if segment.mask is not None:
        mask_exists = any(m.get("id") == segment.mask.global_id for m in script.materials.masks)
        if not mask_exists:
            script.materials.masks.append(segment.mask.export_json())
    return segment.mask.global_id


def _add_masks_impl(
    draft_id: str, segment_ids: List[str],
    name: str, X: int, Y: int, width: int, height: int,
    feather: int, rotation: int, invert: bool, round_corner: int,
) -> Tuple[str, int, List[str], List[str]]:
    if not segment_ids:
        raise ValueError("segment_ids cannot be empty")
    mask_type = _find_mask_type_by_name(name)
    if mask_type is None:
        raise ValueError(f"Mask type not found: {name}")
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    masks_added = 0
    affected_segments, mask_ids = [], []
    for seg_id in segment_ids:
        mask_id = _add_mask_to_segment(
            script, seg_id, mask_type, X, Y, width, height, feather, rotation, invert, round_corner,
        )
        masks_added += 1
        affected_segments.append(seg_id)
        mask_ids.append(mask_id)
    script.save()
    return draft_id, masks_added, affected_segments, mask_ids


class CapcutAddMasksTool(BaseTool):
    name = "capcut_add_masks"
    description = "向剪映草稿中的视频/图片片段添加遮罩效果。支持线性、镜面、圆形、矩形、爱心、星形等遮罩类型。"
    input_model = CapcutAddMasksInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            draft_id, masks_added, affected, mask_ids = _add_masks_impl(
                draft_id=arguments.draft_id, segment_ids=arguments.segment_ids,
                name=arguments.name, X=arguments.X, Y=arguments.Y,
                width=arguments.width, height=arguments.height,
                feather=arguments.feather, rotation=arguments.rotation,
                invert=arguments.invert, round_corner=arguments.round_corner,
            )
            return ToolResult(
                output=f"添加遮罩成功，draft_id: {draft_id}, masks_added: {masks_added}, "
                       f"affected_segments: {affected}, mask_ids: {mask_ids}",
                metadata={"draft_id": draft_id, "masks_added": masks_added,
                          "affected_segments": affected, "mask_ids": mask_ids},
            )
        except ValueError as e:
            return ToolResult(output=f"添加遮罩失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加遮罩失败：{e}", is_error=True)
