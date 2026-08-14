# 本地 CLI 伙伴插件化方案 - 基于现有架构

## 当前架构分析

### Octopus 有两套扩展系统

#### 1. **插件系统**（`.octopus/plugins/`）
- 用途：Skills、Channels、API routes
- 格式：`plugin.yaml` + Python `ModulePlugin`
- 例子：Sentry、Linear、GitHub 等外部服务集成

#### 2. **Agent 系统**（`agents/`）
- 用途：可分配的工作代理
- 格式：`profile.jsonc` + 可选 `SOUL.md`
- 例子：本地 CLI 伙伴（Claude Code、OpenCode、Codex）

### 本地 CLI 伙伴当前实现

```
agents/local_opencode_cli/
├── profile.jsonc          # Agent 元数据
├── avatar.svg             # 头像
└── SOUL.md                # Agent 指令（可选）

profile.jsonc 关键字段：
{
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "opencode-cli",           # 映射到 build_partner_argv()
    "local_partner_command": "/path/to/opencode", # CLI 命令路径
    "local_partner_executable": "/path/to/opencode"
  }
}
```

核心执行逻辑在 `runtime/execution/agents/local_partner_bridge.py`：
```python
def build_partner_argv(partner_id, command, prompt, model=None):
    if partner_id == "opencode-cli":
        return [command, "run", "--auto", prompt]
    # ... 硬编码其他 CLI
```

---

## 问题

1. **硬编码**：每个 CLI 的参数在 Python 代码中硬编码
2. **维护成本高**：新增 CLI 或参数变化需要修改核心代码
3. **不可扩展**：用户无法添加自定义 CLI

---

## 解决方案：基于现有 Agent 系统的插件化

### 核心思路

**在 `profile.jsonc` 中声明 CLI 参数配置**，而不是硬编码在 Python 中。

### 方案设计

#### 1. 扩展 `profile.jsonc` 格式

```jsonc
// agents/local_opencode_cli/profile.jsonc
{
  "id": "local_opencode_cli",
  "name": "OpenCode CLI 伙伴",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "opencode-cli",
    "local_partner_command": "/Users/user/.opencode/bin/opencode",
    "local_partner_executable": "/Users/user/.opencode/bin/opencode",
    
    // ✨ 新增：CLI 调用配置（声明式）
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        {"if": "model", "then": ["-m", "{model}"]},
        "--auto",
        "{prompt}"
      ],
      "timeout_seconds": 240,
      "supports_stdin": false
    },
    
    // ✨ 新增：模型配置
    "local_partner_model": {
      "supports_custom": true,
      "model_flag": "-m",
      "default": "opencode/big-pickle"
    },
    
    // ✨ 新增：认证检查（可选）
    "local_partner_auth": {
      "required": false,
      "check_hint": "OpenCode 使用免费模型，无需登录"
    },
    
    // ✨ 新增：错误诊断（可选）
    "local_partner_errors": [
      {
        "pattern": "Unexpected server error",
        "kind": "server_error",
        "hint": "请检查网络连接或稍后重试"
      }
    ]
  }
}
```

#### 2. 更新 `build_partner_argv()` 读取配置

```python
# runtime/execution/agents/local_partner_bridge.py

def build_partner_argv(
    partner_id: str,
    command: str,
    prompt: str,
    model: str | None = None,
    agent_capabilities: dict | None = None,  # ← 新增参数
) -> list[str] | None:
    """Build argv using agent's capabilities config (with fallback)."""
    
    # 尝试从 agent capabilities 读取配置
    if agent_capabilities and "local_partner_invocation" in agent_capabilities:
        invocation = agent_capabilities["local_partner_invocation"]
        return _build_from_template(
            template=invocation.get("args_template", []),
            command=command,
            prompt=prompt,
            model=model,
        )
    
    # Fallback: 保留现有硬编码逻辑（向后兼容）
    if partner_id == "opencode-cli":
        return [command, "run", "--auto", prompt]
    if partner_id == "codebuddy-cli":
        return [command, "-p", "-y", "--output-format", "text", prompt]
    # ...
    return None


def _build_from_template(
    template: list,
    command: str,
    prompt: str,
    model: str | None,
) -> list[str]:
    """Build argv from args_template."""
    argv = []
    for item in template:
        if isinstance(item, str):
            # 简单字符串替换
            value = item.format(command=command, prompt=prompt, model=model or "")
            if value:
                argv.append(value)
        elif isinstance(item, dict):
            # 条件包含
            if item.get("if") == "model" and model:
                for subitem in item["then"]:
                    argv.append(subitem.format(model=model))
    return argv
```

#### 3. 更新调用点传递 `capabilities`

```python
# runtime/sensing/gateway/realtime_local_partner.py

async def drive_local_partner(runtime, turn, log, emitter, intent, agent, provider, *, text: str):
    ident = partner_identity(getattr(agent, "capabilities", None))
    # ...
    
    # 传递完整的 capabilities
    result = await asyncio.to_thread(
        run_local_partner,
        partner_id=partner_id,
        command=command,
        prompt=prompt,
        model=partner_model or None,
        agent_capabilities=getattr(agent, "capabilities", None),  # ← 新增
    )
```

