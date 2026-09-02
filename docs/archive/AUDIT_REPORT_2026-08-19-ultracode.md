# octopus-agent UltraCode 深度审计报告

- 日期: 2026-08-19
- 审计模式: UltraCode / audit.ultracode —— 多路并行调查 + 全量动态验证 + 逐行源码复核 + 与上次报告交叉核对
- 范围: runtime(1294 py 文件/~39 万行) + tests(874 文件/~26 万行) + frontend(1007 ts/tsx)
- 性质: 只读审计, 未修改任何代码

## 验证基线(本次实测)

| 门禁 | 结果 |
|------|------|
| 全量 pytest | **12601 passed, 1 failed(文档漂移), 48 skipped, 5 xfailed**(672s) |
| ruff | **24 errors**(3 个 runtime 实题, 2 个 tests F821 运行时无碍, 余为风格) |
| mypy ratchet | **1 个新错误**(evolution_ops_router.py union-attr)→ 门禁红灯 |
| bandit(runtime) | 406 发现: **1 HIGH + 3 MEDIUM 实质**, 余为 LOW 惯例项 |
| pip-audit(Python) | **0 已知漏洞** ✅ |
| pnpm audit(前端) | **78 漏洞: 1 critical + 29 high + 38 moderate + 10 low** ⚠️ |
| 前端 tsc typecheck | 通过 ✅ |
| 前端 eslint | 0 errors, **45 warnings** |
| 前端 vite build | 通过(13.7s) ✅ |
| 上次提交回归测试(31b6a011) | 40 passed ✅ |

---

## P0 — Critical(必须尽快处理)

### C1. Tentacle Dashboard 默认无认证 + 局域网裸奔(上次未修)
- 证据: `runtime/tentacle/dashboard.py:49` `require_auth: bool = False` 默认关闭; `coordinator.py:173` `create_tentacle_router(self)` 未传 `require_auth=True`; `coordinator.py:103` 默认绑定 **0.0.0.0:8765**(LAN bind)。
- 影响: 局域网内任何设备可访问设备列表/任务提交/截图/VLM 分析/远程输入/WebSocket 屏幕流, 等于把设备控制权拱手让人。
- 修复: `create_tentacle_router` 默认 `require_auth=True`; 生产强制要求身份存储; 评估默认绑定 loopback。

### C2. additionalProperties: True 可走私权限标志(上次未修)
- 证据: `runtime/safety/auth/arg_guard.py:1-23` 文档自认工具 schema 是 `additionalProperties: True`, `allow_sensitive`/`allow_private` 可被模型或间接提示注入走私进 tool input。
- 影响: 绕过敏感文件 denylist 与 SSRF 保护; 目前仅靠单一剥离点兜底, 违反纵深防御。
- 修复: 工具 schema 改 `additionalProperties: False` + handler 层二次剥离(双保险)。

### C3. 前端 live-preview XSS(上次未修)
- 证据: `frontend/src/components/workspace/live-preview-panel.tsx:100-138` htmlContent/jsContent 未转义拼入 iframe 内容 + `doc.write()` 回退; `:477/:487` `sandbox="allow-scripts allow-same-origin"` 形同虚设。
- 同类: `embedded-browser/iframe-renderer.tsx:117` 与 `browser-panel.tsx:155` 也含 `allow-same-origin`。
- 影响: LLM 输出或注入内容可在同源上下文执行任意 JS。
- 修复: 内容消毒; sandbox 移除 allow-same-origin / 改 srcdoc + 严格 CSP。

### C4. Reflex 模块 SSRF(上次未修, 已复核)
- 证据: `runtime/core/nerves/reflex/actions.py:81`、`broadcast.py:220`、`tiers.py:278` 三处裸 `urllib.request.urlopen`, **url_guard 完全未接入**(grep 零命中)。
- 影响: 控制 reflex_rules.yaml 或提示注入可 SSRF 内网。
- 修复: 统一走 `url_guard.safe_urlopen` + IP 固定与 DNS-rebinding 防护。

