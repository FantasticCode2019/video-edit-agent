import os
from pathlib import Path

# OpenHarness 用户数据目录
OPENHARNESS_DIR = Path.home() / ".openharness"

# 草稿存储目录（默认 ~/.openharness/drafts/capcut/，可环境变量覆盖）
CAPCUT_DRAFT_DIR = os.getenv("CAPCUT_DRAFT_DIR", str(OPENHARNESS_DIR / "drafts" / "capcut"))

# 模板目录（模块内自包含）
CAPCUT_TEMPLATE_DIR = Path(__file__).parent / "template"
