import json
from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import hex_to_rgb


class CapcutAddTextStyleInput(BaseModel):
    """生成文本样式参数"""
    text: str = Field(description="文本内容")
    keyword: str = Field(description="关键词（| 分隔多个）")
    font_size: int = Field(default=12, description="普通文本字体大小")
    keyword_color: str = Field(default="#ff7100", description="关键词颜色")
    keyword_font_size: int = Field(default=15, description="关键词字体大小")


def _make_style(start: int, end: int, font_size: int, color, use_letter_color: bool = False) -> dict:
    style = {
        "fill": {"content": {"solid": {"color": color}}},
        "range": [start, end],
        "size": font_size,
        "font": {"id": "", "path": ""},
    }
    if use_letter_color:
        style["useLetterColor"] = True
    return style


def _add_text_style_impl(
    text: str, keyword: str, font_size: int, keyword_color: str, keyword_font_size: int,
) -> str:
    keywords = [kw.strip() for kw in keyword.split('|') if kw.strip()]
    keywords.sort(key=len, reverse=True)
    if not keywords:
        return json.dumps({
            "text": text,
            "styles": [_make_style(0, len(text), font_size, [1.0, 1.0, 1.0])],
        }, ensure_ascii=False, separators=(',', ':'))
    color_hex = keyword_color.lstrip('#')
    kw_rgb = [int(color_hex[i:i+2], 16) / 255.0 for i in (0, 2, 4)] if len(color_hex) == 6 else [1.0, 0.44, 0.0]
    normal_rgb = [1.0, 1.0, 1.0]
    positions = []
    used = set()
    for kw in keywords:
        for match in __import__('re').finditer(__import__('re').escape(kw), text):
            span = set(range(match.start(), match.end()))
            if not span & used:
                positions.append((match.start(), match.end(), kw))
                used |= span
    positions.sort()
    styles = []
    cur = 0
    for start, end, _ in positions:
        if cur < start:
            styles.append(_make_style(cur, start, font_size, normal_rgb))
        styles.append(_make_style(start, end, keyword_font_size, kw_rgb, use_letter_color=True))
        cur = end
    if cur < len(text):
        styles.append(_make_style(cur, len(text), font_size, normal_rgb))
    return json.dumps({"text": text, "styles": styles}, ensure_ascii=False, separators=(',', ':'))


class CapcutAddTextStyleTool(BaseTool):
    name = "capcut_add_text_style"
    description = "为文本生成富文本样式 JSON，支持关键词高亮。返回 text_style JSON 字符串，可直接用于字幕或文字模板。"
    input_model = CapcutAddTextStyleInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        text_style = _add_text_style_impl(
            text=arguments.text, keyword=arguments.keyword, font_size=arguments.font_size,
            keyword_color=arguments.keyword_color, keyword_font_size=arguments.keyword_font_size,
        )
        return ToolResult(output=f"文本样式生成成功：{text_style}", metadata={"text_style": text_style})
