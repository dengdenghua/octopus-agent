---
name: octopus-image-upload-router-drop
description: 图片上传全链路通但 openai/gemini 路由翻译层静默丢弃 image_url 块;查法=看 provider payload 不是看装配
metadata: 
  node_type: memory
  type: project
  originSessionId: 149c79d4-2dc0-4586-b126-5aee8ac7e050
  modified: 2026-08-18T14:03:26.641Z
---

2026-08-18:用户报「图片文件上传发送到对话链路有问题」。真根因在**最后一步翻译**,不在上传或装配。

`_messages_to_openai`(runtime/sensing/model_router/openai_router.py)处理 user 角色的块列表时只有
`tool_result` / `text` 两个分支,`image_url` 块**两个都不匹配→静默丢弃**,并把消息压成
joined string。gemini `_split_system_and_contents` 同样漏了分支。**只有 anthropic_router 有
`_normalize_image_block` 做了翻译**,所以默认 anthropic 路线能看图、OpenAI 兼容中转(本机
Kimi/doubao/packyapi 都走这条)全瞎。

诊断链(每步都实证过,别跳):
1. 前端 send 路径**是对的** —— 在 `WebSocket.prototype.send` 上打桩抓 `turn/start`,
   attachments 带齐 `data_url`/`mediaType`/`path`/`artifact_url`。
2. `TurnParams` 校验**不吃** attachments;`_input_attachments` 提取正常。
3. `_assemble_messages` 产出 `['text','image_url']` —— **装配层看起来完全正常,这是最大的迷惑点**。
4. 决定性证据 = 模型自己的 reasoning:「I don't see any image attached to this message」。
   journal 里 `data:image` 有 3 处(说明 data_url 进了后端),但模型看不到。
5. 直接调 `_messages_to_openai` → `[{'role':'user','content':'describe this'}]` 图没了。

**教训:验证多模态要断言 provider payload,不是断言装配结果。**装配层测试全绿也照样瞎。
新加的 6 条路由测试就是钉这一层的。

顺手修的第二个洞:无 `data_url` 时 `_image_blocks_from_attachments` 会把
**server-relative** `artifact_url`(`/api/threads/<id>/artifacts/x.png`)当 image_url 发出去
——任何 provider 都取不到;而 `_attachment_context_appendix` 又因为
`_looks_like_image_attachment` 为真把它跳过 → **两条通道同时丢**。改成:相对路径不发图,
并让它落回 manifest(模型可 read_file)。helper 现在返回 `(blocks, consumed_indices)`。

踩坑:
- **后端不热重载**。跑在 8000 的进程是凌晨启的,live 探针一直在测旧代码(改完仍 NOIMAGE)。
  别据此判断修复失败 —— 改完必须重启 `.venv/bin/python -m runtime serve` 才生效。
  **同一天第二次被这条咬**:`ps` 显示两个 backend 进程(03:15 的和 22:01 的),
  但 `lsof -nP -iTCP:8000 -sTCP:LISTEN` 证明**旧的 03:15 那个仍占着端口**,
  新起的绑不上、白起。所以「看到有新进程」不等于新代码在服务 ——
  判据只能是 lsof 里那个 PID 的 `ps -o lstart` 早于还是晚于你的改动。
- `tests/test_auto_docs_fresh.py::test_generator_output_matches_on_disk` **本来就红**
  (stash 掉改动照样红),别归因给自己。
- Bash 的 cwd 会在 `cd frontend` 后漂移,`runtime/` 路径突然 not found —— 用绝对路径重锚。

门禁:12545 passed / 0 failed(-m "not slow and not integration");ruff + octopus-lint 全绿。
相关 [[octopus-envelope-whitelist-projection-trap.md]](同款「白名单不列名就静默丢」形状)。
