from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import hex_to_rgb, gen_unique_id, get_track_id, map_text_animation_name
from openharness.capcut.pyJianYingDraft import ScriptFile, TrackType
from openharness.capcut.pyJianYingDraft.text_segment import TextSegment, TextStyle, TextBorder, TextShadow
from openharness.capcut.pyJianYingDraft.segment import ClipSettings
from openharness.capcut.pyJianYingDraft.time_util import Timerange
from openharness.capcut.pyJianYingDraft.metadata import FontType


class CaptionInfo(BaseModel):
    """单个字幕信息"""
    start: int = Field(description="开始时间（微秒）")
    end: int = Field(description="结束时间（微秒）")
    text: str = Field(description="文本内容")
    keyword: str | None = Field(default=None, description="关键词（| 分隔）")
    keyword_color: str = Field(default="#ff7100", description="关键词颜色")
    keyword_border_color: str | None = Field(default=None, description="关键词边框颜色")
    keyword_font_size: int = Field(default=15, description="关键词字体大小")
    font_size: int | None = Field(default=None, description="文本字体大小")
    in_animation: str | None = Field(default=None, description="入场动画")
    out_animation: str | None = Field(default=None, description="出场动画")
    loop_animation: str | None = Field(default=None, description="循环动画")


class CapcutAddCaptionsInput(BaseModel):
    """添加字幕参数"""
    draft_id: str = Field(description="草稿 ID")
    captions: List[CaptionInfo] = Field(description="字幕信息列表")
    text_color: str = Field(default="#ffffff", description="文本颜色")
    border_color: str | None = Field(default=None, description="边框颜色")
    alignment: int = Field(default=1, description="对齐方式 (0-2)")
    alpha: float = Field(default=1.0, description="透明度")
    font: str | None = Field(default=None, description="字体名称")
    font_size: int = Field(default=15, description="字体大小")
    scale_x: float = Field(default=1.0, description="水平缩放")
    scale_y: float = Field(default=1.0, description="垂直缩放")
    transform_x: float = Field(default=0.0, description="水平位移")
    transform_y: float = Field(default=0.0, description="垂直位移")
    bold: bool = Field(default=False, description="加粗")
    italic: bool = Field(default=False, description="斜体")
    underline: bool = Field(default=False, description="下划线")
    has_shadow: bool = Field(default=False, description="阴影")
    shadow_color: str = Field(default="#000000", description="阴影颜色")
    shadow_alpha: float = Field(default=0.9, description="阴影透明度")


def _parse_captions_data(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("captions should be a list")
    result = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"the {i}th item should be a dict")
        required = ["start", "end", "text"]
        missing = [f for f in required if f not in item]
        if missing:
            raise ValueError(f"the {i}th item is missing required fields: {', '.join(missing)}")
        if not isinstance(item["text"], str) or not item["text"].strip():
            raise ValueError(f"the {i}th item has invalid text")
        result.append({
            "start": item["start"], "end": item["end"], "text": item["text"],
            "keyword": item.get("keyword"),
            "keyword_color": item.get("keyword_color", "#ff7100"),
            "keyword_border_color": item.get("keyword_border_color"),
            "keyword_font_size": item.get("keyword_font_size", 15),
            "font_size": item.get("font_size"),
            "in_animation": item.get("in_animation"),
            "out_animation": item.get("out_animation"),
            "loop_animation": item.get("loop_animation"),
            "in_animation_duration": item.get("in_animation_duration"),
            "out_animation_duration": item.get("out_animation_duration"),
            "loop_animation_duration": item.get("loop_animation_duration"),
        })
    return result


def _apply_keyword_highlight(text_segment: TextSegment, keywords: str, keyword_color: tuple, keyword_font_size: float, keyword_border_color):
    keyword_list = keywords.split('|')
    text = text_segment.text
    for kw in keyword_list:
        kw = kw.strip()
        if not kw:
            continue
        start_pos = 0
        while start_pos < len(text):
            pos = text.find(kw, start_pos)
            if pos == -1:
                break
            end_pos = pos + len(kw)
            highlight = {
                "fill": {"alpha": 1.0, "content": {"solid": {"color": list(keyword_color)}}},
                "range": [pos, end_pos], "size": keyword_font_size,
                "bold": text_segment.style.bold,
                "italic": text_segment.style.italic,
                "underline": text_segment.style.underline,
            }
            if keyword_border_color is not None:
                highlight["strokes"] = [{"content": {"solid": {"alpha": 1.0, "color": list(keyword_border_color)}}, "width": 0.08}]
            text_segment.extra_styles.append(highlight)
            start_pos = end_pos


