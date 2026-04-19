from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult


class CapcutSaveDraftInput(BaseModel):
    """保存剪映草稿参数"""
    draft_id: str = Field(description="草稿唯一标识")


class CapcutSaveDraftTool(BaseTool):
    name = "capcut_save_draft"
    description = "保存剪映草稿到磁盘。在调用 add_videos、add_captions 等修改操作后使用，确保编辑内容持久化。"
    input_model = CapcutSaveDraftInput

    async def execute(
        self, arguments: BaseModel, context: ToolExecutionContext
    ) -> ToolResult:
        from openharness.capcut.draft_manager import save_draft

        try:
            save_draft(arguments.draft_id)
            return ToolResult(
                output=f"草稿保存成功，draft_id: {arguments.draft_id}",
            )
        except ValueError as e:
            return ToolResult(output=f"保存失败：{e}", is_error=True)
        except Exception as e:
            return ToolResult(output=f"草稿保存失败：{e}", is_error=True)
