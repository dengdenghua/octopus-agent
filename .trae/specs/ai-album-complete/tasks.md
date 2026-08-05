# Tasks

- [x] Task 1: 扩展 `image_semantic_index.py` 数据层
  - [x] SubTask 1.1: 新增 `image_meta` 扩展字段（exif 时间、拍摄地点、文件类型、尺寸、mtime）
  - [x] SubTask 1.2: 新增 `image_tags` 表（分类标签 -> 分数）
  - [x] SubTask 1.3: 新增 `image_ocr` 表（图片路径 -> 识别文本）
  - [x] SubTask 1.4: 新增 `image_hashes` 表（感知哈希 -> 路径，用于重复检测）
  - [x] SubTask 1.5: 新增 `image_quality` 表（清晰度评分 -> 路径，用于模糊检测）
  - [x] SubTask 1.6: 新增 `image_categories` 表（few-shot 自定义类别原型向量）
  - [x] SubTask 1.7: 在 `build_index` 中采集新字段（EXIF 时间、dHash、清晰度、触发 OCR）
  - [x] SubTask 1.8: 新增工具函数：`classify_image` / `ocr_image` / `find_duplicates` / `find_blurry` / `filter_meta` / `train_category` / `sensitive_scan`

- [x] Task 2: 新增 `image_album_skills.py` 技能层
  - [x] SubTask 2.1: 实现 `image_analyze`（zero-shot 分类，含自定义类别）
  - [x] SubTask 2.2: 实现 `image_ocr`（文字识别 + 写入索引）
  - [x] SubTask 2.3: 实现 `image_find_duplicates`（重复分组，仅列出）
  - [x] SubTask 2.4: 实现 `image_find_blurry`（模糊检测，仅列出）
  - [x] SubTask 2.5: 实现 `image_sensitive_scan`（NSFW 标记，不处理）
  - [x] SubTask 2.6: 实现 `image_filter_meta`（多条件组合筛选）
  - [x] SubTask 2.7: 实现 `image_train_category`（few-shot 自定义类别）
  - [x] SubTask 2.8: 为每个技能注册 `Skill`（self-gating + 描述 + affinity）

- [x] Task 3: 注册依赖与入口
  - [x] SubTask 3.1: `uv add rapidocr-onnxruntime`（OCR 依赖）
  - [x] SubTask 3.2: 在 `builtins.py::register_all` 注册 `image_album_skills`
  - [x] SubTask 3.3: 更新 `register_all` 返回计数

- [x] Task 4: 全链路验证
  - [x] SubTask 4.1: 构造测试图片（含文字截图、模糊图、重复图、彩色分类图）
  - [x] SubTask 4.2: 验证 `image_analyze` 分类正确
  - [x] SubTask 4.3: 验证 `image_ocr` 识别文字
  - [x] SubTask 4.4: 验证 `image_find_duplicates` 分组
  - [x] SubTask 4.5: 验证 `image_find_blurry` 标记模糊
  - [x] SubTask 4.6: 验证 `image_sensitive_scan` 标记
  - [x] SubTask 4.7: 验证 `image_filter_meta` 组合筛选
  - [x] SubTask 4.8: 验证 `image_train_category` few-shot 分类
  - [x] SubTask 4.9: 验证 `register_all` 完整加载不崩、无重复注册

# Task Dependencies
- Task 2 依赖 Task 1（技能层调用数据层工具函数）
- Task 3 依赖 Task 2（先实现技能再注册）
- Task 4 依赖 Task 1/2/3（全链路验证在实现完成后）