def _add_caption_to_draft(
    script: ScriptFile, track_name: str, caption: Dict, text_color: str, border_color,
    alignment: int, alpha: float, font, font_size: int,
    scale_x: float, scale_y: float, transform_x: float, transform_y: float,
    underline: bool, italic: bool, bold: bool, has_shadow: bool, shadow_info,
) -> Tuple[str, str, Dict]:
    duration = caption["end"] - caption["start"]
    timerange = Timerange(start=caption["start"], duration=duration)
    rgb_color = hex_to_rgb(text_color)
    align_val = 1
    if alignment == 0:
        align_val = 0
    elif alignment == 2:
        align_val = 2
    font_size_val = font_size
    if caption.get("font_size") is not None:
        font_size_val = float(caption["font_size"])
    text_style = TextStyle(
        size=font_size_val, color=rgb_color, alpha=alpha, align=align_val,
        letter_spacing=0, line_spacing=0, auto_wrapping=True,
        underline=underline, italic=italic, bold=bold,
    )
    text_border = TextBorder(color=hex_to_rgb(border_color)) if border_color else None
    font_type = getattr(FontType, font, None) if font else None
    clip_settings = ClipSettings(
        scale_x=scale_x, scale_y=scale_y,
        transform_x=transform_x / script.width,
        transform_y=transform_y / script.height,
    )
    text_shadow = None
    if has_shadow:
        if shadow_info:
            text_shadow = TextShadow(
                alpha=shadow_info.get("shadow_alpha", 0.9),
                color=hex_to_rgb(shadow_info.get("shadow_color", "#000000")),
                diffuse=shadow_info.get("shadow_diffuse", 15.0),
                distance=shadow_info.get("shadow_distance", 5.0),
                angle=shadow_info.get("shadow_angle", -45.0),
            )
        else:
            text_shadow = TextShadow(alpha=0.9, color=(0.0, 0.0, 0.0), diffuse=15.0, distance=5.0, angle=-45.0)
    text_segment = TextSegment(
        text=caption["text"], timerange=timerange, style=text_style,
        border=text_border, font=font_type, shadow=text_shadow, clip_settings=clip_settings,
    )
    if caption.get("keyword"):
        kw_color = hex_to_rgb(caption.get("keyword_color", "#ff7100"))
        kw_font_size = caption.get("keyword_font_size", 15)
        kw_border = hex_to_rgb(caption["keyword_border_color"]) if caption.get("keyword_border_color") else (hex_to_rgb(border_color) if border_color else None)
        _apply_keyword_highlight(text_segment, caption["keyword"], kw_color, kw_font_size, kw_border)
    for anim_kind, anim_key in [("in", "in_animation"), ("out", "out_animation"), ("loop", "loop_animation")]:
        if caption.get(anim_key):
            anim_enum = map_text_animation_name(caption[anim_key], anim_kind)
            if anim_enum:
                dur = caption.get(anim_key.replace("animation", "animation_duration"))
                text_segment.add_animation(anim_enum, duration=dur)
    script.add_segment(text_segment, track_name)
    seg_info = {"id": text_segment.segment_id, "start": caption["start"], "end": caption["end"]}
    return text_segment.segment_id, text_segment.material_id, seg_info


def _add_captions_impl(
    draft_id: str, captions: List[Dict[str, Any]], text_color: str, border_color,
    alignment: int, alpha: float, font, font_size: int,
    scale_x: float, scale_y: float, transform_x: float, transform_y: float,
    underline: bool, italic: bool, bold: bool, has_shadow: bool, shadow_info,
) -> Tuple[str, str, List[str], List[str], List[Dict]]:
    if not captions:
        raise ValueError("captions cannot be empty")
    items = _parse_captions_data(captions)
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"caption_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.text, track_name=track_name)
    seg_ids, txt_ids, seg_infos = [], [], []
    for caption in items:
        s_id, t_id, s_info = _add_caption_to_draft(
            script, track_name, caption, text_color, border_color, alignment, alpha, font, font_size,
            scale_x, scale_y, transform_x, transform_y, underline, italic, bold, has_shadow, shadow_info,
        )
        seg_ids.append(s_id)
        txt_ids.append(t_id)
        seg_infos.append(s_info)
    script.save()
    track_id = get_track_id(script, track_name)
    return draft_id, track_id, txt_ids, seg_ids, seg_infos


class CapcutAddCaptionsTool(BaseTool):
    name = "capcut_add_captions"
    description = "向剪映草稿批量添加字幕。支持关键词高亮、字体样式、动画效果和阴影。返回 track_id、text_ids、segment_ids 和 segment_infos。"
    input_model = CapcutAddCaptionsInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            captions = [c.model_dump() for c in arguments.captions]
            shadow_info = None
            if arguments.has_shadow:
                shadow_info = {
                    "shadow_color": arguments.shadow_color, "shadow_alpha": arguments.shadow_alpha,
                    "shadow_diffuse": 15.0, "shadow_distance": 5.0, "shadow_angle": -45.0,
                }
            draft_id, track_id, text_ids, seg_ids, seg_infos = _add_captions_impl(
                draft_id=arguments.draft_id, captions=captions,
                text_color=arguments.text_color, border_color=arguments.border_color,
                alignment=arguments.alignment, alpha=arguments.alpha, font=arguments.font,
                font_size=arguments.font_size, scale_x=arguments.scale_x, scale_y=arguments.scale_y,
                transform_x=arguments.transform_x, transform_y=arguments.transform_y,
                underline=arguments.underline, italic=arguments.italic, bold=arguments.bold,
                has_shadow=arguments.has_shadow, shadow_info=shadow_info,
            )
            return ToolResult(
                output=f"添加字幕成功，draft_id: {draft_id}, track_id: {track_id}, "
                       f"text_ids: {text_ids}, segment_ids: {seg_ids}",
                metadata={"draft_id": draft_id, "track_id": track_id,
                          "text_ids": text_ids, "segment_ids": seg_ids, "segment_infos": seg_infos},
            )
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(output=f"添加字幕失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加字幕失败：{e}", is_error=True)
