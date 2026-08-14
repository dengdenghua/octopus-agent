# 声明式本地 CLI 伙伴配置 - 使用指南

## 快速开始

### 场景 1：修改现有 CLI 的参数

假设 OpenCode 发布了新版本，`--auto` 改名为 `--non-interactive`。

#### 步骤

1. **找到配置文件**
   ```bash
   vim agents/local_opencode_cli/profile.jsonc
   ```

2. **修改 args_template**
   ```jsonc
   {
     "capabilities": {
       "local_partner_invocation": {
         "args_template": [
           "{command}",
           "run",
           {"if": "model", "then": ["-m", "{model}"]},
           "--non-interactive",  // ← 改这里
           "{prompt}"
         ]
       }
     }
   }
   ```

3. **重启 Octopus**
   ```bash
   # 如果是开发环境
   make dev
   
   # 或者重启服务
   octopus restart
   ```

4. **完成！** 下次调用 OpenCode 就会使用新参数。

**时间**: 30 秒

---

### 场景 2：添加新的 CLI 工具

假设你想添加一个新的 AI CLI 工具叫 `cursor`。

#### 步骤

1. **复制现有模板**
   ```bash
   cp -r agents/local_opencode_cli agents/local_cursor_cli
   ```

2. **编辑配置文件**
   ```bash
   vim agents/local_cursor_cli/profile.jsonc
   ```

   ```jsonc
   {
     "id": "local_cursor_cli",
     "name": "Cursor AI 伙伴",
     "icon": "CR",
     "description": "Cursor AI 本地 CLI 伙伴",
     "runtime": "local_partner",
     "capabilities": {
       "local_partner": true,
       "local_partner_id": "cursor-cli",
       "local_partner_command": "cursor",
       "local_partner_executable": "/usr/local/bin/cursor",
       "local_partner_invocation": {
         "args_template": [
           "{command}",
           "run",
           "--approve-all",
           {
             "if": "model",
             "then": ["-m", "{model}"]
           },
           "{prompt}"
         ]
       }
     }
   }
   ```

3. **（可选）替换头像**
   ```bash
   # 放一个 Cursor 的 logo
   cp ~/cursor-logo.svg agents/local_cursor_cli/avatar.svg
   ```

4. **重启 Octopus**
   ```bash
   make dev
   ```

5. **验证**
   打开 Octopus UI，在团队成员列表中应该能看到"Cursor AI 伙伴"。

**时间**: 5 分钟

---

## 模板语法详解

### 占位符

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `{command}` | CLI 命令路径 | `/usr/local/bin/cursor` |
| `{prompt}` | 用户任务（已包装） | `"Octopus adapter request..."` |
| `{model}` | 模型名称（可选） | `"gpt-4"` 或 `""` |

**示例**：
```jsonc
["{command}", "run", "{prompt}"]
// 展开为：
// ["/usr/local/bin/cursor", "run", "Octopus adapter request..."]
```

### 条件块

#### 基础条件
```jsonc
{
  "if": "model",
  "then": ["-m", "{model}"]
}
```
- 当 `model` 存在时：展开为 `["-m", "gpt-4"]`
- 当 `model` 为空时：不展开（跳过）

#### 带 else 分支
```jsonc
{
  "if": "model",
  "then": ["-m", "{model}"],
  "else": ["--default-model"]
}
```
- 当 `model` 存在时：展开为 `["-m", "gpt-4"]`
- 当 `model` 为空时：展开为 `["--default-model"]`

### 完整示例

#### OpenCode CLI
```jsonc
{
  "args_template": [
    "{command}",           // cursor
    "run",                 // 固定参数
    {
      "if": "model",       // 条件块：有模型时
      "then": ["-m", "{model}"]  // 添加 -m 参数
    },
    "--auto",              // 固定参数：自动确认
    "{prompt}"             // 用户任务
  ]
}
```

**展开结果**（有模型）：
```bash
cursor run -m deepseek/flash --auto "Octopus adapter request..."
```

**展开结果**（无模型）：
```bash
cursor run --auto "Octopus adapter request..."
```

