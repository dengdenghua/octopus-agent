# 商业多租户安全整改 Spec

状态：Phase 0-A 已实施；Phase 1 共享存储收口进行中；Phase 2 执行隔离开始收口；商业多租户上线仍阻断

版本：v1.6

适用范围：`octopus-agent` 服务端、WebSocket 控制面、插件/MCP/浏览器/设备执行面、持久化状态和 Kubernetes/Docker 部署模板。

## 1. 目标

将当前“单用户本机应用优先”的安全模型，升级为能够支撑闭源商业产品的安全基线：

1. 非 loopback 部署必须认证且默认拒绝不安全启动。
2. 身份、租户和资源所有权成为所有数据面与执行面的强制上下文。
3. 普通用户不能触达宿主机命令、插件加载、远程代理、浏览器接管、设备控制等高权限能力。
4. 不同租户之间不得读取、修改或删除文件、线程、Memory、Project、Workspace、Trace、Cookie、凭证和账单数据。
5. 关键安全策略必须在服务层/存储层执行，不能只依赖手写 URL 前缀或前端隐藏按钮。
6. 部署、升级、回滚和审计能够被运营团队验证和追踪。

## 2. 非目标

本 Spec 不要求本阶段重写 Cerebrum、Ganglia、Arms、Suckers、Beak 的业务编排逻辑，也不改变本地单用户桌面模式的产品体验。单用户模式可以保留宽松权限，但必须与 server/shared 模式有明确、可验证的边界。

## 3. 威胁模型

| 主体 | 能力 | 必须防止的结果 |
|---|---|---|
| 匿名网络请求 | 访问公开 HTTP/WS 入口 | 触达控制面、文件面或执行面 |
| 普通租户用户 | 合法登录、可创建业务资源 | 横向读取/修改其他租户资源 |
| 恶意插件/MCP server | 运行在服务进程或子进程边界内 | 读取其他租户数据、窃取凭证、逃逸执行边界 |
| 被入侵的浏览器/设备 | 持有 session/profile/device 标识 | 接管其他用户控制会话或设备 |
| 恶意远程地址 | 被用户配置为 HTTP/WS/MCP/OAuth 目标 | SSRF、DNS rebinding、内网和 metadata 读取 |
| 被污染的升级包/镜像 | 进入部署供应链 | 供应链持久化执行或回滚到已知漏洞版本 |

## 4. 目标安全模型

所有请求进入服务后必须形成统一 Principal：

```text
CurrentPrincipal {
  tenant_id: str
  actor_id: str
  roles: set[str]
  scopes: set[str]
  authn_method: str
  request_id: str
}
```

身份只能来自经过验证的 JWT/API key/企业 SSO。`user_id`、`owner_id`、`roles`、`holder_id` 等请求字段不能改变 Principal，也不能作为授权依据。

所有持久化资源至少包含：

```text
tenant_id
owner_id / created_by
created_at / updated_at
resource_acl 或可计算的 membership
```

授权采用默认拒绝：

```text
authenticate → resolve tenant → load resource → authorize action → execute
```

## 5. 风险分级与执行阶段

### Phase 0：上线阻断项

- 非 loopback 且未启用认证时拒绝启动。
- `/media`、`/api/agent-trace`、`/api/capabilities/enable` 等入口强制认证。
- MCP、Reflex exec、PluginHub、Remote Backend、Browser、Android/Tentacle 等执行面默认关闭或仅允许 admin/operator。
- 所有出站 URL 统一经过 SSRF Guard。
- 高危接口需要可观测的 operator 审计事件。

### Phase 1：多租户资源隔离

- 引入 `CurrentPrincipal` 和统一 authorization service。
- Thread、Project、Memory、Workspace、FS、Browser、Device、Trace、Journal、Usage 增加 tenant/owner scope。
- 禁止从 query/body/header 读取授权身份。
- 为所有资源操作增加 Alice/Bob/Admin 三方回归测试。

### Phase 2：执行隔离与供应链

- Shell、MCP、Plugin、Browser、Device 使用独立 worker/sandbox 和最小权限凭证。
- Plugin/MCP 包必须签名、版本固定、来源可验证。
- 镜像使用 immutable digest，发布 SBOM、签名和 provenance。
- OAuth token 加密存储，禁止长期 token 放入 query string。

### Phase 3：商业运营能力

- 按 tenant 计费、限流、并发、存储和模型预算。
- 统一审计、告警、撤销、密钥轮换和租户删除流程。
- 水平扩展时，Session、Lease、Registry、Approval、Quota 和 Job 状态必须使用共享持久化。