---

## 优势

### ✅ 与现有架构完美契合
- 使用已有的 `agents/` 目录和 `profile.jsonc`
- 不引入新的概念或目录结构
- 向后兼容现有 agent

### ✅ 低侵入性
- 只需扩展 `profile.jsonc` 格式
- 只需修改 `build_partner_argv()` 读取配置
- 保留硬编码逻辑作为 fallback

### ✅ 用户可扩展
```bash
# 用户添加自定义 CLI
mkdir -p agents/local_my_cli
cat > agents/local_my_cli/profile.jsonc << 'EOF'
{
  "id": "local_my_cli",
  "name": "My Custom CLI",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "my-cli",
    "local_partner_command": "/usr/local/bin/mycli",
    "local_partner_invocation": {
      "args_template": ["{command}", "exec", "--yes", "{prompt}"]
    }
  }
}
EOF

# 重启 Octopus 即可使用
```

### ✅ 易于维护
- CLI 参数变化：编辑 `profile.jsonc`
- 新增 CLI：复制目录，修改配置
- 无需改 Python 代码

---

## 迁移路径

### 阶段 1：扩展配置读取（2-3小时）
1. 在 `build_partner_argv()` 添加配置读取逻辑
2. 实现 `_build_from_template()` 函数
3. 更新调用点传递 `capabilities`
4. 保留硬编码 fallback

### 阶段 2：迁移现有 CLI（2-3小时）
1. 为 OpenCode CLI 添加 `local_partner_invocation`
2. 为 CodeBuddy CLI 添加配置（顺便修复 `-y` 问题）
3. 为其他 CLI 添加配置
4. 测试每个 CLI

### 阶段 3：文档和工具（1-2小时）
1. 更新 `profile.jsonc` schema 文档
2. 创建用户指南：如何添加自定义 CLI
3. 添加验证工具：`octopus agent validate local_my_cli`

**总工作量：5-8 小时**（而不是 5-8 天！）

---

## 示例：完整配置

### OpenCode CLI（已修复）
```jsonc
{
  "id": "local_opencode_cli",
  "name": "OpenCode CLI 伙伴",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "opencode-cli",
    "local_partner_command": "/Users/user/.opencode/bin/opencode",
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        {"if": "model", "then": ["-m", "{model}"]},
        "--auto",
        "{prompt}"
      ]
    }
  }
}
```

### CodeBuddy CLI（待修复）
```jsonc
{
  "id": "local_codebuddy_cli",
  "name": "CodeBuddy CLI 伙伴",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "codebuddy-cli",
    "local_partner_command": "/usr/local/bin/codebuddy",
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "-p",
        {"if": "model", "then": ["-m", "{model}"]},
        "-y",  // ← 修复：添加自动批准
        "--output-format",
        "text",
        "{prompt}"
      ]
    }
  }
}
```

### Claude Code（带登录提示）
```jsonc
{
  "id": "local_claude_code",
  "name": "Claude Code 伙伴",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "claude-code",
    "local_partner_command": "/usr/local/bin/claude",
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "-p",
        {"if": "model", "then": ["--model", "{model}"]},
        "{prompt}"
      ]
    },
    "local_partner_auth": {
      "required": true,
      "check_hint": "请运行 `claude` 然后执行 `/login` 登录"
    }
  }
}
```

---

## 对比：插件系统 vs Agent 配置

| 维度 | 使用插件系统 | 使用 Agent 配置 |
|------|------------|----------------|
| 文件位置 | `.octopus/plugins/` | `agents/` |
| 配置格式 | `plugin.yaml` + Python | `profile.jsonc` |
| 适用场景 | Skills、Channels、API | 可分配的工作代理 |
| 工作量 | 5-8 天（新系统） | 5-8 小时（扩展现有） |
| 架构一致性 | ⚠️ 引入新概念 | ✅ 符合现有模式 |
| 向后兼容 | ⚠️ 需要大量迁移 | ✅ Fallback 到硬编码 |
| 推荐程度 | ❌ 过度设计 | ✅ **推荐** |

---

## 总结

### 推荐方案：基于 Agent 配置的声明式参数

**核心改动**：
1. 在 `profile.jsonc` 的 `capabilities` 中添加 `local_partner_invocation` 配置
2. 修改 `build_partner_argv()` 优先读取配置，fallback 到硬编码
3. 保持向后兼容

**优势**：
- ✅ 与现有架构完美契合
- ✅ 低侵入性（几个小时工作量）
- ✅ 用户可扩展（复制 agent 目录即可）
- ✅ 易于维护（编辑 JSON，无需改代码）

**下一步**：
1. 立即实现基础框架（2-3小时）
2. 迁移现有 CLI（2-3小时）
3. 顺便修复 CodeBuddy 和 Claude Code 问题

要我开始实现吗？
