from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class CapcutCreateDraftInput(BaseModel):
    """创建剪映草稿参数"""
    width: int = Field(default=1920, ge=1, description="视频宽度（像素）")
    height: int = Field(default=1080, ge=1, description="视频高度（像素）")


class CapcutCreateDraftTool(BaseTool):
    name = "capcut_create_draft"
    description = "创建一个新的剪映视频编辑草稿，设置画布尺寸。返回 draft_id 用于后续操作（如 add_videos, add_captions 等）。"
    input_model = CapcutCreateDraftInput

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        from openharness.capcut.draft_manager import create_draft as _create_draft

        try:
            draft_id = _create_draft(
                width=arguments.width,
                height=arguments.height,
            )
            return ToolResult(
                output=f"草稿创建成功，draft_id: {draft_id}",
                metadata={"draft_id": draft_id},
            )
        except FileNotFoundError as e:
            return ToolResult(output=f"草稿创建失败：模板文件不存在 - {e}", is_error=True)
        except ValueError as e:
            return ToolResult(output=f"参数错误：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"草稿创建失败：{e}", is_error=True)
