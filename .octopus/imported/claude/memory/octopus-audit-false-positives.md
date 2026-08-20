---
name: octopus-audit-false-positives
description: "全栈审计里被子代理误报、经实证驳回的\"P0\" —— 别再当漏洞修"
metadata: 
  node_type: memory
  type: project
  originSessionId: 1f9d2b5f-f63e-4fc1-8631-547b7fd9611c
---

2026-06 全栈审计（789 finding），逐条追链路后确认的**假阳性**，勿重复上报/修复：

- **container_sandbox.py:136 "shell injection"** — 假阳性。`docker exec ... sh -c command` 运行任意命令**正是 sandbox 的功能**；代码显式拒绝 host fallback（120-132、154-161 行），`write_file` 还转义引号。威胁模型是"别在宿主执行"，已强制。
- **reflex_admin_router.py:1725/1879 "unsafe YAML"** — 假阳性。用的是 `ruamel.yaml.YAML(typ="rt")` 往返模式，默认安全，不构造任意 Python 对象（实测 PyYAML 风格 payload → ConstructorError BLOCKED）。:1647 用 `safe_load`。
- **kuzu_kg.py:196 "SQL 注入 LIMIT"** — 降级（非 P0）。`limit: int` 类型，pattern 已参数化（$sp/$pp/$op）。最多 `int(limit)` 防御。
- **audit_chain.py:306 "payload 未深拷贝/MAC 变异"** — 假阳性。`body` 引用 payload 后立即 `canonical_bytes()` 序列化，中间无变异；深拷贝不改规范序列化结果。
- **executor.py:181 "registry.get() None 解引用"** — 假阳性。`get()` 抛 `SkillNotFound` 从不返回 None（suckers/registry.py:130）；子代理按 dict.get 误读。
- **pause_control.py:288 "recovery 丢 pause 状态"** — 非 bug。`resumed`/无事件都穿透到 `_pending`，仅 `paused` 特判恢复 —— 自洽设计（重启后 in-flight 任务挂 pending 待审）。改 `continue` 是产品决策。
- **react_loop.py:1431 "steps 空时跳过 message 重建"** — 假阳性。messages 已从 `messages_snapshot` 独立恢复；step-rehydrate 是附加路径，steps 空时无可重建。
- **第二轮核心逻辑批次 4/4 全非 bug** —— 干净真 bug 已挖尽，剩余 high findings 多为假阳性/设计内，别再盲目逐条修核心逻辑。

**真实但更大/模糊（第二轮已全部啃完，带回归测试）:**
- **etcd_coordinator.py:178** `expires_at=now` —— 验证为**低危非 bug**：唯一调用方 `Hearts.is_leader()` 只读 holder_id 不读 expires_at。已加解释性注释防未来误改。
- **ws_server.py:343** 配对码无限流 —— 已加 per-IP 滑窗失败限流（`_hello_rate_limited`，5次/60s 窗口，超限 1008 "rate limited"）+ 4 个回归测试（test_tentacle_ws_auth.py）。
- **terminal_router.py:55** session 无界增长 —— 已加 `reap_sessions(exclude_id)` 惰性回收（死会话/idle>30min/硬上限 64，每次新连接调用，保留断线重连）+ `last_activity` 跟踪 + 4 个回归测试（test_terminal_reaper.py）。
- **SSE proxy headers** —— observability 3 端点（/api/stream /api/preview/stream /api/files/stream）已有 heartbeat，补 `_SSE_HEADERS`（Cache-Control/Connection/X-Accel-Buffering）。**未做全量 EventSourceResponse 重写**（需重写每个 generator yield 格式，跨端点易碎）。

**本会话已修并加回归测试:**
- S1 observability SSE 无鉴权 → 接 `require_auth`（router 级 dep，仿 browser_router，dev 下 no-op）· test_audit_authz_fixes.py
- S3 anthropic_compat 4 个 session 端点无所有权校验 → `_owned_or_404` 比对 creator_actor（404 防探测）· test_audit_authz_fixes.py
- S8 molili proxy 鉴权头错 → `Authorization:Bearer{user_id}` 改 `Token:{molili_token}`，对齐 client.py
- **channel edit() 参数顺序**：feishu/matrix/mattermost 签名倒置 `(original_message_id, msg)`，但 base.py 契约 + manager.py:169 positional 调用 + 多数 channel + WeCom 测试都是 `(msg, original_message_id)` → 经 manager 调用必崩。已 swap 3 签名 + 改 matrix/mattermost 测试 + 补 feishu 回归（test_feishu.py TestEdit）。**真 bug，子代理这条对了。**

教训见 [[octopus-agent-audit-verification-lesson]]；S11 快照见 [[octopus-openapi-snapshot-baseline]]。
