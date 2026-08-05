# 视频理解 + AI 检索 Spec

## Why
octopus-agent 已具备本地图片语义检索（CLIP 双塔）与 AI 相册能力（分类/OCR/人脸/重复/模糊/筛选/训练），对标绿联 NAS 的「AI 相册」。但视频理解与 AI 检索仍是空白：用户无法对本地视频做「按文字找片段」「按人脸找人」「按台词搜视频」「视频内容摘要」。本次补齐视频理解与检索能力，使 agent 达到「关键帧抽取 + 语义定位 + 人脸分组 + 语音转写 + 场景分类」的完整视频 AI 检索水平。

## What Changes
- 新增 `video_semantic_index.py`：基于 PyAV 解码抽关键帧，CLIP 视觉塔嵌入，SQLite 持久化，支持文→视频、图→视频、人脸→视频、语音转写检索。
- 新增 `video_album_skills.py`：注册 `video_index_build` / `video_search_by_text` / `video_search_by_image` / `video_search_by_speech` / `video_search_by_face` / `video_analyze` / `video_face_albums` 等 Agent 技能。
- 复用既有的 `fastembed`（CLIP 视觉塔）、`insightface`（人脸）、`av`（PyAV 解码，自带 ffmpeg 库，无需系统 ffmpeg）。
- 语音转写可选依赖 `faster-whisper`（轻量 CTranslate2 实现）；未安装时转写/语音检索 self-gating 降级，不阻断启动。
- 所有能力保持 self-gating：`av` 缺失、CLIP 塔不可用、`OCTOPUS_VIDEO_SEMANTIC=0` 时优雅降级，不阻断启动。
- 注册入口接入 `builtins.py::register_all`。

## Impact
- Affected specs: 本地图片语义检索（复用其模型与视觉塔）
- Affected code:
  - `runtime/memory/hemolymph/video_semantic_index.py`（新增）
  - `runtime/execution/suckers/video_album_skills.py`（新增）
  - `runtime/execution/suckers/builtins.py`（注册）
  - `pyproject.toml`（新增 `faster-whisper` 可选依赖）

## ADDED Requirements
### Requirement: 视频关键帧抽取与语义索引
系统 SHALL 用 PyAV 解码视频，按场景切换或固定间隔抽取关键帧，用 CLIP 视觉塔嵌入并持久化，供文本/图片/人脸检索定位到具体时间点。

#### Scenario: 建立视频索引
- **WHEN** 用户调用 `video_index_build` 传入目录
- **THEN** 系统扫描视频、抽取关键帧、生成向量，返回索引统计（视频数/关键帧数/时长）

### Requirement: 文→视频检索
系统 SHALL 用文字描述匹配视频关键帧，返回命中视频及关键帧时间点。

#### Scenario: 检索"人物奔跑"片段
- **WHEN** 用户调用 `video_search_by_text` 传入 `{query, directory}`
- **THEN** 系统返回按相似度排序的 `[视频, 时间点, 分数]` 列表

### Requirement: 图→视频检索
系统 SHALL 用一张图片在视频关键帧中检索视觉相似片段。

#### Scenario: 以图搜片
- **WHEN** 用户调用 `video_search_by_image` 传入图片路径
- **THEN** 系统返回包含相似画面的视频及时间点

### Requirement: 语音转写检索
系统 SHALL 对视频音轨做语音转写（faster-whisper），支持按台词/语音内容检索视频片段。

#### Scenario: 按台词搜视频
- **WHEN** 用户调用 `video_search_by_speech` 传入 `{query, directory}`
- **THEN** 系统返回命中台词、所在视频与时间段（需先开启转写索引）

### Requirement: 视频人脸检索与分组
系统 SHALL 对视频关键帧做 ArcFace 人脸嵌入，支持按人脸在视频中检索，以及跨视频的人脸分组。

#### Scenario: 按人脸找视频
- **WHEN** 用户调用 `video_search_by_face` 传入图片路径
- **THEN** 系统返回包含同一人的视频、时间点与分数

#### Scenario: 视频人物分组
- **WHEN** 用户调用 `video_face_albums`
- **THEN** 系统对跨视频帧的人脸聚类，返回人物分组及出现片段

### Requirement: 视频内容摘要与分类
系统 SHALL 对视频关键帧做 CLIP zero-shot 分类，汇总生成视频场景标签与内容摘要。

#### Scenario: 生成视频摘要
- **WHEN** 用户调用 `video_analyze` 传入视频路径
- **THEN** 系统返回视频时长、关键帧数、Top 场景标签及聚合摘要

### Requirement: 自动增量索引
系统 SHALL 通过后台监控（watchdog）定期扫描目录，仅对新增或修改的视频文件做关键帧抽取与嵌入，并清理已消失文件的陈旧索引，避免全量重建。

#### Scenario: 目录持续监控
- **WHEN** 用户调用 `video_index_build` 传入 `{incremental: true, watch: true}`
- **THEN** 系统启动后台扫描器，定期按 mtime 增量更新索引，返回监控已启动

#### Scenario: 增量重扫
- **WHEN** 用户调用 `video_index_build` 传入 `{incremental: true}`
- **THEN** 系统仅处理新增或 mtime 变化的视频，删除已消失文件的索引，返回 `{videos_indexed, skipped, incremental}`

### Requirement: 硬件加速
系统 SHALL 支持通过环境变量启用 ONNX Runtime GPU 执行提供器（CUDA/TensorRT）与模型量化，并在低功耗设备上加速 CLIP 嵌入与人脸检测；语音转写支持选择 GPU 设备与 INT8/FP16 计算类型。

#### Scenario: 启用 GPU 推理
- **WHEN** 设置 `OCTOPUS_ORT_PROVIDERS=CUDAExecutionProvider` 且安装了 `onnxruntime-gpu`
- **THEN** CLIP 双塔与人脸检测使用 CUDA 执行提供器；未安装 GPU 构建时静默回退 CPU

#### Scenario: 启用量化
- **WHEN** 设置 `OCTOPUS_EMBED_QUANTIZE=int8`
- **THEN** CLIP 模型以 int8 量化加载，缩小体积并加速推理

#### Scenario: 查询加速状态
- **WHEN** 用户调用 `GET /media/video/hardware`
- **THEN** 系统返回 `{ort_providers, gpu_requested, embed_quantization, whisper_device, whisper_compute}`

## MODIFIED Requirements
### Requirement: 复用既有图片语义能力（register 扩展）
原有图片技能（`image_index_build` / `image_search_by_text` / 等）保持行为不变；视频模块复用同一 CLIP 视觉塔与 insightface 人脸模型，不重复加载模型。

**Reason**: 关键帧本质是图片，可直接复用图片语义管线。
**Migration**: 无破坏性变更；视频索引独立于图片索引，互不影响。