#### Claude Code CLI
```jsonc
{
  "args_template": [
    "{command}",           // claude
    "-p",                  // print 模式
    {
      "if": "model",       // 条件块
      "then": ["--model", "{model}"]
    },
    "{prompt}"
  ]
}
```

**展开结果**：
```bash
claude -p --model opus-4 "Octopus adapter request..."
```

#### CodeBuddy CLI（带自动确认）
```jsonc
{
  "args_template": [
    "{command}",
    "-p",
    {
      "if": "model",
      "then": ["--model", "{model}"]
    },
    "--output-format", "text",
    "-y",                  // 自动确认（不等待用户输入）
    "{prompt}"
  ]
}
```

---

## 实际使用案例

### 案例 1：同一个 CLI 的多个变体

创建两个 OpenCode 配置：快速版和精确版。

#### OpenCode 快速版
```bash
cp -r agents/local_opencode_cli agents/local_opencode_fast
vim agents/local_opencode_fast/profile.jsonc
```

```jsonc
{
  "id": "local_opencode_fast",
  "name": "OpenCode 快速版",
  "capabilities": {
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        "--fast",           // ← 快速模式
        "--auto",
        "{prompt}"
      ]
    }
  }
}
```

#### OpenCode 精确版
```bash
cp -r agents/local_opencode_cli agents/local_opencode_thorough
vim agents/local_opencode_thorough/profile.jsonc
```

```jsonc
{
  "id": "local_opencode_thorough",
  "name": "OpenCode 精确版",
  "capabilities": {
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        "--thorough",       // ← 精确模式
        "--auto",
        "{prompt}"
      ]
    }
  }
}
```

**结果**：用户可以在 UI 中选择"OpenCode 快速版"或"OpenCode 精确版"！

---

### 案例 2：企业内部工具

假设公司有内部 AI CLI：`/opt/company/bin/internal-ai`

#### 创建私有配置
```bash
mkdir -p ~/.octopus/agents/local_internal_ai
vim ~/.octopus/agents/local_internal_ai/profile.jsonc
```

```jsonc
{
  "id": "local_internal_ai",
  "name": "内部 AI 助手",
  "icon": "IA",
  "description": "公司内部 AI CLI 工具",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "internal-ai",
    "local_partner_command": "/opt/company/bin/internal-ai",
    "local_partner_executable": "/opt/company/bin/internal-ai",
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "--corp-mode",       // 企业模式
        "--policy=strict",   // 严格策略
        "execute",
        "{prompt}"
      ]
    }
  }
}
```

**优势**：
- ✅ 配置不会提交到公开仓库
- ✅ Octopus 更新不影响这个配置
- ✅ 团队可以共享这个配置文件

---

### 案例 3：调试模式

为 OpenCode 添加调试标志。

```jsonc
{
  "id": "local_opencode_debug",
  "name": "OpenCode 调试版",
  "capabilities": {
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        "--verbose",         // 详细日志
        "--debug",           // 调试模式
        "--auto",
        "{prompt}"
      ]
    }
  }
}
```

---

## 常见问题

### Q1: 修改配置后不生效？

**A**: 需要重启 Octopus 服务。

```bash
# 开发环境
make dev

# 或生产环境
octopus restart
```

---

### Q2: 如何知道我的 CLI 需要什么参数？

**A**: 查看 CLI 的帮助文档：

```bash
# 查看帮助
opencode --help
cursor --help

# 查看所有参数
opencode run --help
```

常见参数模式：
- 非交互模式：`--auto`, `-y`, `--non-interactive`, `--approve-all`
- 模型选择：`-m <model>`, `--model <model>`
- 输出格式：`--output-format text`, `-o text`
- 一次性执行：`run`, `exec`, `-p`, `--print`

---

### Q3: 模板出错会怎样？

**A**: 会自动回退到硬编码规则，不会中断服务。

```python
try:
    argv = _expand_args_template(...)  # 尝试模板
    if argv:
        return argv
except Exception:
    pass  # 静默失败

# 回退到硬编码
if partner_id == "opencode-cli":
    return [command, "run", "--auto", prompt]
```

---

### Q4: 如何测试我的配置？

**方法 1：使用测试脚本**
```bash
.venv/bin/python scripts/test_declarative_cli_config.py
```

