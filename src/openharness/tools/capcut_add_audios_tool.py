from pydantic import BaseModel, Field
from typing import List, Dict, Any, Tuple

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.capcut.utils import gen_unique_id, get_track_id
from openharness.capcut.pyJianYingDraft import ScriptFile, TrackType
from openharness.capcut.pyJianYingDraft.audio_segment import AudioSegment
from openharness.capcut.pyJianYingDraft.local_materials import AudioMaterial
from openharness.capcut.pyJianYingDraft.time_util import Timerange
from openharness.capcut.pyJianYingDraft.metadata import (
    AudioSceneEffectType, VideoSceneEffectType, VideoCharacterEffectType,
)


class AudioInfo(BaseModel):
    """单个音频信息"""
    audio_path: str = Field(description="音频文件本地路径")
    start: int = Field(description="开始时间（微秒）")
    end: int = Field(description="结束时间（微秒）")
    duration: int | None = Field(default=None, description="音频总时长（微秒，可选）")
    volume: float = Field(default=1.0, description="音量 [0, 2]")
    audio_effect: str | None = Field(default=None, description="音频效果名称（可选）")


class CapcutAddAudiosInput(BaseModel):
    """添加音频参数"""
    draft_id: str = Field(description="草稿 ID")
    audio_infos: List[AudioInfo] = Field(description="音频信息列表")


def _parse_audio_data(data: Any) -> List[Dict[str, Any]]:
    if not isinstance(data, list):
        raise ValueError("audio_infos should be a list")
    result = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"the {i}th item should be a dict")
        required = ["audio_path", "start", "end"]
        missing = [f for f in required if f not in item]
        if missing:
            raise ValueError(f"the {i}th item is missing required fields: {', '.join(missing)}")
        volume = item.get("volume", 1.0)
        if volume < 0.0 or volume > 2.0:
            volume = 1.0
        result.append({
            "audio_path": item["audio_path"],
            "start": item["start"],
            "end": item["end"],
            "duration": item.get("duration"),
            "volume": volume,
            "audio_effect": item.get("audio_effect"),
        })
    return result


def _add_audio_effect(audio_segment: AudioSegment, effect_name: str):
    effect_type = None
    for et in AudioSceneEffectType:
        if et.value.name == effect_name:
            effect_type = et
            break
    if effect_type is None:
        for et in VideoSceneEffectType:
            if et.value.name == effect_name:
                effect_type = et
                break
    if effect_type is None:
        for et in VideoCharacterEffectType:
            if et.value.name == effect_name:
                effect_type = et
                break
    if effect_type:
        params = []
        for param in effect_type.value.params:
            if param.min_value != param.max_value:
                val = ((param.default_value - param.min_value) / (param.max_value - param.min_value)) * 100
            else:
                val = 50
            params.append(val)
        audio_segment.add_effect(effect_type, params=params)


def _add_audio_to_draft(script: ScriptFile, track_name: str, audio: Dict[str, Any]) -> str:
    temp_material = AudioMaterial(audio["audio_path"])
    actual_duration = temp_material.duration
    if audio.get("duration") is None:
        audio["duration"] = actual_duration
    start_time = audio["start"]
    requested_duration = audio["end"] - start_time
    segment_duration = min(requested_duration, actual_duration) if actual_duration >= requested_duration else actual_duration
    if segment_duration <= 0:
        segment_duration = 100
    audio_segment = AudioSegment(
        material=audio["audio_path"],
        target_timerange=Timerange(start=start_time, duration=segment_duration),
        volume=audio["volume"],
    )
    if audio.get("audio_effect"):
        _add_audio_effect(audio_segment, audio["audio_effect"])
    try:
        script.add_segment(audio_segment, track_name)
    except Exception as e:
        if "overlap" in str(e).lower():
            for offset in range(100, 1100, 100):
                try:
                    adjusted = AudioSegment(
                        material=audio["audio_path"],
                        target_timerange=Timerange(start=start_time + offset, duration=segment_duration),
                        volume=audio["volume"],
                    )
                    script.add_segment(adjusted, track_name)
                    break
                except Exception:
                    continue
            else:
                raise
        else:
            raise
    return audio_segment.material_instance.material_id


def _add_audios_impl(draft_id: str, audio_infos: List[Dict[str, Any]]) -> Tuple[str, str, List[str]]:
    if not audio_infos:
        raise ValueError("audio_infos cannot be empty")
    audios = _parse_audio_data(audio_infos)
    from openharness.capcut import draft_manager
    script = draft_manager.get_draft(draft_id)
    track_name = f"audio_track_{gen_unique_id()}"
    script.add_track(track_type=TrackType.audio, track_name=track_name, relative_index=10)
    audio_ids = []
    for audio in audios:
        audio_id = _add_audio_to_draft(script, track_name, audio)
        audio_ids.append(audio_id)
    script.save()
    track_id = get_track_id(script, track_name)
    return draft_id, track_id, audio_ids


class CapcutAddAudiosTool(BaseTool):
    name = "capcut_add_audios"
    description = "向剪映草稿批量添加音频素材。支持设置音量和音频效果。返回 track_id 和 audio_ids。"
    input_model = CapcutAddAudiosInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            audio_infos = [a.model_dump() for a in arguments.audio_infos]
            draft_id, track_id, audio_ids = _add_audios_impl(arguments.draft_id, audio_infos)
            return ToolResult(
                output=f"添加音频成功，draft_id: {draft_id}, track_id: {track_id}, audio_ids: {audio_ids}",
                metadata={"draft_id": draft_id, "track_id": track_id, "audio_ids": audio_ids},
            )
        except (ValueError, FileNotFoundError) as e:
            return ToolResult(output=f"添加音频失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"添加音频失败：{e}", is_error=True)
