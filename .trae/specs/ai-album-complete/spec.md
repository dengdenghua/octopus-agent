# AI 相册完整能力 Spec

## Why
octopus-agent 已具备本地图片语义检索（CLIP 双塔：文→图、图→图）与人脸聚类（ArcFace），对标绿联 DXP8800 Ultra「AI 相册」的核心能力。但相比绿联完整能力，仍缺：图像分类识别、OCR 文字识别、敏感内容识别、模糊照片识别、重复照片识别、多条件组合筛选、AI 自学习训练。本次补齐这些能力，使 octopus-agent 达到「视觉理解＋人脸聚类＋OCR＋内容安全＋图库清理＋组合检索＋自定义训练」的完整相册 AI 水平。

## What Changes
- 扩展 `image_semantic_index.py`：新增元数据表（拍摄时间、EXIF、文件类型、尺寸、mtime）、图像分类标签、OCR 文本、感知哈希（用于重复检测）、清晰度评分（用于模糊检测）。
- 新增 `image_album_skills.py`：注册 `image_analyze` / `image_ocr` / `image_find_duplicates` / `image_find_blurry` / `image_filter_meta` / `image_sensitive_scan` / `image_train_category` 等 Agent 技能。
- 复用已装的 `fastembed` + `opencv` + `numpy`；OCR 依赖 `rapidocr-onnxruntime`（轻量，新增依赖）。
- 敏感内容识别采用 CLIP zero-shot（NSFW 语义标签），不引入重型分类模型，**不删除/不自动处理**，仅标记供用户确认。
- 所有能力保持 self-gating：依赖缺失或 `OCTOPUS_IMAGE_SEMANTIC=0` 时优雅降级，不阻断启动。
- 注册入口接入 `builtins.py::register_all`。

## Impact
- Affected specs: 本地图片语义检索（此前已实现）
- Affected code:
  - `runtime/memory/hemolymph/image_semantic_index.py`（扩展）
  - `runtime/execution/suckers/image_semantic_skills.py`（保持）
  - `runtime/execution/suckers/image_album_skills.py`（新增）
  - `runtime/execution/suckers/builtins.py`（注册）
  - `uv.lock` / `pyproject.toml`（新增 OCR 依赖）

## ADDED Requirements
### Requirement: 图像内容分类识别
系统 SHALL 对图片做 zero-shot 视觉分类，返回与预置/自定义标签的匹配度。

#### Scenario: 分类一张照片
- **WHEN** 用户调用 `image_analyze` 传入图片路径或自然语言标签
- **THEN** 系统返回各标签的匹配分数，并给出最可能的分类

### Requirement: OCR 文字识别
系统 SHALL 识别图片中的文字，支持按文字搜索图片及提取文字内容。

#### Scenario: 识别截图文字
- **WHEN** 用户调用 `image_ocr` 传入图片路径
- **THEN** 系统返回识别出的文字及置信度，并写入索引供 `image_search_by_text` 检索

### Requirement: 重复照片识别
系统 SHALL 找出重复或近似重复的照片（基于感知哈希 + 图片向量余弦）。

#### Scenario: 清理重复照片
- **WHEN** 用户调用 `image_find_duplicates`
- **THEN** 系统返回重复分组及每组代表图，**仅列出供用户确认，不自动删除**

### Requirement: 模糊照片识别
系统 SHALL 识别失焦、抖动或清晰度差的照片（Laplacian 方差 + 抖动检测）。

#### Scenario: 查找模糊照片
- **WHEN** 用户调用 `image_find_blurry`
- **THEN** 系统返回清晰度评分低于阈值的图片列表，供用户确认后手动删除

### Requirement: 敏感内容识别
系统 SHALL 识别潜在敏感图片并标记（CLIP zero-shot NSFW 语义）。

#### Scenario: 扫描敏感图片
- **WHEN** 用户调用 `image_sensitive_scan`
- **THEN** 系统返回疑似敏感图片及类别，**仅标记不处理**，交由用户浏览时模糊显示

### Requirement: 多条件组合筛选
系统 SHALL 支持按元数据（时间范围、文件类型、人物、地点/场景、尺寸）组合筛选照片。

#### Scenario: 组合筛选
- **WHEN** 用户调用 `image_filter_meta` 传入 `{year, location, person, scene, type}`
- **THEN** 系统返回满足全部条件的图片列表

### Requirement: AI 自学习训练
系统 SHALL 支持用户在 CLIP 之上通过 few-shot 方式定义新类别（原型向量），无需真正训练。

#### Scenario: 自定义新类别
- **WHEN** 用户调用 `image_train_category` 传入类别名 + 若干示例图
- **THEN** 系统生成并存储该类别原型向量，后续 `image_analyze` 可识别该自定义类别

## MODIFIED Requirements
### Requirement: 既有图片语义检索（register 扩展）
原有 5 个图像技能（`image_index_build` / `image_search_by_text` / `image_search_by_image` / `face_group_albums` / `face_search_by_image`）保持行为不变；`image_index_build` 额外采集元数据、OCR、哈希、清晰度标签，供新技能使用。

**Reason**: 新能力依赖索引期采集的补充数据。
**Migration**: 既有索引无需强制重建；新字段在下次 `image_index_build` 时补齐。