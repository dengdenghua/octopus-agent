---
name: octopus-okf-cross-repo-loop
description: OKF 知识交换在 agent↔storage 两仓已闭环;storage 半边在未合并分支上
metadata: 
  node_type: memory
  type: project
  originSessionId: 1f9d2b5f-f63e-4fc1-8631-547b7fd9611c
---

OKF(Open Knowledge Format)跨仓闭环已端到端打通,**两仓 PR 均已合并入各自 main(2026-06-25)**。两半在不同仓——任一仓单看都只见一半。

- **导出半(octopus-agent)**:`GET /api/wiki/okf-bundle`(`runtime/sensing/gateway/wiki_router.py`)把 wiki 流式成 tar.gz(markdown+frontmatter+index.json+edges)。测试 `tests/test_wiki_qa.py`。随 PR #1(`fix/full-stack-audit-hardening`,20 commit:审计加固+OKF Phase0-3+reranker/graph/ask/export)合入 main @ `882b97a3`。
- **摄入半(octopus-storage)**:`POST /v1/okf/ingest`(`octopus_storage/okf.py` + `app.py`)安全解包→注册成 folder source→索引,使 agent 的 wiki 进 storage 的 `/v1/search`+`/v1/answer`。测试 `tests/test_okf_ingest.py`(含 ingest→auto-index→search 端到端 + 穿越/符号链接/绝对路径/非gzip/上限 拒绝)。PR #1(`feat/okf-ingest`,2 commit)合入 main @ `6850fc5`。

**Why**:gbrain 知识层追平的最后一环;用户「一步到位」要求做完包括跨仓。
**How to apply**:storage 解包是**安全敏感**代码(手写 per-member 校验 + 惰性遍历及早 bail,不用 `extractall`,不依赖 3.12 `tarfile filter`,兼容 3.11)——改动别削弱穿越/链接/tar-bomb 防护。复用了 `_spawn_index_job`(从 create_index_job 抽出,行为不变)。合并法用的是本地 `git branch -f main <feat>` + `git push origin main:main`(不切共享工作树,GitHub 自动标 PR merged)。详见 [[octopus-family-architecture]] 的域分工与 ADR-009。
