# Checklist

- [x] `image_semantic_index.py` 新增各表（tags/ocr/hashes/quality/categories）建表逻辑正确
- [x] `build_index` 采集 EXIF 时间、dHash、清晰度、OCR 文本
- [x] `classify_image` 返回预置标签匹配分数，支持自定义类别
- [x] `ocr_image` 识别文字并写入索引
- [x] `find_duplicates` 返回重复分组（仅列出，不删除）
- [x] `find_blurry` 返回低清晰度图片列表（仅列出）
- [x] `sensitive_scan` 标记疑似敏感图片（仅标记，不处理）
- [x] `filter_meta` 支持时间/类型/人物/场景/尺寸组合筛选
- [x] `train_category` few-shot 生成自定义类别原型向量
- [x] `image_album_skills.py` 注册全部 7 个技能，每个带 self-gating
- [x] `rapidocr-onnxruntime` 已加入依赖
- [x] `builtins.py::register_all` 注册新技能且返回计数正确
- [x] `register_all` 完整加载不崩、无重复注册
- [x] 全链路验证通过（分类/OCR/重复/模糊/敏感/筛选/训练）