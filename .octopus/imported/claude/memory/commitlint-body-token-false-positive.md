---
name: commitlint-body-token-false-positive
description: "commitlint footer-leading-blank 假失败——正文换行恰好在行首产生 \"word:\" 会被当成 footer token"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 61a315f7-1be7-498c-8157-ea1ae4ec56a9
  modified: 2026-08-16T13:57:13.790Z
---

husky commit-msg 钩子的 commitlint 规则 `footer-leading-blank` 会把正文中任何**行首**形如 `word: value` 的行（如 "free: a downstream..."、"outputs: an unchanged..."）解析成 footer token，报 "footer must have leading blank line" 假失败——即使真正的 Co-Authored-By footer 前有空行（2026-08-16 提交 074d09d3 时连吃三次拒绝才定位）。

**Why:** conventional parser 从第一个 `token: value` 行开始把余下全文当 footer；正文手动 72 列换行很容易把带冒号的词顶到行首。

**How to apply:** 提交前用 `grep -nE '^[A-Za-z][A-Za-z0-9-]*: ' <msgfile>` 自查（排除 Co-Authored-By 行），重排换行避免行首冒号词。写消息用文件 + `git commit -F`，便于 grep。相关：[[octopus-agent-generated-artifact-drift]]。
