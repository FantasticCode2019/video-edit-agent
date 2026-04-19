import os
import shutil
import datetime
import uuid
from collections import OrderedDict
from typing import Dict, Optional
from pathlib import Path

from .pyJianYingDraft import ScriptFile, TrackType

# LRU 缓存，最大 100 条
DRAFT_CACHE: Dict[str, ScriptFile] = OrderedDict()
MAX_CACHE_SIZE = 100


def _update_cache(draft_id: str, script: ScriptFile) -> None:
    """更新 LRU 缓存"""
    if draft_id in DRAFT_CACHE:
        DRAFT_CACHE.pop(draft_id)
    elif len(DRAFT_CACHE) >= MAX_CACHE_SIZE:
        DRAFT_CACHE.popitem(last=False)
    DRAFT_CACHE[draft_id] = script


def create_draft(width: int, height: int) -> str:
    """创建剪映草稿

    Args:
        width: 画布宽度（像素）
        height: 画布高度（像素）

    Returns:
        draft_id: 草稿唯一标识

    Raises:
        ValueError: 画布尺寸无效
        FileNotFoundError: 模板文件不存在
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid canvas size: {width}x{height}")

    # 生成 draft_id
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    draft_id = f"{timestamp}{unique_id}"

    from . import config

    # 从模板复制到草稿目录
    template_path = config.CAPCUT_TEMPLATE_DIR / "default2"
    draft_path = Path(config.CAPCUT_DRAFT_DIR) / draft_id
    if draft_path.exists():
        shutil.rmtree(draft_path)
    shutil.copytree(template_path, draft_path)

    # 加载并修改 draft_info.json
    draft_info_path = draft_path / "draft_info.json"
    script = ScriptFile.load_template(str(draft_info_path))
    script.dual_file_compatibility = True
    script.width, script.height = width, height
    script.content["canvas_config"]["width"] = width
    script.content["canvas_config"]["height"] = height

    # 设置保存路径（保存到 draft_content.json）
    draft_content_path = draft_path / "draft_content.json"
    script.save_path = str(draft_content_path)
    script.save()

    # 添加空主轨道
    script.add_track(
        track_type=TrackType.video,
        track_name="main_track",
        relative_index=0
    )
    script.save()

    # 缓存
    _update_cache(draft_id, script)

    return draft_id


def get_draft(draft_id: str) -> ScriptFile:
    """获取草稿 ScriptFile（缓存优先）

    Args:
        draft_id: 草稿唯一标识

    Returns:
        ScriptFile 对象

    Raises:
        FileNotFoundError: 草稿不存在
    """
    if draft_id in DRAFT_CACHE:
        # 移到末尾（最近使用）
        DRAFT_CACHE.move_to_end(draft_id)
        return DRAFT_CACHE[draft_id]

    from . import config

    draft_path = Path(config.CAPCUT_DRAFT_DIR) / draft_id
    draft_info_path = draft_path / "draft_info.json"
    if not draft_info_path.exists():
        raise FileNotFoundError(f"Draft not found: {draft_id}")

    script = ScriptFile.load_template(str(draft_info_path))
    script.save_path = str(draft_path / "draft_content.json")
    _update_cache(draft_id, script)
    return script


def save_draft(draft_id: str) -> None:
    """保存草稿到磁盘

    Args:
        draft_id: 草稿唯一标识

    Raises:
        ValueError: 草稿不在缓存中
    """
    if draft_id not in DRAFT_CACHE:
        raise ValueError(f"Draft not in cache: {draft_id}")
    DRAFT_CACHE[draft_id].save()


def get_draft_path(draft_id: str) -> Path:
    """返回草稿目录路径"""
    from . import config
    return Path(config.CAPCUT_DRAFT_DIR) / draft_id