## 6. 本次实施范围：Phase 0-A

本轮先落地低侵入、可回滚的阻断措施：

1. 非 loopback 无认证启动直接失败。
2. Media router 使用同一认证依赖。
3. Agent Trace router 使用统一 router-level 认证依赖。
4. Runtime capability hot-load 使用认证依赖。
5. 增加针对上述入口的认证回归测试/静态验证。

暂不在本轮直接重写资源存储 schema；该部分必须在 Phase 1 先完成 Principal/tenant 设计后执行。

## 7. 验收标准

### 启动安全

- `host=0.0.0.0` 且 `oct.enabled=false`、`local_auth.enabled=false` 时启动失败。
- loopback 单用户模式保持可用。
- 认证开启时无凭证访问受保护路由返回 401。

### 路由安全

- 无凭证访问 `/media/video/index` 返回 401。
- 无凭证访问 `/api/agent-trace/stats` 返回 401。
- 无凭证访问 `/api/capabilities/enable` 返回 401。
- 认证成功只能证明身份，不能自动获得 admin/operator 权限。

### 回归安全

- 不改变现有合法认证请求的响应契约。
- 不删除、不覆盖用户未提交修改。
- 仅修改本 Spec 明确的文件和测试。
- 所有新增测试在依赖完整的环境中通过。

## 8. 回滚策略

Phase 0 的每个变更必须独立可回滚。认证 fail-closed 若阻断已有本地部署，运营方只能显式启用 local_auth 或绑定 loopback，不允许通过重新放宽默认安全策略绕过。

## 8.1 Phase 0-A 实施记录

已完成：

1. `serve` 在构建运行时前拒绝非 loopback 且未启用认证的绑定；Unix domain socket 和 loopback 本地模式保持可用。
2. `/media` 全路由启用统一认证依赖。
3. `/api/agent-trace` 全路由启用统一认证依赖。
4. `/api/capabilities/enable` 启用认证依赖。
5. 认证开关打开但 identity store 缺失时，以上入口 fail-closed 返回 401。
6. 新增 Phase 0-A 回归测试；完整执行需安装项目测试依赖。

未在本阶段实施：资源 tenant/owner 隔离、SSRF Guard、执行沙箱和供应链治理；这些仍是商业上线前的阻断项。

## 8.2 Phase 1 基础授权层实施记录

已开始：

1. 新增 `CurrentPrincipal`，从已验证身份生成 `tenant_id`、`actor_id`、角色、scope、认证方式和 request id。
2. JWT 角色授权不接受未在 identity store 中登记的 subject，避免仅凭 token claims 获得 operator 权限。
3. MCP 的配置、信任、OAuth 授权/撤销要求 `operator` 或 `admin`。
4. PluginHub 的加载、启动、停止、卸载和配置修改要求 `operator` 或 `admin`。
5. Capability hot-load 与 Reflex 管理面要求 `operator` 或 `admin`。

尚未完成：Principal 注入到全部业务资源、tenant-aware Store 迁移、owner/member 授权和跨租户回归矩阵。

本轮已补齐并验证静态契约：

1. Workspace ACL：创建者、成员、owner/editor/viewer、lease holder 均与 Principal 绑定；非成员隐藏资源存在性。
2. Thread：创建和更新强制覆盖 owner metadata；上传、FS local scope 对无 owner 的 legacy thread fail-closed。
3. Project OS：文档记录 `owner_id`/`tenant_id`，读写、timeline、report、intervene、delete 等路径做 owner/tenant 授权；legacy project 对普通用户不可见。
4. FS local：认证模式下 `/roots`、目录选择、目录导入、tree/read/write/revert、Git status 必须绑定拥有者 thread workspace；路径同时受 `OCTOPUS_FS_ALLOWED_ROOTS` 限制；目录导入默认 100 MB/1000 文件上限，可通过显式环境变量收紧。
5. FS remote：workspace membership、写权限和 lease holder 使用已验证 Principal；query/header/body 中的 `user_id`/`holder_id` 不能冒充身份。
6. Remote Backend：配置、健康检查、proxy、realtime WS 收敛到 operator/admin；JWT subject 必须是 identity store 已登记身份；配置登记只做语法校验，实际出站通过 pinned-IP SSRF/DNS guard。
7. Browser：session/profile、截图、action log、replay、close/reset 绑定 owner；relay 状态绑定首个 authenticated owner；全局 Browser config、无 owner legacy artifact 仅 operator/admin 可操作/读取。
8. Media：认证请求的媒体根目录、图片/视频路径、封面、watcher 和视频索引库已按 tenant/owner 隔离；共享 allowlist 只对显式 operator/admin 生效，普通用户不能借此读取共享根。仍未完成视频/PDF/模型任务 quota、任务撤销和跨租户管理员审计闭环。
9. Upload：文件名、单文件大小、文件数量和 thread owner/tenant 已有边界；legacy thread 无法归属时拒绝访问；上传认证改用统一 Principal，不再直接依赖旧 actor helper。
10. Computer、Terminal shell、Android device control：认证模式下统一要求 `operator/admin`；Terminal 仍保留 session owner 检查，Computer 保留 preview/lease，Android 保留 preview token。

