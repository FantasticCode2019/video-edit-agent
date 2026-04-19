"""Whisper ASR integration for automatic subtitle generation.

Transcribes audio from a video/audio file using a local Whisper model,
then converts the result to both ASS (with optional styling) and SRT formats.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)


def generate_subtitles(
    audio_source: str,
    language: str = "zh",
    model_name: str = "base",
    output_dir: Optional[str] = None,
    style: Optional[dict] = None,
    highlight_keywords: Optional[list[str]] = None,
    highlight_style: Optional[dict] = None,
    video_width: int = 0,
    video_height: int = 0,
) -> str:
    """Transcribe audio and generate an ASS subtitle file with optional styling.

    Args:
        audio_source: Path to audio or video file.
        language: Language code for Whisper (e.g. "zh", "en").
        model_name: Whisper model size ("tiny", "base", "small", "medium", "large").
        output_dir: Directory for the output .ass file. Uses a temp dir if None.
        style: Optional dict of subtitle style fields (font, font_size, font_color,
            bold, italic, stroke_width, stroke_color, shadow_color, bg_color,
            alignment, pos_x, pos_y, rotate).
        highlight_keywords: Optional list of keywords to highlight.
        highlight_style: Optional dict of highlight style (font_color, bold, stroke_width,
            stroke_color, shadow_color, bg_color, etc.).
        video_width: Video width for ASS margin calculations.
        video_height: Video height for ASS margin calculations.

    Returns:
        Absolute path to the generated .ass subtitle file.
        Also writes a companion .srt file to the same directory.
    """
    import whisper

    logger.info(f"Loading Whisper model: {model_name}")
    model = whisper.load_model(model_name)

    logger.info(f"Transcribing: {audio_source} (language={language})")
    result = model.transcribe(audio_source, language=language)

    # 保存原始 segments（用于 SRT 导出，不含样式标记）
    raw_segments: list[dict] = []
    subtitle_list = []
    for seg in result.get("segments", []):
        text = seg["text"].strip()
        entry: dict = {
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
        }

        # 保存原始文本用于 SRT
        raw_segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": text,
        })

        # 注入样式
        if style:
            for key in (
                "font", "font_size", "font_color", "bold", "italic",
                "stroke_width", "stroke_color", "shadow_color", "bg_color",
                "rotate",
            ):
                if key in style and style[key] is not None:
                    entry[key] = style[key]
            # alignment 作为数字直接用
            if style.get("alignment") is not None:
                entry["alignment"] = style["alignment"]
            # pos_x/pos_y → pos 字符串
            if style.get("pos_x") is not None and style.get("pos_y") is not None:
                entry["pos"] = f"{style['pos_x']},{style['pos_y']}"

        # 高亮关键词处理：直接通过 highlights 字段指定，不修改文本
        if highlight_keywords and text:
            # 检查文本中是否实际包含关键词
            import re
            has_match = any(re.search(re.escape(kw), text, re.IGNORECASE) for kw in highlight_keywords if kw)
            if has_match:
                # 合并默认值：高亮默认红色加粗
                hl_final_style = {"font_color": "FF0000", "bold": True}
                if highlight_style:
                    hl_final_style.update({k: v for k, v in highlight_style.items() if v is not None})
                entry["highlights"] = [{
                    "keywords": highlight_keywords,
                    "style": hl_final_style,
                }]

        subtitle_list.append(entry)

    if not subtitle_list:
        logger.warning("Whisper 未识别到任何语音片段")
        subtitle_list = [{"start": 0, "end": 1, "text": ""}]

    from .subtitle_gen import gen_ass

    ass_content = gen_ass(subtitle_list, video_width=video_width, video_height=video_height)

    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="video_editor_sub_")
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "whisper_subtitles.ass")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_content)

    # 同时导出 SRT 文件（纯文本，不含样式标记）
    from .subtitle_gen import convert_to_srt

    srt_content = convert_to_srt(raw_segments)
    srt_path = os.path.join(output_dir, "whisper_subtitles.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    logger.info(f"字幕文件已生成: {output_path}, {srt_path} ({len(subtitle_list)} 条)")
    return output_path
