# Checklist

- [x] `media_router` 新增 faces / classify / speech / image / cover / ocr 端点，全部 self-gating
- [x] 新增端点复用 `video_semantic_index` 既有函数，无重复实现
- [x] `api.ts` 新增视频检索/相册/标签/封面/OCR API 与类型
- [x] `VideoLibraryView` 支持 视频/人物/标签 三 Tab 切换
- [x] 文本搜索命中展示 视频/时间点/分数
- [x] 点击命中打开播放器并定位到 `time_sec`
- [x] 播放器支持上一段/下一段跳转与关闭
- [x] 人脸相册按分组渲染，点击人物展开出现片段并可跳转
- [x] 标签筛选过滤网格，未建索引时降级提示
- [x] 缩略图使用关键帧封面，悬停/详情展示分类摘要
- [x] OCR 文字检索命中并支持跳转播放
- [x] 索引缺失/模型不可用时前端不崩、端点优雅降级
- [x] 视频库新增文案在 4 种语言全部补齐
- [x] 全链路验证通过（文本/人脸/标签/摘要/封面/OCR/降级）