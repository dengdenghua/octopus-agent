# 视频库 UX 增强 Spec

## Why
后端已具备视频语义索引能力（`video_semantic_index.py` + `media_router`，覆盖文→视频、图→视频、人脸→视频、语音转写、人脸分组、场景分类），但前端「本地数据库 → 视频」库仍是静态缩略图列表：只能重建索引，无法搜索、无法点击跳转播放到时间点、看不到人脸相册/标签/摘要/封面。本次补齐视频库的**检索闭环与前 UX**，让用户真正用得起视频 AI 检索。

## What Changes
- **后端 `media_router` 扩展**：新增文档/人脸/语音/分类/关键帧封面/OCR 等只读端点，复用 `video_semantic_index` 既有函数，全部 self-gating（索引缺失或模型不可用时返回 `ok:false`，不崩）。
- **前端 `api.ts` 扩展**：新增视频检索、人脸相册、分类、封面、OCR 的 API 函数与类型。
- **前端 `storage/page.tsx` 视频库重构**：`VideoLibraryView` 从"纯列表"升级为含搜索、筛选、结果跳转、播放器弹层、人脸相册、标签筛选、摘要与封面的完整视图。
- **新增视频播放器弹层**：点结果/缩略图进入播放器，支持 `time_sec` 跳转定位到命中关键帧，并展示相邻命中的上一段/下一段。
- **人脸相册 Tab**：按 `group_video_faces` 返回的人物分组展示，点击人物进入其出现片段列表。
- **标签筛选**：按 `classify_video` 返回的场景标签（风景/人物/城市/会议…）做筛选，与既有 `docs/images` 的 smart-filter 交互一致。
- **视频摘要 + 自动封面**：利用关键帧分类标签聚合生成摘要，从关键帧中挑一张作为封面并持久化/点击预览。
- **OCR 文字识别（P0）**：复用 `image_semantic_index.ocr_image`，对关键帧做 OCR，支持"按视频内文字检索"。
- 所有新增 i18n 文案补齐 4 种语言（zh-CN / en-US / ja-JP / ko-KR）。

## Impact
- Affected specs: `video-understanding-ai-search`（其产物是本次前端的后端依赖）
- Affected code:
  - `runtime/sensing/gateway/media_router.py`（新增端点）
  - `runtime/memory/hemolymph/video_semantic_index.py`（补充关键帧封面/OCR 辅助函数，若需）
  - `frontend/src/core/storage/api.ts`（新增 API + 类型）
  - `frontend/src/app/workspace/storage/page.tsx`（视频库视图重构）
  - `frontend/src/core/i18n/locales/{zh-CN,en-US,ja-JP,ko-KR}.ts` + `types.ts`（新增文案）
- 不破坏既有图片/文档/视频索引能力；新增端点均为只读。

## ADDED Requirements
### Requirement: 视频语义检索闭环
系统 SHALL 在视频库提供文本语义检索，命中结果展示所属视频、时间点与相似度，点击后跳转到播放器对应时间点播放。

#### Scenario: 检索并跳转定位
- **WHEN** 用户在视频库搜索框输入文字并回车
- **THEN** 系统调用 `video_search_by_text` 返回命中列表，展示 `视频名/时间点/分数`；点击某条命中打开播放器并定位到 `time_sec`
- **AND** 播放器提供命中段的上一段/下一段跳转与"关闭/返回"能力

### Requirement: 视频人脸相册
系统 SHALL 在视频库提供"人物"Tab，按 `group_video_faces` 聚类结果分组展示人物，点击人物查看其出现的视频片段。

#### Scenario: 浏览人物相册
- **WHEN** 用户切换到"人物"Tab 且索引含人脸数据
- **THEN** 系统展示 `[person, count_faces, appearances]` 分组卡片，点击某一人物展开其出现片段（视频+时间点），点击片段跳转播放

### Requirement: 视频标签筛选
系统 SHALL 在视频库提供场景标签筛选，标签来自 `classify_video` 的关键帧聚合分类。

#### Scenario: 按标签筛视频
- **WHEN** 用户点击"风景/人物/会议"等标签 chip
- **THEN** 网格仅显示带该标签的视频；未建索引/无标签时给出提示并保持降级

### Requirement: 视频摘要与自动封面
系统 SHALL 为已索引视频生成内容摘要（Top 场景标签聚合）与静态封面（取一张关键帧）。

#### Scenario: 展示摘要与封面
- **WHEN** 用户悬停或进入视频详情
- **THEN** 展示分类标签与一句话摘要；缩略图使用关键帧封面而非未加载的 `<video>` 首帧

### Requirement: 视频内文字 OCR 检索
系统 SHALL 复用图片 OCR 能力，对视频关键帧做文字识别，支持按文字检索视频片段。

#### Scenario: 按视频内文字检索
- **WHEN** 用户在视频库搜索"界面截图里的按钮文字"等
- **THEN** 系统对关键帧 OCR 结果做包含匹配，返回命中的视频与时间点（OCR 未启用/不可用时降级为空结果）

## MODIFIED Requirements
### Requirement: 重建索引入口（保留）
原有"重建索引"按钮行为不变，仍调用 `triggerVideoIndex`，但索引完成后前端应刷新视频列表、人脸相册、标签、摘要与封面缓存。

**Reason**: 检索/相册/标签/摘要都依赖索引数据，索引更新后需一并刷新。
**Migration**: 无破坏性变更；既有 `triggerVideoIndex` 契约不变。

## REMOVED Requirements
无（本 spec 不删除既有能力）。