---
name: octopus-lsp-integration
description: "lsp_skills.py 早已存在(别另造包);修了4个\"错误伪装成空答案\"的bug;真进程测试是唯一能抓到它们的方式"
metadata: 
  node_type: memory
  type: project
  originSessionId: cd66e82a-76c5-4876-8fd5-b367091f4f61
  modified: 2026-08-12T18:14:27.107Z
---

`runtime/execution/suckers/lsp_skills.py`（986 行，4 个 skill：definition/
references/hover/document_symbols）**早就存在并已注册**在 `builtins.py:693`。
2026-08-13 我没先查就建了平行包 `runtime/execution/lsp/`（7 模块 + 34 测试），
发现后删掉，只把增量移植进 shipped 模块。**动 LSP 前先读这个文件。**

d400f416 修的四个 bug 同一形状 —— **错误伪装成合法的空答案**：

1. `_lsp_references` 只 open 定义文件，pyright 只从已打开文档答引用 →
   `check_path` 报 2 个（真实 51 个）且 `ok: true`。修法 = `_lsp_candidates.py`
   播种（grep 提候选，LSP 定裁决）。
2. `_resolve_server_argv` 认 `sys.executable` 永远可用 → 选中 `python -m pylsp`
   （没装），**并因此遮蔽了后面已装的 pyright**。这台机器上 Python LSP 全黑。
   修法 = 查模块可导入 + 解释器同目录优先于 PATH。
3. read loop 唤醒等待者不留 payload → 服务器死了返回 `{}` = "没找到定义"。
4. `stderr=PIPE` 无人读 → 多话服务器写满缓冲死锁；启动失败只报"连接关闭"
   （rust-analyzer 的 rustup shim 就是这样）。

**教训（同 [[octopus-agent-subagent-model-routing]] 里 stub-runner 那条）**：
原有 24 个测试全用 `_FakeClient`，从没启动过真进程 —— 假客户端返回测试自己
喂的 locations，永远测不出"服务器只答已打开的文档"。`tests/lsp_fake_server.py`
是脚本化真子进程（framing 故意手写，不复用 runtime 的 codec，否则会跟客户端
"就malformed帧达成一致"）。pyright 已声明进 dev extra，否则 e2e 测试自己跳过。

验证 shipped 修复要对 shipped 函数实测，别对自己的新代码；证明测试真能抓 bug
的办法 = 临时把修复关掉看它变红（关播种 → count 1）。

相关：[[octopus-agent-improvement-roadmap]]、[[octopus-audit-false-positives]]
