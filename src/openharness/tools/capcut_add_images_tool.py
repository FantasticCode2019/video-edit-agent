from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id, find_transition_type, map_video_animation_name
from openharness.capcut.pyJianYingDraft import ScriptFile, TrackType
from openharness.capcut.pyJianYingDraft.video_segment import VideoSegment
from openharness.capcut.pyJianYingDraft.segment import ClipSettings
from openharness.capcut.pyJianYingDraft.time_util import Timerange


class ImageInfo(BaseModel):
    """单个图片信息"""
    image_path: str = Field(description="图片文件本地路径")
    width: int = Field(description="图片宽度（像素）")
    height: int = Field(description="图片高度（像素）")
    start: int = Field(description="开始时间（微秒）")
    end: int = Field(description="结束时间（微秒）")
    in_animation: str | None = Field(default=None, description="入场动画名称（可选）")
    out_animation: str | None = Field(default=None, description="出场动画名称（可选）")
    loop_animation: str | None = Field(default=None, description="循环/组合动画名称（可选）")
    transition: str | None = Field(default=None, description="转场效果名称（可选）")
    transition_duration: int = Field(default=500000, description="转场持续时间（微秒）")


class CapcutAddImagesInput(BaseModel):
    """添加图片参数"""
    draft_id: str = Field(description="草稿 ID")
    image_infos: List[ImageInfo] = Field(description="图片信息列表")
    alpha: float = Field(default=1.0, ge=0, le=1, description="全局透明度")
    scale_x: float = Field(default=1.0, description="X 轴缩放")
    scale_y: float = Field(default=1.0, description="Y 轴缩放")
    transform_x: int = Field(default=0, description="X 轴位置偏移（像素）")
    transform_y: int = Field(default=0, description="Y 轴位置偏移（像素）")


def _parse_image_data(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("image_infos should be a list")
    result = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"the {i}th item should be a dict")
        required = ["image_path", "width", "height", "start", "end"]
        missing = [f for f in required if f not in item]
        if missing:
            raise ValueError(f"the {i}th item is missing required fields: {', '.join(missing)}")
        result.append({
            "image_path": item["image_path"],
            "width": int(item["width"]),
            "height": int(item["height"]),
            "start": int(item["start"]),
            "end": int(item["end"]),
            "in_animation": item.get("in_animation"),
            "out_animation": item.get("out_animation"),
            "loop_animation": item.get("loop_animation"),
            "in_animation_duration": item.get("in_animation_duration"),
            "out_animation_duration": item.get("out_animation_duration"),
            "loop_animation_duration": item.get("loop_animation_duration"),
            "transition": item.get("transition"),
            "transition_duration": item.get("transition_duration", 500000),
        })
    return result


def _add_image_to_draft(
    script: ScriptFile, track_name: str, image: Dict[str, Any],
    alpha: float, scale_x: float, scale_y: float,
    transform_x: int, transform_y: int,
) -> Tuple[str, Dict]:
    clip_settings = ClipSettings(
        alpha=alpha, scale_x=scale_x, scale_y=scale_y,
        transform_x=transform_x / script.width,
        transform_y=transform_y / script.height,
    )
    segment_duration = image["end"] - image["start"]
    video_segment = VideoSegment(
        material=image["image_path"],
        target_timerange=Timerange(start=image["start"], duration=segment_duration),
        clip_settings=clip_settings,
    )
    for anim_key, anim_kind in [("in_animation", "in"), ("out_animation", "out"), ("loop_animation", "group")]:
        if image.get(anim_key):
            anim_enum = map_video_animation_name(image[anim_key], anim_kind)
            if anim_enum:
                dur = image.get(anim_key.replace("animation", "animation_duration"))
                dur = int(dur) if dur is not None and dur != "" else None
                video_segment.add_animation(anim_enum, duration=dur)
    if image.get("transition"):
        tt = find_transition_type(image["transition"])
        if tt:
            video_segment.add_transition(tt, duration=image.get("transition_duration"))
    script.add_segment(video_segment, track_name)
    return video_segment.segment_id, {"id": video_segment.segment_id, "start": image["start"], "end": image["end"]}


def _add_images_impl(
    draft_id: str, image_infos: List[Dict[str, Any]],
    alpha: float, scale_x: float, scale_y: float,
    transform_x: int, transform_y: int,
) -> Tuple[str, str, List[str], List[str], List[Dict]]:
    if not image_infos:
        raise ValueError("image_infos cannot be empty")
    images = _parse_image_data(image_infos)
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"image_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.video, track_name=track_name, relative_index=10)
    segment_ids = []
    segment_infos = []
    for image in images:
        seg_id, seg_info = _add_image_to_draft(script, track_name, image, alpha, scale_x, scale_y, transform_x, transform_y)
        segment_ids.append(seg_id)
        segment_infos.append(seg_info)
    script.save()
    track_id = get_track_id(script, track_name)
    image_ids = [v.material_id for v in script.materials.videos if v.material_type == "photo"]
    return draft_id, track_id, image_ids, segment_ids, segment_infos


class CapcutAddImagesTool(BaseTool):
    name = "capcut_add_images"
    description = "向剪映草稿批量添加图片素材。支持设置透明度、缩放、位置偏移、入场/出场/组合动画和转场效果。返回 track_id、image_ids、segment_ids、segment_infos。"
    input_model = CapcutAddImagesInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            image_infos = [img.model_dump() for img in arguments.image_infos]
            draft_id, track_id, img_ids, seg_ids, seg_infos = _add_images_impl(
                arguments.draft_id, image_infos, arguments.alpha, arguments.scale_x,
                arguments.scale_y, arguments.transform_x, arguments.transform_y)
            return ToolResult(
                output=f"添加图片成功，draft_id: {draft_id}, track_id: {track_id}, "
                       f"image_ids: {img_ids}, segment_ids: {seg_ids}",
                metadata={"draft_id": draft_id, "track_id": track_id,
                          "image_ids": img_ids, "segment_ids": seg_ids, "segment_infos": seg_infos},
            )
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(output=f"添加图片失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加图片失败：{e}", is_error=True)
