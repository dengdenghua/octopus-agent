---
name: documents
description: 创建、提取、转换 .docx Word 文档。可用于从结构化内容生成 docx、提取 docx 全文与表格、转 Markdown、查看文档元信息。纯本地处理,无外部服务依赖。
---

# Documents 技能(创建 • 提取 • 转换 • 检查)

处理 `.docx`(Word)文档的本地工具集,基于 python-docx 实现。
**所有操作都在本地完成,不依赖任何外部 API 或授权。**

## 工具清单

| 工具 | 作用 |
|---|---|
| `documents.create_docx` | 从结构化内容创建 .docx(标题/段落/列表/表格) |
| `documents.extract_text` | 提取 .docx 的结构化文本(段落+样式层级+表格+图片数) |
| `documents.to_markdown` | 把 .docx 转换为 Markdown(标题/列表/表格保留) |
| `documents.docx_info` | 文档元信息统计(段落/表格/图片/节/核心样式/大小) |

## 用法约定

### 创建文档 `documents.create_docx`

参数:
- `path`(必填):输出 .docx 路径
- `title`(可选):文档大标题
- `sections`(必填):结构化内容数组,每项是:
  - `{"type":"heading","text":"...","level":1-6}` — 标题
  - `{"type":"paragraph","text":"..."}` — 段落
  - `{"type":"list","items":["..."],"ordered":false}` — 列表(ordered=true 为有序)
  - `{"type":"table","headers":["列1"],"rows":[["单元格"]]}` — 表格(自动网格线)
- `overwrite`(可选):目标文件已存在时必须显式 `true` 才覆盖,**默认拒绝**

### 提取 `documents.extract_text(path)`

返回段落列表(带 Word 样式名与标题层级)、表格数据(最多前 50 行)、图片数量。
超大文档自动截断并标记 `truncated`。

### 转换 `documents.to_markdown(path)`

返回 Markdown 文本:Heading 1-6 → `#`~`######`,列表 → `-`/`1.`,表格 → Markdown 表格。

### 检查 `documents.docx_info(path)`

返回段落数、表格数(含行列)、图片数、节数、核心样式、文件大小。

## 边界

- 仅支持 `.docx`(不支持旧版 `.doc`);文件不存在返回干净错误。
- 写操作(`create_docx` 覆盖)有安全门:必须显式 `overwrite=true`。
- 不读取/不修改文档的修订痕迹与评论(只读提取时忽略;创建时自然无)。
- 此插件为独立自研实现,与 OpenAI 无关联,不包含 OpenAI 代码。
