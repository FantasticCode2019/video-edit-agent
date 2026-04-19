import json
from pydantic import BaseModel, Field
from typing import Optional

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class VideoEditInput(BaseModel):
    """视频编辑请求"""
    request_json: str = Field(description="VideoEditRequest JSON 字符串")
    output_dir: Optional[str] = Field(default=None, description="输出目录（可选，默认为输入文件同目录）")


def _video_edit_impl(request_json: str, output_dir: Optional[str] = None) -> dict:
    from openharness.video_editor.schema import VideoEditRequest
    from openharness.video_editor.executor import execute

    data = json.loads(request_json)
    req = VideoEditRequest(**data)
    result = execute(req, output_dir=output_dir)
    return result


class VideoEditTool(BaseTool):
    name = "video_edit"
    description = (
        "执行视频编辑操作。接收 VideoEditRequest JSON，经过验证后调用 FFmpeg 管线处理。"
        "支持：视频拼接/截取、音频混合（配音/背景音乐）、字幕烧录（ASS/SRT/Whisper）、"
        "图片/视频叠加、转场特效、色彩调节、变速/倒放。"
        "先用 video_probe 探测素材参数，再构造 JSON 调用本工具。"
    )
    input_model = VideoEditInput

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            result = _video_edit_impl(arguments.request_json, arguments.output_dir)
            output_path = result.get("output_path", "unknown")
            return ToolResult(
                output=f"视频编辑完成，输出文件：{output_path}",
                metadata=result,
            )
        except json.JSONDecodeError as e:
            return ToolResult(output=f"JSON 解析失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"视频编辑失败：{e}", is_error=True)
