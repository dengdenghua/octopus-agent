---
name: concurrent-agent-repo-workflow
description: "这个仓常有并行 agent 同时改;提交/合并/验证要按这套避坑法,别硬刚"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 900aad5a-9593-4b2a-ac1a-12cea9e9d8da
---

octopus-mobile 仓经常有**另一个 agent/进程并行在改**(整个 2026-07-05 会话如此)。它会:
① 往 HEAD 所在分支提交(我在功能分支上,它的 commit 会插进来);② 重写 main 历史(rebase/reset,
我 committed 的文件一度在工作区被还原成原版);③ 工作区留着**编译不过的在制品**(如 MarketScreen/
SettingsScreen/DiscoverScreen 半成品)。

**避坑法(已验证有效):**
- 提交只 `git add` 我自己的文件,**绝不碰**在制品(MarketScreen/SettingsScreen/DiscoverScreen/ChatScreen/
  proguard/values-*/strings 等)。
- 合并到 main **不要 ff-merge**(历史被重写会分叉),改用 **cherry-pick 我自己的 commit** —— 干净、避开插队的并行 commit。
- 我的 commit 对象即使 HEAD 被切走也**始终可达**(git cat-file/reflog 确认),别慌。
- 要真机验证/构建时,工作区常因并行在制品**编译红**。安全法:`git worktree add --detach <tmp> HEAD` 从
  **已提交状态**构建(keystore 是绝对路径,拷 local.properties 进 worktree 即可签名),完全不碰并行未提交文件;完了 `git worktree remove --force`。

**Why:** 这套坑本会话踩了 3-4 次(ff 失败、文件被还原、build 挂在别人半成品上)。
**How to apply:** 用户偏好「**等并行结束后统一再验证**」——别在 churn 中途强行跑整仓 build/detekt,我的活提交好即可,整体验证留到并行落定。detekt/编译报错先看是不是在制品文件(不是我的就别修、别当自己的锅)。相关技能落地见 [[testing-jvm-stores]]。
