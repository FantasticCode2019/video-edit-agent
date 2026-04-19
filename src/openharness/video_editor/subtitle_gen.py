"""Self-contained ASS/SRT subtitle generation.

Generates ASS subtitle files with inline style override tags and plain SRT files.
No dependency on Jinja2, highlight_parser, or external config.
"""
from __future__ import annotations

import re
from io import StringIO
from numbers import Number


# ---------------------------------------------------------------------------
# Color conversion
# ---------------------------------------------------------------------------


def convert_color(color: str, tag: str) -> str:
    """Convert #RRGGBB or RRGGBB color to ASS BGR format with the given tag."""
    if not color or len(color) < 5:
        return ""
    if color.startswith("#"):
        r, g, b = color[1:3], color[3:5], color[5:7]
        return f"{tag}&H{b}{g}{r}&"
    elif len(color) == 6:
        r, g, b = color[0:2], color[2:4], color[4:6]
        return f"{tag}&H{b}{g}{r}&"
    return ""


# ---------------------------------------------------------------------------
# Style map — subtitle dict keys → ASS override tags
# ---------------------------------------------------------------------------

STYLE_FUNC_MAP = {
    "font": lambda x: f"\\fn{x}" if x else "",
    "font_size": lambda x: f"\\fs{x}" if x else "",
    "font_color": lambda x: convert_color(x, "\\c"),
    "bold": lambda x: "\\b1" if x else "\\b0",
    "italic": lambda x: "\\i1" if x else "\\i0",
    "stroke_width": lambda x: f"\\bord{x}" if x is not None else "",
    "stroke_color": lambda x: convert_color(x, "\\3c"),
    "shadow_color": lambda x: convert_color(x, "\\4c"),
    "alignment": lambda x: f"\\an{x}" if x else "",
    "pos": lambda x: f"\\pos({x})" if x else "",
    "rotate": lambda x: f"\\frz{-x}" if x else "",
    "bg_color": lambda x: convert_color(x, "\\3c"),
}


def build_style_str(style_dict: dict, keys: list[str]) -> str:
    """Build ASS style override string from a dict for the given keys."""
    parts = []
    for key in keys:
        if key in style_dict and key in STYLE_FUNC_MAP:
            value = style_dict.get(key)
            if value is not None:
                s = STYLE_FUNC_MAP[key](value)
                if s:
                    parts.append(s)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Time formatting
# ---------------------------------------------------------------------------


