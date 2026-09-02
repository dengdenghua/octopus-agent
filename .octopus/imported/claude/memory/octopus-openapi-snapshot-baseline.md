---
name: octopus-openapi-snapshot-baseline
description: "openapi-snapshot 是最小 baseline 配置生成的,别拿它跟满配 live 服务器(546路径)比\"漂移\""
metadata: 
  node_type: memory
  type: project
  originSessionId: 1f9d2b5f-f63e-4fc1-8631-547b7fd9611c
---

`docs/openapi-snapshot.json` 由 `tests/test_openapi_snapshot.py` 构建的**最小 baseline app** 生成（~492 路径），**不是** config.local.yaml 满配运行时（546 路径）。差的 ~55 路径是 molili billing / gene-locks / groups / local-partners / admin/reflex 等**配置门控 router**，只在对应 feature 开启时挂载。

**踩坑（2026-06）:** 审计时拿 live 服务器 `/openapi.json`(546) 对比快照(491)，误报"55 端点 drift / 未 snapshot"为 P0。实际用 `OCTOPUS_OPENAPI_WRITE=1 .venv/bin/pytest tests/test_openapi_snapshot.py` 重生成后只动 1 个路径(491→492) —— 真实漂移极小。

**How to apply:**
- 判断快照是否 stale，要用 `test_openapi_snapshot.py` 同一 baseline 重生成后比 diff，**不要**比 live 服务器路径数
- `make openapi-snapshot` 的 target 是裸 `pytest`，非交互 shell 没激活 venv 会 `command not found`；用 `.venv/bin/pytest`
- 重生成产生大 diff 多为序列化 churn（openapi-types 版本漂移），提交前确认是真内容变更 —— 见 [[octopus-agent-generated-artifact-drift]]

相关：[[octopus-agent-audit-verification-lesson]]（又一次：审计结论先实证再定级）。
