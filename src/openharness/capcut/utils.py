"""Capcut shared utility functions."""

import uuid
from typing import Optional, Tuple

from openharness.capcut.pyJianYingDraft import ScriptFile
from openharness.capcut.pyJianYingDraft.segment import VisualSegment
from openharness.capcut.pyJianYingDraft.metadata import (
    TransitionType, IntroType, OutroType, GroupAnimationType,
    TextIntro, TextOutro, TextLoopAnim,
)


def gen_unique_id() -> str:
    return uuid.uuid4().hex[:8]


def get_track_id(script: ScriptFile, track_name: str) -> str:
    for key in script.tracks.keys():
        if script.tracks[key].name == track_name:
            return script.tracks[key].track_id
    return ""


def find_transition_type(name: str) -> Optional[TransitionType]:
    if not name:
        return None
    try:
        return TransitionType.from_name(name)
    except ValueError:
        return None


def find_segment(script: ScriptFile, segment_id: str):
    """在所有轨道中查找片段"""
    for track in script.tracks.values():
        for seg in track.segments:
            if seg.segment_id == segment_id:
                return seg
    return None


def hex_to_rgb(hex_color: str) -> Tuple[float, float, float]:
    """十六进制颜色转 RGB (0-1 范围)"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return (1.0, 1.0, 1.0)
    try:
        r = int(hex_color[0:2], 16) / 255.0
        g = int(hex_color[2:4], 16) / 255.0
        b = int(hex_color[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (1.0, 1.0, 1.0)


def map_video_animation_name(name: str, kind: str):
    """视频/图片动画名称映射 (kind: "in" | "out" | "group")"""
    if kind == "in":
        for attr in dir(IntroType):
            val = getattr(IntroType, attr)
            if isinstance(val, IntroType) and val.value.title == name:
                return val
    elif kind == "out":
        for attr in dir(OutroType):
            val = getattr(OutroType, attr)
            if isinstance(val, OutroType) and val.value.title == name:
                return val
    elif kind == "group":
        for attr in dir(GroupAnimationType):
            val = getattr(GroupAnimationType, attr)
            if isinstance(val, GroupAnimationType) and val.value.title == name:
                return val
    return None


def map_text_animation_name(name: str, kind: str):
    """文本动画名称映射 (kind: "in" | "out" | "loop")"""
    if kind == "in":
        for attr in dir(TextIntro):
            val = getattr(TextIntro, attr)
            if isinstance(val, TextIntro) and val.value.title == name:
                return val
    elif kind == "out":
        for attr in dir(TextOutro):
            val = getattr(TextOutro, attr)
            if isinstance(val, TextOutro) and val.value.title == name:
                return val
    elif kind == "loop":
        for attr in dir(TextLoopAnim):
            val = getattr(TextLoopAnim, attr)
            if isinstance(val, TextLoopAnim) and val.value.title == name:
                return val
    return None
