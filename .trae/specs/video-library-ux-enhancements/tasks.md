# Tasks

- [x] Task 1: 后端 `media_router` 扩展只读视频端点
  - [x] SubTask 1.1: 确认 `POST /video/search/face` 入参/出参与前端一致
  - [x] SubTask 1.2: 新增 `GET /video/faces`（`group_video_faces`）→ `[{person, count_faces, appearances:[{video_path,time_sec}]}]`
  - [x] SubTask 1.3: 新增 `POST /video/classify`（`classify_video`）→ `results:[{video_path, tags:[{label,score}]}]`
  - [x] SubTask 1.4: 新增 `POST /video/search/speech`（`search_video_by_speech`）→ `[{video_path,start_sec,end_sec,text,score}]`
  - [x] SubTask 1.5: 新增 `POST /video/search/image`（`search_video_by_image`）
  - [x] SubTask 1.6: 新增 `GET /video/cover`（`extract_frame_jpeg` 返回 JPEG 关键帧静态图）
  - [x] SubTask 1.7: 新增 `POST /video/ocr`（`ocr_video_keyframes` 复用 `image_semantic_index.ocr_image`）
  - [x] SubTask 1.8: 全部端点 self-gating（索引/模型缺失时 `ok:false`，不抛 500）

- [x] Task 2: 前端 `api.ts` 新增视频 API 与类型
  - [x] SubTask 2.1: 新增 `NASVideoSearchHit`、`NASVideoFaceGroup`、`NASVideoTag`、`NASVideoCover` 等类型
  - [x] SubTask 2.2: 新增 `searchVideoByText` / `searchVideoByFace` / `searchVideoBySpeech` / `searchVideoByImage`
  - [x] SubTask 2.3: 新增 `listVideoFaceGroups` / `classifyVideoTags` / `getVideoCoverURL`
  - [x] SubTask 2.4: 新增 `ocrVideoKeyframes`（OCR 文字检索）

- [x] Task 3: 前端视频库视图重构（storage/page.tsx）
  - [x] SubTask 3.1: `VideoLibraryView` 增加 Tab（视频 / 人物 / 标签），与 smart-filter 交互一致
  - [x] SubTask 3.2: 文本搜索接入 `searchVideoByText`，结果列表展示 视频/时间点/分数，点击进入播放器定位
  - [x] SubTask 3.3: 新增视频播放器弹层（`video` 元素 + `currentTime=time_sec` + 上一段/下一段 + 关闭）
  - [x] SubTask 3.4: 人脸相册列表：按 `listVideoFaceGroups` 渲染人物卡片，点击展开出现片段
  - [x] SubTask 3.5: 标签筛选：按 `classifyVideoTags` 渲染标签 chip，点击过滤网格
  - [x] SubTask 3.6: 摘要 + 封面：缩略图改用 `getVideoCoverURL`，悬停/详情展示标签摘要
  - [x] SubTask 3.7: OCR 检索：搜索命中落到 `ocrVideoKeyframes`，同样支持跳转播放

- [x] Task 4: i18n 文案补齐（4 语言）
  - [x] SubTask 4.1: `zh-CN.ts` 新增视频库文案（Tab 名/搜索占位/相册/标签/摘要/封面/OCR/播放器按钮）
  - [x] SubTask 4.2: `en-US.ts` / `ja-JP.ts` / `ko-KR.ts` 同步补齐
  - [x] SubTask 4.3: `types.ts` 补齐对应类型定义

- [x] Task 5: 全链路验证
  - [x] SubTask 5.1: 构建测试索引（含画面切换 + 人脸 + 文字关键帧）
  - [x] SubTask 5.2: 验证文本搜索命中并跳转播放到 `time_sec`
  - [x] SubTask 5.3: 验证人脸相册分组与片段跳转
  - [x] SubTask 5.4: 验证标签筛选过滤网格
  - [x] SubTask 5.5: 验证摘要展示与封面图加载
  - [x] SubTask 5.6: 验证 OCR 文字检索命中
  - [x] SubTask 5.7: 验证索引缺失/模型不可用时全部端点优雅降级、前端不崩

# Task Dependencies
- Task 2 依赖 Task 1（前端调用后端新增端点）
- Task 3 依赖 Task 2（视图用前端 API）
- Task 4 依赖 Task 3（文案随视图落地）
- Task 5 依赖 Task 1/2/3/4（全链路验证在实现完成后）