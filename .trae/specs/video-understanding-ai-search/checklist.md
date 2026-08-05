# Checklist

- [x] `video_semantic_index.py` 建表逻辑正确（meta/keyframes/faces/transcript/tags）
- [x] PyAV 关键帧抽取（固定间隔 + 场景切换）有效
- [x] `build_video_index` 建立索引并返回统计
- [x] `search_video_by_text` 文→视频定位时间点
- [x] `search_video_by_image` 图→视频检索
- [x] `search_face_in_videos` 人脸→视频检索
- [x] `group_video_faces` 跨视频人脸分组
- [x] `classify_video` 关键帧分类生成摘要/标签
- [x] `search_video_by_speech` 语音转写检索（whisper 可用时）
- [x] 全部能力 self-gating（av/CLIP/whisper 缺失时不崩溃）
- [x] `video_album_skills.py` 注册全部 7 个技能，每个带 self-gating
- [x] `faster-whisper` 已声明到依赖
- [x] `builtins.py::register_all` 注册新技能且返回计数正确
- [x] `register_all` 完整加载不崩、无重复注册
- [x] 全链路验证通过（索引/文搜/图搜/人脸/摘要/语音）