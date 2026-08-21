# octopus-agent 深度审计报告

- 日期: 2026-08-19
- 审计方式: 6 路并行审计代理 + 全部发现逐行源码复核(17 处)
- 验证状态: 动态测试/typecheck/build 因执行环境受限未能运行; 结论基于静态审查
- 审计为只读操作, 未修改任何代码或配置

## Critical (P0)

### C1. Tentacle Dashboard 默认无认证
- 证据: `runtime/tentacle/dashboard.py:49` require_auth=False; `runtime/tentacle/coordinator.py:173` 未传 require_auth=True; `config.local.yaml` oct.enabled=false + local_auth.enabled=false + allow_any_username=true
- 影响: 设备列表/任务提交/截图/VLM 分析/远程输入/WebSocket 屏幕流对局域网开放
- 修复: create_tentacle_router 默认 require_auth=True; 生产强制启用认证

### C2. additionalProperties: True 可走私权限标志
- 证据: `runtime/safety/auth/arg_guard.py:1-23` 文档自认 allow_sensitive/allow_private 可被模型或提示注入走私
- 影响: 绕过敏感文件 denylist 和 SSRF 保护; 依赖单一剥离点(executor.py:221)
- 修复: schema 改 additionalProperties: False + handler 层二次剥离

### C3. 前端 live-preview iframe XSS
- 证据: `frontend/src/components/workspace/live-preview-panel.tsx:95-126` htmlContent/cssContent/jsContent 未转义插入 + doc.write 回退; sandbox="allow-scripts allow-same-origin"
- 影响: LLM 输出或用户输入可注入任意 JS
- 修复: 内容消毒; sandbox 移除 allow-same-origin 或 srcdoc + 严格 CSP

### C4. Reflex 模块 SSRF (三处)
- 证据: `runtime/core/nerves/reflex/actions.py:55-100`; `broadcast.py:195-225`; `tiers.py:260-290` 裸 urllib.urlopen 无 URL 校验, nosec B310 无技术缓解
- 影响: 控制 reflex_rules.yaml 或提示注入可 SSRF 内网; SLM 端点无 DNS-rebinding 保护
- 修复: 统一走 url_guard.safe_urlopen; IP 固定与重绑定防护

## High (P1)

| # | 发现 | 证据 | 影响 |
|---|------|------|------|
| H1 | JWT 密钥硬编码 + 备份配置漂移 | config.local.yaml:76,84 测试密钥; original/rollback 备份文件在仓库 | 可伪造任意 JWT |
| H2 | API Key 哈希无盐 | runtime/safety/auth/identity.py:45-85 裸 SHA-256 | 彩虹表/GPU 批量破解 |
| H3 | trust_jwt_sub 静默合成身份 | identity.py:83-107 从 JWT sub 合成 Identity | 冒充任意用户 |
| H4 | dangerouslySetInnerHTML 2 处 | code-block.tsx:237; mermaid-block.tsx:125 | Shiki/Mermaid CVE 时可 XSS |
| H5 | thread metadata 可声明文件访问根 | _fs_router_helpers.py:80-130 本地模式无兜底 | 绕过文件系统边界 |
| H6 | 浏览器回环访问静默恢复(下调) | _executor_helpers.py:48-89 仅 session metadata 污染时可绕过 | 建议显式白名单 |

## Medium (P2)

- M1: image_generation.py:692-695 shell=True 模板来自配置, 建议 shell=False
- M2: cron shell 执行为有意设计(下调), 仅需校验 UI 命令来源
- M3: 前端无 CSP
- M4: web_skills.py:70-115 外部 client 重定向未重新校验 (TOCTOU SSRF)
- M5: team_bridge.py:25-50 tentacle token 明文落盘无权限限制
- M6: auth/api.ts:20-50 localStorage token 迁移可能串会话
- M7: 配置备份文件漂移

## 对子代理初报的更正

1. docker-compose.yml:19 实际默认绑定 127.0.0.1 (非 0.0.0.0), 风险降为 medium
2. cron_executor.py _shell_argv 是有意的信任边界设计, 非漏洞

## 亮点

- 安全守卫系统化: arg_guard/path_guard/url_guard/crypto 字段级加密
- 测试规模: 3802 个测试, 含专门安全测试
- .gitignore 正确排除敏感文件
- commitlint 落地, Makefile 统一入口, 文档体系完整
- nosec 注释诚实标注风险点

## 修复优先级

| 优先级 | 事项 | 工作量 |
|--------|------|--------|
| P0 | C1 Tentacle 认证默认开启 | 小 |
| P0 | C2 additionalProperties: False | 中 |
| P0 | C3 live-preview 消毒 + sandbox 收紧 | 小 |
| P0 | H1 轮换 JWT 密钥 + 清理备份配置 | 小 |
| P1 | C4 Reflex SSRF 统一 safe_urlopen | 中 |
| P1 | H2 Argon2id; H3 关闭 trust_jwt_sub | 小 |
| P1 | H4 两处 dangerouslySetInnerHTML 消毒 | 小 |
| P2 | M1-M7 批量加固 | 中 |

## 结论

底子很好, 但"本地单用户"安全假设正在被打破。配置默认关闭认证 + 硬编码测试密钥 + Tentacle 无鉴权, 一旦服务暴露到网络即设备控制权拱手让人。建议按 P0 顺序先堵认证与 XSS, 再处理 SSRF 与哈希加固。
