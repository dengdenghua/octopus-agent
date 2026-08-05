# Tasks

- [x] Task 1: 新增 `video_semantic_index.py` 视频数据层
  - [x] SubTask 1.1: 建表（video_meta / video_keyframes / video_faces / video_transcript / video_tags）
  - [x] SubTask 1.2: 实现 PyAV 关键帧抽取（固定间隔 + 场景切换检测）
  - [x] SubTask 1.3: 实现 `build_video_index`（CLIP 嵌入关键帧 + 可选人脸/转写）
  - [x] SubTask 1.4: 实现 `search_video_by_text`（文→关键帧→视频+时间点）
  - [x] SubTask 1.5: 实现 `search_video_by_image`（图→关键帧）
  - [x] SubTask 1.6: 实现 `search_video_by_speech`（faster-whisper 转写检索）
  - [x] SubTask 1.7: 实现 `search_face_in_videos`（人脸→视频）
  - [x] SubTask 1.8: 实现 `group_video_faces`（跨视频人脸聚类）
  - [x] SubTask 1.9: 实现 `classify_video`（zero-shot 关键帧分类 → 摘要/标签）
  - [x] SubTask 1.10: 全部 self-gating（av/CLIP/whisper 缺失时优雅降级）

- [x] Task 2: 新增 `video_album_skills.py` 技能层
  - [x] SubTask 2.1: 实现 `video_index_build`
  - [x] SubTask 2.2: 实现 `video_search_by_text`
  - [x] SubTask 2.3: 实现 `video_search_by_image`
  - [x] SubTask 2.4: 实现 `video_search_by_speech`
  - [x] SubTask 2.5: 实现 `video_search_by_face`
  - [x] SubTask 2.6: 实现 `video_analyze`（摘要/分类）
  - [x] SubTask 2.7: 实现 `video_face_albums`（分组）
  - [x] SubTask 2.8: 为每个技能注册 `Skill`（self-gating + 描述 + affinity）

- [x] Task 3: 注册依赖与入口
  - [x] SubTask 3.1: `pyproject.toml` 声明 `faster-whisper` 可选依赖
  - [x] SubTask 3.2: 在 `builtins.py::register_all` 注册 `video_album_skills`
  - [x] SubTask 3.3: 更新 `register_all` 返回计数

- [x] Task 4: 全链路验证
  - [x] SubTask 4.1: 用 PyAV 构造测试视频（含画面切换 + 人脸 + 音轨）
  - [x] SubTask 4.2: 验证 `video_index_build` 建立索引
  - [x] SubTask 4.3: 验证 `video_search_by_text` 定位时间点
  - [x] SubTask 4.4: 验证 `video_search_by_image` 以图搜片
  - [x] SubTask 4.5: 验证 `video_search_by_face` 人脸检索
  - [x] SubTask 4.6: 验证 `video_analyze` 摘要分类
  - [x] SubTask 4.7: 验证 `video_search_by_speech`（依赖 whisper 可用时）
  - [x] SubTask 4.8: 验证 `register_all` 完整加载不崩、无重复注册

# Task Dependencies
- Task 2 依赖 Task 1（技能层调用数据层）
- Task 3 依赖 Task 2（先实现技能再注册）
- Task 4 依赖 Task 1/2/3（全链路验证在实现完成后）