以上是“边界收口”而不是“多租户完成”。Principal 已进入若干高风险入口，但旧 `_resolve_actor` 和 actor-agnostic router 仍存在，不能把全项目视为统一授权。

### 8.3 本轮 FS / 高风险入口契约

| 入口 | 单用户开发模式 | 认证/共享模式 | 当前结论 |
|---|---|---|---|
| `/api/fs/roots` | 返回配置允许根 | 必须带 owner thread，只返回该 thread 的允许根 | 已收口 |
| `/api/fs/pick-directory` | 本机目录选择 | 必须带 owner thread，选择结果不得越界 | 已收口 |
| `/api/fs/import-directory` | 写入本地 data import 目录 | 写入 thread workspace 的 `.octopus/imports`，有 quota | 已收口 |
| `/api/git/status` | 仅配置允许根 | 必须在 owner thread scope 内 | 已收口 |
| Remote Backend | 本地兼容 | operator/admin + URL guard | 已收口为控制面 |
| Browser session/relay | 本机共享状态 | owner/session/relay 绑定 | 部分完成 |
| Media | 本地兼容 | tenant/owner 媒体根 + 索引库；共享 allowlist 仅 operator/admin | 路径与 watcher 已收口，quota/任务治理未完成 |
| Memory | 本地兼容 | tenant/owner 哈希目录 | 需补齐后台 scope 与旧文件迁移 |
| Agent Trace | 本地兼容 | tenant/owner scope；legacy 仅控制面 | 已完成第一版 store scope，需补齐后台传播 |

### 8.4 当前商业上线阻断项

以下项目不能以“已加认证”替代，必须在商业多租户 GA 前完成：

1. 将 Memory、Journal、Usage、Trace、Browser artifact、媒体索引等共享文件/SQLite 数据迁移到带 `tenant_id` 的持久化模型，并在 Store 层强制带 scope 参数；Memory、Journal、Usage、Trace、Browser artifact、媒体索引、Experience/Review/Proposal、Project、Workspace、Lease 已完成第一阶段 Store 过滤与默认分区，但历史迁移、删除恢复和所有后台调用仍未全部完成。
2. 统一替换剩余旧 `_resolve_actor` 调用，禁止 router 自己解释 `user_id`、`owner_id`、`roles`、`holder_id`。
3. 为 Project、Thread、Workspace、Upload、Browser、Backend 增加数据库级唯一约束、迁移、删除和租户级备份/恢复策略；Project/Workspace/Lease 已增加 Store 级 scope，Thread/Upload/Backend/Browser 仍有 JSON/旧 store 或控制面迁移工作。
4. 完成所有出站 HTTP/WS/MCP/OAuth/remote backend 的统一 SSRF guard、DNS rebinding 防护、重定向复核和凭证不进 query 的实现；本轮已收口 Remote Backend、MCP OAuth discovery/token/DCR，并将默认 `fetch_url`/Crawler HTTP GET 切换到 pinned-IP helper；企业资产、模型/embedding、渠道 webhook、Browser Playwright 导航及其他 adapter 仍待逐项迁移。
5. Shell、MCP、Plugin、Browser、Device 执行面完成 worker/sandbox、最小权限凭证、审计和撤销；本轮已将主应用 Evolution 控制面收口为 operator/admin，并将 MCP 配置、运行时客户端、Skill 可见性、Trust、OAuth token/pending 按 tenant 分区；高风险 Shell/Git/质量检查在显式 commercial/shared 模式下已改为硬 sandbox fail-closed，但 MCP stdio 仍因缺少 worker launcher 被拒绝，PluginHub 主进程加载也被拒绝；基础 SkillRegistry 仍是共享进程内对象，Browser/Device worker、撤销和审计尚未完成，operator 角色不等于宿主机 root。
6. 增加上传/视频/PDF/模型任务的 tenant quota、并发限制、超时和后台任务清理；当前 quota 仍以单进程环境变量为主。
7. 完成 Kubernetes/Docker 的 immutable image digest、SBOM、签名、升级回滚和多副本共享状态治理。
8. 补齐 Alice/Bob/Admin 三方端到端矩阵，并在 CI 中对受保护路由做“无 Principal / 错租户 / legacy 资源 / 越权角色 / path traversal / SSRF”自动扫描；当前已补 Workspace/Thread/Upload/Project 的部分 Alice/Bob/legacy 回归，尚未覆盖全路由。

