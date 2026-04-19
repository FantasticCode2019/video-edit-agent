from pydantic import BaseModel, Field
from typing import Optional

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class VideoProbeInput(BaseModel):
    """探测视频/音频文件元信息"""
    file_path: str = Field(description="文件本地路径")


class VideoProbeTool(BaseTool):
    name = "video_probe"
    description = "探测视频或音频文件的元信息，包括时长、分辨率、帧率、编码格式、是否有音轨、是否有视频流。用于在编辑前了解素材参数。"
    input_model = VideoProbeInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        from openharness.video_editor.ffmpeg_core import (
            get_video_duration, get_video_fps, get_video_codec,
            has_audio_stream, get_stream_info,
        )

        try:
            path = arguments.file_path

            duration = get_video_duration(path)
            has_audio = has_audio_stream(path)
            has_video = True
            fps = None
            codec = None
            width = None
            height = None

            try:
                info = get_stream_info(path)
                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "video":
                        fps_str = stream.get("r_frame_rate", "0/1")
                        num, den = fps_str.split("/")
                        fps = float(num) / float(den) if float(den) != 0 else None
                        codec = stream.get("codec_name")
                        width = stream.get("width")
                        height = stream.get("height")
                        break
            except Exception:
                pass

            result = {
                "path": path,
                "duration_seconds": round(duration, 2),
                "has_video": has_video,
                "has_audio": has_audio,
                "fps": round(fps, 2) if fps else None,
                "codec": codec,
                "width": width,
                "height": height,
            }

            return ToolResult(
                output=f"文件探测成功：{result}",
                metadata=result,
            )
        except FileNotFoundError:
            return ToolResult(output=f"文件未找到：{arguments.file_path}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"探测失败：{e}", is_error=True)