**方法 2：手动测试 argv 构建**
```python
from runtime.execution.agents.local_partner_bridge import build_partner_argv
import json

# 加载配置
with open("agents/local_opencode_cli/profile.jsonc") as f:
    lines = [l for l in f if not l.strip().startswith("//")]
    data = json.loads("".join(lines))
    capabilities = data["capabilities"]

# 测试构建
argv = build_partner_argv(
    partner_id="opencode-cli",
    command="opencode",
    prompt="test task",
    model="deepseek/flash",
    capabilities=capabilities,
)

print(argv)
# ['opencode', 'run', '-m', 'deepseek/flash', '--auto', 'Octopus adapter request...']
```

---

### Q5: 可以嵌套条件吗？

**A**: 目前不支持嵌套条件，只支持一层 `if`。

**不支持**：
```jsonc
{
  "if": "model",
  "then": [
    {
      "if": "debug",  // ❌ 嵌套不支持
      "then": ["--debug"]
    }
  ]
}
```

**推荐方案**：创建多个配置变体（如案例 1）。

---

### Q6: 可以使用环境变量吗？

**A**: 目前不支持，但这是计划中的功能（P2）。

**计划支持**：
```jsonc
{
  "args_template": [
    "{command}",
    "--config", "{env:HOME}/.config/cursor/config.json"
  ]
}
```

---

## 检查清单

### 添加新 CLI 前

- [ ] CLI 已安装并可以在终端运行
- [ ] 知道 CLI 的非交互模式参数
- [ ] 知道 CLI 的模型选择参数（如果有）
- [ ] 知道 CLI 的可执行文件路径

### 配置文件检查

- [ ] `id` 是唯一的（不与其他 agent 冲突）
- [ ] `local_partner_command` 是正确的命令名
- [ ] `local_partner_executable` 是绝对路径
- [ ] `args_template` 包含 `{command}` 和 `{prompt}`
- [ ] 如果支持模型选择，添加了 `{"if": "model", ...}`
- [ ] 如果 CLI 需要确认，添加了自动确认标志

### 测试验证

- [ ] 重启 Octopus 后能看到新 agent
- [ ] 可以在 UI 中选择这个 agent
- [ ] 实际派发任务能成功执行
- [ ] 带模型参数能正确传递

---

## 进阶技巧

### 技巧 1：条件 else 分支

当 CLI 必须有模型参数时：

```jsonc
{
  "args_template": [
    "{command}",
    "run",
    {
      "if": "model",
      "then": ["-m", "{model}"],
      "else": ["-m", "default"]  // 没有模型时用默认值
    },
    "{prompt}"
  ]
}
```

### 技巧 2：多个条件参数

虽然不支持嵌套，但可以并列多个条件：

```jsonc
{
  "args_template": [
    "{command}",
    {
      "if": "model",
      "then": ["-m", "{model}"]
    },
    "--auto",
    {
      "if": "model",
      "then": ["--verbose"]  // 有模型时也打开详细日志
    },
    "{prompt}"
  ]
}
```

### 技巧 3：占位符可以重复使用

```jsonc
{
  "args_template": [
    "{command}",
    "--log", "/tmp/{command}.log",  // 日志文件以命令命名
    "{prompt}"
  ]
}
```

---

## 资源

### 文档
- [价值分析](./value-declarative-vs-hardcoded-cli-config.md)
- [实施报告](./design-local-cli-partners-declarative-implementation.md)
- [完成总结](./declarative-cli-partners-completion-summary.md)

### 示例配置
- OpenCode: `agents/local_opencode_cli/profile.jsonc`
- Claude Code: `agents/local_claude_code/profile.jsonc`
- CodeBuddy: `agents/local_codebuddy_cli/profile.jsonc`

### 测试工具
- 单元测试: `tests/test_local_partner_declarative.py`
- 集成测试: `scripts/test_declarative_cli_config.py`

---

## 获取帮助

遇到问题？

1. 检查 CLI 是否能在终端正常运行
2. 查看 Octopus 日志：`logs/octopus.log`
3. 运行测试脚本验证配置
4. 参考现有配置文件示例

---

**开始享受秒级迭代的快感吧！** 🚀
