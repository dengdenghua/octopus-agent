---
name: octopus-mobile-security-audit
description: octopus-mobile 41-agent 安全审计已修复大部分问题，但审计日志防篡改与弱密码备份 keystore 仍是未闭环的安全债
metadata: 
  node_type: memory
  type: project
  originSessionId: 66726182-1abe-4233-b042-dcefc473e4bd
---

octopus-mobile 近期做过一次大规模安全审计（AUDIT_REPORT.md/AUDIT_FIXES.md 记录，41-agent 深度审计），修复了悬空 tool_call 崩溃恢复、并发重复执行、审计日志脱敏缺失、evaluateJs 恒失效、SPS 解析越界等历史缺陷，590 个 Kotlin 单测全绿，CI（ci.yml + codeql.yml）配置健全。

**仍未闭环的安全债**：
1. **审计日志防篡改不完善**：HMAC 密钥与日志同存本地 KVUtils，逐行签名非链式，本地攻击者可重算签名或删行且难以检测。最新提交（`28e459c`/`94f924c`）在尝试补哈希链，是持续演进中的弱点，尚未真正做到外部不可变存储或链式签名。
2. **弱密码备份 keystore 仍在仓库里**：`release-old-weakpass-backup.keystore`（旧签名库）与新 `release.keystore` 同时存在于仓库中（另见 [[octopus-ecosystem-and-os-fork]] 2026-06-13 轮换记录）。
3. **`isRemoteHighRiskAllowed`** 是有意保留的高风险 opt-in 设计（远程高危工具免确认，如短信/文件/装应用可无人工确认执行），一旦运营侧误开启会扩大信任边界。
4. **测试覆盖不对称**：Kotlin 单测成熟（590用例），但 androidTest 插桩测试几乎空白（仅1文件），Python server 测试薄弱（仅1个文件、112/116通过，4个失败因本地未配 agnes provider）。

**Why**：这是一个通过无障碍服务控制手机的高权限 Agent 应用，审计链路完整性直接决定出问题后能否溯源、能否证明"未被篡改"。
**How to apply**：后续如果要碰 mobile 的安全/合规相关代码，先确认这几项是否已经推进，避免重复审计或误判为"已解决"。