### C5. 前端依赖供应链: 78 个已知漏洞(本次新发现 ⚠️ 最重要)
- 证据: `pnpm audit`: **1 critical(shell-quote, quote() 不转义 .op 换行, 任意命令注入路径)** + 29 high + 38 moderate。
- 高影响项:
  - **Electron 系列**(影响桌面打包): offscreen UAF、WebContents 全屏/指针锁/键盘锁回调 UAF、PowerMonitor UAF、`commandLineSwitches` webPreference 注入、`Function.prototype.bind` 上下文隔离绕过、iframe 逃逸 allow-popups、custom protocol 跨源读取 —— 均需 Electron ≥39.8.10。
  - **vite `server.fs.deny` bypass**(dev server, Windows 备用路径)→ 开发期任意文件读取。
  - **undici**(经 jsdom 传递): TLS 校验绕过、WebSocket DoS、跨源请求路由、私有缓存信息泄露。
  - **axios**: 代理继承泄露; **sharp/libvips**: 4 个 CVE; **js-yaml**: 二次 CPU 消耗; **brace-expansion**: 指数 DoS(多版本); **extract-zip**: 符号链接路径穿越; **postcss**: sourceMappingURL 路径穿越。
- 修复: `pnpm audit --fix` 或按建议升级; Electron 升到 ≥39.8.10; 将 `pnpm audit` 纳入 CI 门禁。

---

## P1 — High

### H1. JWT 测试密钥硬编码 + 备份配置漂移(上次未修, 本次修正细节)
- 证据: `config.local.yaml:77,85` 与 `config.local.original-20260816.yaml:76` / `config.local.rollback-20260816.yaml:77` 均硬编码 `test-secret-key-for-local-development-only-1234567890`。
- 修正：这些文件**均已被 `.gitignore` 忽略且不在 git 仓库**（`git ls-files` 核实），故不存在“备份在仓库泄露”；真实风险是**一旦用户启用账号认证但忘记更换密钥，任何知情者可用已知测试密钥伪造任意 JWT**。
- 修复: 启动时检测到测试密钥即告警/拒绝; 文档显式提示生产必须更换; 备份配置改为环境变量注入。

### H2. API Key 哈希无盐(上次未修)
- 证据: `runtime/safety/auth/identity.py:45-85` 裸 SHA-256, 无 salt/pepper/迭代。
- 修复: 换 Argon2id 或至少 HMAC+随机盐+多次迭代。

### H3. trust_jwt_sub 静默合成身份(上次未修)
- 证据: `identity.py:83-107` 开启后从 JWT `sub` + `roles` 合成 Identity, 可冒充任意用户。
- 修复: 默认关闭, 审计/受信调用方显式开启。

### H4. Python 3.12 语法但声明支持 3.11(本次新发现 ⚠️)
- 证据: `runtime/execution/suckers/delegation_result_cache.py:114` `f"{p}:dir:{"|".join(entries)}"` 使用 PEP 701 嵌套 f-string 引号复用, 该语法 Python 3.12 才支持; 而 `pyproject.toml` `requires-python = ">=3.11"`。
- 影响: 在 Python 3.11 环境直接 SyntaxError 无法导入。
- 修复: 改为 `f"{p}:dir:{'|'.join(entries)}"`, 或如实提升 requires-python 到 ≥3.12 并在 CI 加 3.11 矩阵。

### H5. mypy 门禁红灯: evolution_ops_router.py(本次新发现)
- 证据: `tools/lint/mypy_ratchet.py` 报 `runtime/sensing/gateway/evolution_ops_router.py [union-attr] Item "None" of "Any | list[Any] | None" has no attribute "__iter__"`(313-316 行 `for name in _registry_skill_names(registry)`)。`_registry_skill_names` 实现在 utils.py:110 有 None/异常兜底, 但 mypy 对 `registry.all_names()` 推断为可空, 注解 `-> list[str]` 未消除告警。
- 影响: CI lint-mypy 门禁失败; 若注册表对象异常返回 None 存在潜在 TypeError 风险。
- 修复: 显式 `names = registry.all_names() or []` 收紧类型; 通过后 mypy 全绿。

### H6. external_bridge subprocess shell=True(bandit HIGH, 本次新发现)
- 证据: `runtime/safety/hooks/external_bridge.py:289` `subprocess.run(cmd, shell=True, ...)`; 命令先经 allowlist 校验("hook command not allowed by allowlist")。
- 影响: 依赖 allowlist 配置可信; 若 hook 配置可被提示注入改写则命令注入。
- 修复: 改 `shell=False` 数组传参(如允许)或白名单精确解析; 至少加 `shlex.split` 后显式校验。