### 8.5 验证限制

本工作区已使用项目 `.venv` 执行受影响运行时测试。本轮已完成：

- 受影响 Python 模块 `py_compile`；
- `git diff --check`；
- 路由、Principal、owner/tenant、路径和角色门禁的静态差异审计。
- Experience/Review/Proposal 租户隔离、legacy 隐藏、Admin cross-tenant 与错误租户变更回归；
- Media 路径穿越、共享 allowlist、视频索引库分区和 watcher 分区回归；
- Realtime WebSocket actor → tenant scope → Trace/Proposal 后台写入传播回归。

依赖完整的 CI 环境必须重新执行新增及既有回归测试，尤其是 WebSocket、multipart upload、remote backend SSRF 和 Browser owner 隔离场景。

## 8.6 本轮共享存储与统一 Principal 实施记录

已完成：

1. 新增 `TenantScope` 与 scope helper。存储层不读取 query/body/header 中的身份字段；HTTP 路由只能使用已解析的 `CurrentPrincipal` 生成 scope。
2. Agent Trace SQLite 的 `messages`、`agui_events`、`approvals`、`agent_checkpoints`、`llm_token_usage`、`resume_requests` 增加 `tenant_id` 与 `owner_actor_id`，启动时对旧库执行幂等列迁移并建立 scope index。
3. Trace Store 的写入 API 支持 `scope`，查询、聚合、task run、checkpoint、resume 和 replay 路径支持 scope；普通租户 scope 不可见空 scope 的 legacy rows，cross-tenant 只允许显式 operator/admin 控制面。
4. Journal event envelope 增加 `tenant_id` 与 `owner_actor_id`。`journal_context` 支持租户上下文，JSONL/内存 Journal 读取按 scope 过滤，Trace mirror 复用同一 ownership metadata。
5. `/api/account/usage`、summary、events、billing 查询接入 identity store 与 Journal scope；认证用户只能看到自己的用量，不再把共享 journal 直接汇总成 `local` 账户。
6. Journal SQLite query index 增加租户列、迁移和 scope index；`/api/journal/events` 与 stats 复用 Principal scope，旧未归属事件对普通认证用户不可见。
7. 统一旧 `_resolve_actor` 的 JWT 默认行为为不信任 token subject 直接合成身份；其兼容返回值仍为 actor，但底层解析通过 `resolve_principal`，已登记身份才可通过。
8. Browser screenshot artifact 在有租户上下文时按 tenant/owner 哈希目录保存；普通用户只在自己的目录查找，迁移前全局 legacy artifact 继续只向 operator/admin 开放。Android device WebSocket 也改为登记身份校验，不再信任 JWT claims。
9. ProjectStore、WorkspaceStore、LeaseStore 增加可复用的 scoped view；Project 的 project/milestone/task/event/thread binding、Workspace ACL 和文件 lease 的读写在 Store 层执行 tenant 校验，后台 ProjectEngine 继承同一 scope。
10. 主应用 Evolution 控制面将 `/api/evolution/*` 收敛到 operator/admin；Remote Backend 与 MCP OAuth discovery/token/DCR 使用统一 pinned-IP 出站 guard，禁止私网目标和未复核重定向。
11. MCP 配置状态、运行时客户端和工具名按 tenant 维度管理；MCP Skill 在带 tenant 的 Session/Journal context 下只对所属 tenant 可见，TrustStore 与 OAuthStore 使用 tenant 哈希分区，OAuth callback state 绑定对应分区；同名 server 在不同 tenant 可独立批准、授权和启停。
12. 默认 `fetch_url` 和 Crawler 的 HTTP GET/robots 请求通过 pinned-IP HTTP helper；保留注入 client 的测试/专用 transport seam。
13. 旧的 legacy MCP Trust/OAuth 文件不会自动复制到任意 tenant；迁移时必须由对应 tenant 的 operator 重新批准/授权，避免把单用户凭证扩大成跨租户凭证。

仍未完成：

