# OpenHarness 内置视频编辑 Agent

> 本文档介绍 OpenHarness 内置的两个领域专用 sub-agent。它们扩展了框架的视频创作与编辑能力，通过 `AgentTool` 调用，受 Agent Loop 统一管理（权限检查、hooks、token 追踪）。

---

## Agent 架构

```
OpenHarness 主 Agent（oh）
    ├── capcut-director  — 剪映编导（Agent loop: 脚本策划 → 剪辑执行）
    └── video-editor     — FFmpeg 剪辑师（Agent loop: 探测素材 → 执行编辑）
```

两个 Agent 定位不同、互不重叠：

| | capcut-director | video-editor |
|---|---|---|
| **操作对象** | 剪映草稿 JSON 文件 | 视频/音频媒体文件 |
| **输出** | 剪映可打开的草稿文件 | 编码后的视频文件 |
| **编辑方式** | 非破坏性，可反复修改 | 破坏性，生成新文件 |
| **侧重** | 创意编排（布局/特效/文字/动画） | 技术处理（编码/混音/烧录） |
| **底层引擎** | pyJianYingDraft 库 | FFmpeg 管线 |
| **工具数量** | 11 个 | 2 个 |

---

## 1. capcut-director（剪映编导）

### 定位

剪映草稿创作。接收创意描述，规划视频脚本（分镜/时间线/素材/特效），用户确认后自动执行剪辑。输出为可在剪映/CapCut 中打开的草稿文件。

### 双阶段工作流

| 阶段 | 行为 | 产出 |
|------|------|------|
| **Phase 1: 脚本策划** | 接收创意描述，生成结构化分镜脚本 | 分镜列表（时长/素材/字幕/特效/转场） |
| **Phase 2: 剪辑执行** | 用户确认后，按脚本调用 tool 链 | 剪映草稿文件 |

### 可用 Tools（11 个）

| 类别 | Tool | 功能 |
|------|------|------|
| 草稿管理 | `capcut_create_draft` | 创建草稿，设置画布尺寸 |
| | `capcut_save_draft` | 保存草稿 |
| 媒体素材 | `capcut_add_videos` | 添加视频，支持裁剪/缩放/转场 |
| | `capcut_add_images` | 添加图片，支持动画/转场 |
| | `capcut_add_sticker` | 添加贴纸 |
| | `capcut_add_audios` | 添加音频，支持音量/效果 |
| 文本字幕 | `capcut_add_captions` | 添加字幕，支持关键词高亮/样式/动画/阴影 |
| | `capcut_add_text_style` | 生成富文本样式 JSON |
| 特效动画 | `capcut_add_effects` | 添加场景/人物特效 |
| | `capcut_add_keyframes` | 关键帧动画（位移/缩放/旋转/透明度等） |
| | `capcut_add_masks` | 遮罩效果（线性/圆形/矩形/爱心/星形等） |

### 适用场景

- 图文成片（图片 + 字幕 + 背景音乐）
- 产品展示视频（关键帧动画 + 特效 + 字幕）
- 口播字幕视频（关键词高亮 + 文字动画）
- 模板套用（换素材保持特效不变）
- 批量营销短视频

### 典型指令

- "做一个 30 秒的科技感产品介绍视频"
- "把这些图片做成带转场和字幕的短视频"
- "给视频加上关键词高亮字幕和转场效果"
- "做一个产品展示视频，图片有缩放动画"

### Skill 描述

```
name: capcut-director
description: |
  剪映草稿创作编导。当用户需要创作短视频、产品介绍、图文成片等视频内容，
  且希望输出为剪映草稿（可在剪映中继续编辑）时使用。

  工作方式：接收用户的创意描述 → 生成视频脚本（分镜、时间线、素材、特效安排）
  → 用户确认后自动调用剪映工具链执行。

  支持：视频/图片/贴纸/音频添加、字幕（关键词高亮）、特效、关键帧动画、遮罩。

  与 video-editor 的区别：capcut-director 操作剪映草稿文件（非破坏性），
  video-editor 直接处理视频文件（FFmpeg 编码输出）。
```

---

## 2. video-editor（FFmpeg 剪辑师）

### 定位

FFmpeg 视频处理。接收视频编辑请求，先探测素材参数，再构造结构化 JSON 调用 FFmpeg 管线。输出为编码后的视频文件。

### 工作流

| 步骤 | 行为 | Tool |
|------|------|------|
| **Step 1** | 探测素材参数（时长/分辨率/帧率） | `video_probe` |
| **Step 2** | 构造 VideoEditRequest JSON 并执行 | `video_edit` |

### 可用 Tools（2 个）

| Tool | 功能 |
|------|------|
| `video_probe` | 探测视频/音频文件元信息：时长、分辨率、帧率、编码格式、音轨 |
| `video_edit` | 执行视频编辑：接收 VideoEditRequest JSON → 验证 → FFmpeg 管线 → 输出 |