---

## P2 — Medium

- M1. **ruff 24 errors**: `runtime/execution/suckers/delegation_result_cache.py:114` invalid-syntax(即 H4); `runtime/execution/loops/store.py:165-166` F821 为**误报**(DEFAULT_MAX_RUNS/TTL 为类属性); 其余 runtime 项为风格(UP031/N814/B904/SIM1xx); tests 侧 2 处 F821(Any/Path)运行时无碍(有 `from __future__ import annotations` / 局部注解), 属类型卫生问题。CI 若跑全量 ruff 会红。
- M2. **前端 45 lint warnings**: 大量未使用 import/变量, 集中在新组件(workspace-sidebar、sidebar-footer、settings-dialog、evolution-dashboard 等), 建议 CI 收紧。
- M3. **docs/auto 文档漂移导致 CI 测试失败**: `test_auto_docs_fresh.py` 报 5 个过期文件(00-overview、20-backend/index、cerebrum、model-router、hook-surface)。`make test` 全量会红。需跑 `python scripts/gen_wiki.py` 重新生成。
- M4. **dangerouslySetInnerHTML 2 处未消毒**: `mermaid-block.tsx:125`、`code-block.tsx:237`(上次未修)。
- M5. **前端无 CSP**(上次未修): 结合 C3/M4 放大 XSS 影响面。
- M6. **web_skills 重定向 TOCTOU SSRF**(上次 M4): 外部 client 重定向后未重新校验 URL。
- M7. **单体超大文件**: `_tool_bridge_loop.py` 2292 行、`bridge.py` 1484 行、`realtime_turn_lifecycle.py` 1382 行, 可维护性与评审成本偏高。
- M8. **bundle 体积**: 构建产物含 `codemirror-core` 1.05MB(gzip 345KB)、多个 500KB+ chunk(mermaid 系列、message-list 458KB), 有拆包/懒加载空间。

---

## 上次审计发现的状态核对

| 上次编号 | 结论 | 本次状态 |
|----------|------|----------|
| C1-C4 | P0 | **全部未修**, 证据仍在 |
| H1 JWT | P1 | 未修, 细节修正(gitignore 已挡, 不在仓库) |
| H2 无盐哈希 | P1 | 未修 |
| H3 trust_jwt_sub | P1 | 未修 |
| H4 dangerouslySetInnerHTML | P2 | 未修 |
| docker-compose 绑定 | 降级 medium | 维持(127.0.0.1) |
| cron shell 有意设计 | 非漏洞 | 维持 |

## 亮点(本次实测确认)

- 全量 12601 个测试通过, 测试基建成熟(上次修复的 40 个回归测试全绿)。
- Python 依赖 pip-audit **0 漏洞**, Python 供应链干净。
- 架构模块化良好: react_loop 已按 PHASE 1-7 拆分, 守卫(arg_guard/path_guard/url_guard/identity)系统化, 代码有完备注释与文档串。
- 前端 typecheck + build 全过, commitlint/husky/Makefile 统一入口落地。

## 修复优先级建议

1. **P0**: C5 前端依赖升级(Electron≥39.8.10, vite, axios, sharp…) → C1 Tentacle 认证 → C3 live-preview XSS → C2 schema 收紧 → C4 Reflex SSRF。
2. **P1**: H4 Python 3.11 兼容、H5 mypy 门禁、H6 external_bridge shell、H1-H3 认证加固。
3. **P2**: M1 ruff 全量清零、M3 重新生成 docs/auto、M2 前端 lint 清零、M7/M8 大文件与 bundle 治理。

## 结论

代码库质量高、测试覆盖成熟, 但**安全面(尤其前端供应链)是当前最大短板**: 78 个前端依赖漏洞(1 critical + 29 high)叠加默认无认证的 Tentacle 与局域网绑定, 一旦服务暴露到网络即构成实际攻陷路径。上一轮审计的 P0/P1 至今零修复, 建议按优先级排期, 先供应链、再认证与 XSS, 后 SSRF 与哈希加固。