1. Memory API、OpenAI chat 自动记忆读写和 MemoryHub 已按 tenant/owner 哈希目录/上下文隔离，认证普通用户可以使用自己的 Memory；旧全局 Memory 与未带 scope 的后台学习/检索调用仍属于 legacy 迁移面，不能作为跨租户共享数据读取。
2. Video index SQLite、Media 目录、Experience/Review/Proposal 学习存储已完成第一阶段 tenant-aware 过滤和默认路径分区；Project、Workspace、Lease 已下沉 Store scope，Thread/Upload 仍需完成旧文件迁移、跨副本一致性、quota 和删除/恢复。
3. Agent Trace 的 HTTP 与 Realtime turn 写入已显式传播 tenant scope；其他后台 worker/session 创建处仍需逐项审计，Project/Workspace worker 已补 scope，未归属的历史/后台记录必须继续按 legacy 规则处理。
4. 数据库唯一约束、租户删除/备份恢复、后台任务配额、高权限 worker/sandbox、剩余出站 adapter 迁移、共享 SkillRegistry 的独立 worker/持久化拆分和供应链治理仍是商业 GA 阻断项。

本轮新增回归覆盖：Project Store Alice/Bob/legacy 过滤、Workspace/Lease Store scope、Lease 同文件跨租户冲突查询、MCP Skill/Trust/OAuth tenant partition、Remote Backend/MCP OAuth URL guard、Evolution control-plane auth；并使用项目 `.venv` 实际运行受影响测试。

## 8.7 Phase 2 执行隔离收口记录

已完成：

1. 增加显式 `OCTOPUS_DEPLOYMENT_MODE` 解析。`commercial`、`production`、`shared`、`server` 被视为共享部署；未显式启用时保留本地开发兼容行为，不能据此宣称商业安全。
2. Shell、background exec、IPython、Git（含网络 Git/gh）、质量检查和 verify 调用统一声明高风险执行；共享部署中缺少 `sandbox_dir` 直接返回 `sandbox_violation`，不会退回裸 `subprocess`。
3. 共享部署中的 process sandbox 自动强制 `strict`；显式 `soft`/`direct`/`auto` 不能降级。没有 bwrap/Seatbelt 等硬后端时拒绝执行，并保留 execution policy 证据。
4. MCP stdio 已增加 hard launcher seam：共享部署必须提供 operator 选择的 `sandbox_dir`，客户端会在交给 MCP SDK 前把 command/args/env/cwd 转换为 bwrap/Seatbelt 包装命令；没有 workspace 或硬后端时拒绝创建。远程 HTTP/SSE MCP 不因该门禁自动获得执行隔离结论。
5. PluginHub 在共享部署中拒绝把第三方 Python 导入 API 主进程。插件发现仍可读取 manifest，但加载/生命周期必须等隔离 worker runtime 完成后恢复。
6. 新增 `execution.deployment_mode` 与 `execution.process_sandbox` 配置；`serve` 启动前校验配置/环境一致性并探测硬后端，商业模式显式 soft/direct/off 或缺少硬后端时拒绝启动。

专项验证：config/serve、sandbox/streaming/write-skills/verify/LSP/MCP/PluginHub 及相关租户测试共 246 passed、1 skipped；本轮未修改或暂存用户其他工作区文件。

仍未完成：

1. 将 MCP stdio launcher 从“同进程 SDK 包装”继续拆为独立 worker，补齐租户绑定凭证、资源限制、取消和审计；当前 command wrapping 已阻断宿主机路径旁路，但仍共享主进程生命周期。
2. 实现 Plugin worker/签名包/版本固定/能力代理；当前共享模式是拒绝，不是插件 GA 实现。
3. LSP 已在共享模式下接入硬 sandbox 选择并在无硬后端时拒绝启动；Browser、Android/Tentacle、媒体/PDF/模型任务及其他直接 subprocess/Playwright 通道仍需逐项接入同一 worker/sandbox 契约。
4. 将 shared/commercial 模式接入 Docker/Kubernetes/systemd 的正式部署模板和启动自检，当前 Python 配置层已完成，部署模板仍需同步；同时补充跨进程撤销、配额与审计落盘。

## 9. 后续设计任务

1. `CurrentPrincipal` 实现和依赖注入。
2. tenant-aware Store 接口和数据库迁移。
3. 统一 `authorize(resource, action, principal)` 服务。
4. SSRF Guard 统一库，并清点所有直连 HTTP client；已有 `check_url` 但没有 pinned-IP 请求的调用不能视为完成。
5. Admin/operator scope 与二次审批协议。
6. Browser/MCP/Plugin/Device 的 lease 和 ownership 设计。
7. 多租户安全测试矩阵和路由清单 CI。