### 支持的操作

| 类别 | 操作 |
|------|------|
| 视频 | 拼接（concat）、截取（trim）、变速、倒放 |
| 音频 | 混合（TTS/原声/BGM）、自动音量平衡、淡入淡出、延迟 |
| 字幕 | ASS/SRT 文件烧录、Whisper ASR 自动生成（支持样式/关键词高亮） |
| 叠加 | 图片/GIF 叠加、画中画视频叠加 |
| 转场 | 21 种特效（fade, wipeleft, circleopen 等） |
| 滤镜 | 亮度/对比度/饱和度调节 |
| 输出 | 分辨率/帧率/码率设置 |

### 适用场景

- 视频拼接 + 配音 + 字幕烧录
- 去掉原声换背景音乐
- 截取片段 + 调色
- Whisper 自动生成语音字幕
- 多段视频 + 转场 + 图片水印

### 典型指令

- "合并 intro.mp4 和 main.mp4，加上字幕"
- "把 video.mp4 去掉原声，换上配音和背景音乐"
- "从 main.mp4 截取 0:30-1:30，饱和度 +20%"
- "为 video.mp4 自动生成中文字幕"

### Skill 描述

```
name: video-editor
description: |
  FFmpeg 视频剪辑师。当用户需要对视频文件进行实际处理（编码、拼接、截取、
  混音、字幕烧录等）并输出新的视频文件时使用。

  工作方式：先用 video_probe 探测素材参数 → 构造 VideoEditRequest JSON
  → 调用 video_edit 执行 FFmpeg 管线。

  支持：视频拼接截取、音频混合（TTS/原声/BGM 自动音量平衡）、字幕烧录
  （ASS/SRT/Whisper ASR）、图片/视频叠加、转场特效（21 种）、色彩调节、
  变速倒放。

  与 capcut-director 的区别：video-editor 直接处理视频文件（FFmpeg 编码输出），
  capcut-director 操作剪映草稿文件（非破坏性）。
```

---

## Agent 选择指南

| 用户需求 | 推荐 Agent | 原因 |
|----------|-----------|------|
| "做一个产品介绍短视频" | capcut-director | 创意编排，需要特效/字幕/动画 |
| "合并两个视频加字幕" | video-editor | 技术处理，直接输出文件 |
| "给视频加关键词高亮字幕" | capcut-director | 字幕样式编排 |
| "去掉原声换背景音乐" | video-editor | 音频混合处理 |
| "这些图片做成带特效的视频" | capcut-director | 需要动画/特效/转场 |
| "截取片段并调色" | video-editor | 单一技术操作 |
| "生成带字幕的视频草稿" | capcut-director | 输出草稿供后续编辑 |
| "Whisper 自动生成字幕并烧录" | video-editor | FFmpeg 字幕烧录 |

---

## 代码结构

```
src/openharness/
├── capcut/                          # 剪映草稿模块
│   ├── __init__.py
│   ├── config.py                    # 路径配置
│   ├── draft_manager.py             # 草稿生命周期管理（LRU 缓存）
│   ├── utils.py                     # 共享工具函数
│   ├── pyJianYingDraft/             # 剪映草稿操作库（36 个文件）
│   └── template/default2/           # 草稿模板
│
├── video_editor/                    # FFmpeg 视频编辑模块
│   ├── __init__.py
│   ├── schema.py                    # Pydantic 模型（VideoEditRequest）
│   ├── validator.py                 # 运行时验证（文件存在/时间线）
│   ├── executor.py                  # 参数转换 + 执行桥接
│   ├── ffmpeg_core.py               # FFmpeg 管线（concat/xfade/overlay）
│   ├── subtitle_gen.py              # ASS/SRT 字幕生成
│   └── subtitle_handler.py          # Whisper ASR 集成
│
├── tools/                           # Tool 层
│   ├── capcut_*_tool.py             # 11 个剪映工具
│   ├── video_probe_tool.py          # 视频探测工具
│   ├── video_edit_tool.py           # 视频编辑工具
│   └── __init__.py                  # 注册所有 50 个工具
│
└── coordinator/
    └── agent_definitions.py         # Agent 定义（含 capcut-director, video-editor）
```

---

## 调用方式

两个 Agent 都是 OpenHarness 内置 Agent，通过 `AgentTool` 由主 Agent 调度：

```python
# 调用剪映编导
AgentTool(
    description="制作产品介绍视频",
    prompt="做一个30秒的科技感产品介绍视频，用这些图片和文案...",
    subagent_type="capcut-director"
)

# 调用 FFmpeg 剪辑师
AgentTool(
    description="合并视频加字幕",
    prompt="合并 intro.mp4 和 main.mp4，加上字幕 output.srt，输出 final.mp4",
    subagent_type="video-editor"
)
```

在 OpenHarness TUI 中，用户直接描述需求，主 Agent 自动选择合适的 sub-agent 执行。