def build_time(t, srt_type: bool = False) -> str:
    """Convert seconds to ASS or SRT timestamp string."""
    if not isinstance(t, Number):
        return str(t)
    h = int(t // 3600)
    t = t % 3600
    m = int(t // 60)
    t = t % 60
    s = int(t)
    if srt_type:
        ms = int((t % 1) * 1000)
        return f"{h}:{m:02}:{s:02},{ms:03}"
    ms = int((t % 1) * 100)
    return f"{h}:{m:02}:{s:02}.{ms:02}"


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------


def convert_to_srt(data_list: list[dict]) -> str:
    """Convert a subtitle list to SRT format string."""
    if not data_list:
        return ""
    parts = []
    for i, item in enumerate(data_list, start=1):
        start = build_time(item["start"], srt_type=True)
        end = build_time(item["end"], srt_type=True)
        text = item["text"].replace("\n", " ")
        parts.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# ASS subtitle building
# ---------------------------------------------------------------------------


def _build_normal_subtitle(**kwargs) -> str:
    """Build a normal (non-highlighted) ASS subtitle line with inline styles."""
    text = kwargs.get("text", "").replace("\n", "\\N")
    has_bg = kwargs.get("bg_color")

    style_keys = ["font", "font_size", "bold", "italic", "pos", "font_color", "rotate", "alignment"]
    style_str = build_style_str(kwargs, style_keys)

    if has_bg:
        style_str += "\\bord1"
        style_str += build_style_str(kwargs, ["bg_color"])
    else:
        style_str += build_style_str(kwargs, ["stroke_width", "stroke_color"])
        if kwargs.get("shadow_color"):
            style_str += "\\xshad3\\yshad3\\blur2"
            style_str += build_style_str(kwargs, ["shadow_color"])

    return f"{{{style_str}}}{text}"


def _build_keyword_highlight_subtitle(**kwargs) -> str:
    """Build ASS subtitle with keyword-based highlighting via direct style specification.

    Parameters:
        text: Original subtitle text
        highlights: list of dicts, each with:
            - keywords: list of strings to highlight
            - style: dict with highlight style (font_color, bold, stroke_width, etc.)
        Other fields (font, font_color, etc.) are base styles for non-highlighted text.
    """
    text = kwargs.get("text", "").replace("\n", "\\N")
    highlights = kwargs.get("highlights", [])

    if not highlights:
        return _build_normal_subtitle(**kwargs)

    # Collect keywords with their styles, sorted by length (longer first)
    kw_style_pairs: list[tuple[str, dict]] = []
    for hl in highlights:
        style = hl.get("style", {})
        for kw in hl.get("keywords", []):
            if kw:
                kw_style_pairs.append((kw, style))
    kw_style_pairs.sort(key=lambda x: len(x[0]), reverse=True)

    if not kw_style_pairs:
        return _build_normal_subtitle(**kwargs)

    # Find all match intervals [start, end) with their styles
    matches: list[tuple[int, int, dict]] = []
    for kw, style in kw_style_pairs:
        for m in re.finditer(re.escape(kw), text, re.IGNORECASE):
            matches.append((m.start(), m.end(), style))

    if not matches:
        return _build_normal_subtitle(**kwargs)

    # Sort by position, remove overlaps
    matches.sort(key=lambda x: x[0])
    filtered: list[tuple[int, int, dict]] = []
    last_end = 0
    for start, end, style in matches:
        if start >= last_end:
            filtered.append((start, end, style))
            last_end = end

    # Build base style
    base_keys = ["font", "font_size", "bold", "italic", "pos", "font_color", "rotate", "alignment"]
    base_style_str = build_style_str(kwargs, base_keys)

    has_bg = kwargs.get("bg_color")
    if has_bg:
        base_style_str += "\\bord1"
        base_style_str += build_style_str(kwargs, ["bg_color"])
    else:
        base_style_str += build_style_str(kwargs, ["stroke_width", "stroke_color"])
        if kwargs.get("shadow_color"):
            base_style_str += "\\xshad3\\yshad3\\blur2"
            base_style_str += build_style_str(kwargs, ["shadow_color"])

    # Assemble text segments
    parts = [f"{{{base_style_str}}}"]
    last_pos = 0

    for start, end, hl_style in filtered:
        if start > last_pos:
            parts.append(text[last_pos:start])
        # Highlight segment with full style support
        hl_style_str = build_style_str(hl_style, ["font", "font_size", "bold", "italic", "font_color"])
        hl_style_str += build_style_str(hl_style, ["stroke_width", "stroke_color"])
        if hl_style.get("shadow_color"):
            hl_style_str += "\\xshad3\\yshad3\\blur2"
            hl_style_str += build_style_str(hl_style, ["shadow_color"])
        if hl_style.get("bg_color"):
            hl_style_str += "\\bord1"
            hl_style_str += build_style_str(hl_style, ["bg_color"])
        parts.append(f"{{{hl_style_str}}}{text[start:end]}")
        parts.append(f"{{{base_style_str}}}")
        last_pos = end

    if last_pos < len(text):
        parts.append(text[last_pos:])

    return "".join(parts)


# ---------------------------------------------------------------------------
# ASS file generation
# ---------------------------------------------------------------------------

_ASS_HEADER = """\
[Script Info]
Title:
ScriptType: v4.00+
WrapStyle: 1
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes
Last Style Storage: Default
Video File: ?dummy:23.976000:40000:640:480:47:163:254:
Video Aspect Ratio: 0
Video Zoom: 8
Video Position: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,微软雅黑,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,2,2,10,10,10,0
Style: OpaqueBG,微软雅黑,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,1,0,0,100,100,0,0,3,0,0,2,10,10,10,0

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def gen_ass(subtitle_list: list[dict], video_width: int = 0, video_height: int = 0) -> str:
    """Generate a complete ASS subtitle file from a subtitle list.

    Each subtitle dict may contain:
        - start, end, text (required)
        - style fields: font, font_size, font_color, bold, italic, stroke_width,
          stroke_color, shadow_color, bg_color, alignment, pos, rotate
        - highlights: list of {keywords: [...], style: {...}} for keyword highlighting
    """
    if not subtitle_list:
        return ""

    buf = StringIO()
    buf.write(_ASS_HEADER.format(video_width=video_width, video_height=video_height))

    for item in subtitle_list:
        start = build_time(item["start"])
        end = build_time(item["end"])

        if "MarginL" in item:
            item.pop("pos", None)

        has_bg = bool(item.get("bg_color")) or bool(item.get("normal_style", {}).get("bg_color"))
        style_name = "OpaqueBG" if has_bg else "Default"

        # Choose rendering path
        if item.get("highlights"):
            text = _build_keyword_highlight_subtitle(**item)
        else:
            text = _build_normal_subtitle(**item)

        margin_l = int(item.get("MarginL", 10))
        margin_v = int(item.get("MarginV", 10))
        subtitle_width = int(item.get("SubtitleWidth", 0))
        margin_r = video_width - subtitle_width - margin_l if video_width > 0 and subtitle_width > 0 else 0

        buf.write(f"Dialogue: 0,{start},{end},{style_name},,{margin_l},{margin_r},{margin_v},,{text}\n")

    return buf.getvalue()
