---
name: octopus-agent-evaluation-2026-07
description: 2026-07-03 深度评价(7.0/B)+当轮落地的5项优化+并发会话撞车雷区
metadata: 
  node_type: memory
  type: project
  originSessionId: b9820fd8-54c8-415e-8115-6e85c9e70204
---

2026-07-03 对 octopus-agent 做了一次 61 代理、对抗核查的深度成熟度评价，总分 **7.0/B**。核查真的推翻了初判(印证 [[octopus-agent-audit-verification-lesson]]):子代理曾称沙箱逃逸"仅程序化可达"→实为**已鉴权 /v1/chat/completions 可达**;称可选依赖技能"调用时报错"→实为**依赖缺失即消失**;guard 数 37 非~30;前端 tsc-clean 仅靠排除 129 测试文件。规模:~289K 行 Python(860 文件)、730 前端、8483 测试、main 领先 origin **108 未推**。

**当轮落地的 5 项优化(在 main 工作树,未提交未推)**:
1. `kimi_swarm_load_test.py:14` 改从 `platform.models.llm` 导入 Message/ModelRequest → 消除 safety→sensing 逆向边(Message/ModelRequest 真正定义就在 platform.models.llm,sensing 只 re-export)。
2. 重生成 `docs/openapi-snapshot.json`(492→616 路径)+ 前端 openapi-types.ts → drift 测试转绿。用 `OCTOPUS_OPENAPI_WRITE=1 .venv/bin/python -m pytest tests/test_openapi_snapshot.py`(记忆:make 用裸 pytest 要换 .venv)。
3. `memory/threads/store.py` `_append_record` 加 flock+fsync(照抄 `JSONLJournal.write` 模式),is_new 判定移到锁内。6 进程×300×8KB 并发 smoke PASS。
4. `execution/suckers/write_skills.py` 加 `_scrub_unconfined_env`:无沙箱 exec(sandbox_dir=None)剔除敏感环境变量(键名启发式+复用 `platform.observability.redactor.Redactor` 值检测),接进 `_exec_shell`+`_background_exec`。端到端实证密钥不再泄漏、PATH 保留。**这是沙箱逃逸的缓解(密钥泄漏这半);完整修复(网关绑受限 session)见 spawned task,因撞车延后**。
5. 结构化日志接线:`logging_config.py` `OCTOPUS_LOG_FORMAT=json` 装 StructuredFormatter(默认纯文本不变);`cli_serve.py` run_serve 加"非 loopback 绑定+鉴权关→⚠警告"。

**并发会话撞车雷区(重要)**:2026-07-03 本轮进行时,**另一个会话/用户同时在改** `sensing/gateway/openai_gateway_router.py`(chat_completions,hunk @306-331)、`config_router.py`、`platform/ui/app.py`、`tests/test_app_config_endpoints.py` 及多个前端文件(welcome/sidebar 实时增长)。因此沙箱完整修复(要改 chat_completions)被判定撞车而延后。教训延续 [[octopus-agent-generated-artifact-drift]]:只按显式路径提交自己的文件,绝不 git add -A。`logging_config.py` 是仓库唯一 CRLF 文件,别去动行尾(会造 82 行假 diff)。

剩余未做的评价建议:P1 ruff 全量 format(675/860 漂移,记忆警告别全量);P1 k8s 探针改指 /readyz;P2 CONTRIBUTING 死导航表(12/18)、CODE_WIKI.md 已删仍被 CLAUDE.md 引用、59 死链;P2 react_loop ~2788 行单函数抽取;P2 删死脚手架(DataMigrator/conflict_resolution/空 company)。详见 [[octopus-agent-evaluation-2026-06]] 与 [[octopus-agent-improvement-roadmap]]。
