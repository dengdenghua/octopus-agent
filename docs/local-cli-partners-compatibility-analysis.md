# 本地 CLI 伙伴兼容性完整分析

## 概述

Octopus 支持 7 个本地 CLI 伙伴，但每个都有自己的兼容性要求和潜在问题。

## CLI 伙伴兼容性矩阵

| CLI Partner | 命令格式 | 状态 | 兼容性问题 | 修复方案 |
|-------------|----------|------|------------|----------|
| **OpenCode CLI** | `opencode run --auto` | ✅ 已修复 | 缺少 `--auto` 标志 | 已添加 `--auto` |
| **CodeBuddy CLI** | `codebuddy -p --output-format text` | ⚠️ 需要标志 | 权限未自动批准 | 需要添加 `-y` 或 `--auto` |
| **Claude Code** | `claude -p` | ⚠️ 需要登录 | 未登录返回错误 | 需要先运行 `claude /login` |
| **Trae CLI** | `trae-cli -p --output-format text` | ⚠️ 未验证 | 可能正常，需要进一步测试 | - |
| **Codex CLI** | `codex exec --skip-git-repo-check` | ❓ 未安装 | - | - |
| **Qoder CLI** | `qodercli -p` | ❓ 未安装 | - | - |
| **Kimi CLI** | `kimi` | ❓ 未知 | 无 headless 参数？ | 需要调查 |

## 详细问题分析

### 1. OpenCode CLI ✅ 已修复

**问题**：缺少 `--auto` 标志，导致等待权限确认超时

**症状**：
```bash
$ opencode run "echo hello"
# 卡住等待用户确认权限...
```

**修复**：
```python
# runtime/execution/agents/local_partner_bridge.py
if partner_id == "opencode-cli":
    return [
        command,
        "run",
        *(["-m", m] if m else []),
        "--auto",  # ← 添加此标志
        prompt_arg,
    ]
```

**验证**：
```bash
$ opencode run --auto "echo hello"
✅ 正常工作
```

---

### 2. CodeBuddy CLI ⚠️ 需要修复

**问题**：权限未自动批准，在非交互模式下拒绝执行工具

**症状**：
```bash
$ codebuddy -p --output-format text "echo hello"
Hello! The Bash tool is disabled in this non-interactive session...
If you'd like to execute shell commands, you can either:
- Re-run with `codebuddy -p -y "echo hello"` to auto-approve
- Add "Bash" to the `permissions.allow` list in your settings.
```

**修复方案**：添加 `-y` 或 `--auto` 标志

```python
if partner_id == "codebuddy-cli":
    # ...
    return [
        command,
        "-p",
        *(["-m", m] if m else []),
        "-y",  # ← 添加自动批准标志
        "--output-format",
        "text",
        prompt_arg,
    ]
```

**待验证**：
- `-y` 是否是正确的标志？
- 是否需要 `--auto` 而不是 `-y`？
- 检查 `codebuddy --help` 确认参数名

---

### 3. Claude Code ⚠️ 需要登录

**问题**：CLI 未登录，返回错误而不是执行任务

**症状**：
```bash
$ claude -p "echo hello"
Not logged in · Please run /login
```

**修复方案**：

**选项 A**：启动前检查登录状态
```python
def check_claude_logged_in() -> bool:
    try:
        result = subprocess.run(
            ["claude", "-p", "test"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "Not logged in" not in result.stderr
    except Exception:
        return False
```

**选项 B**：在错误诊断中识别
```python
def diagnose_partner_failure(...):
    # ...
    if partner_id == "claude-code" and "not logged in" in haystack(stderr):
        return PartnerFailureDiagnosis(
            "not_logged_in",
            "Claude Code CLI 未登录",
            "请先在终端运行 `claude` 然后执行 `/login` 命令登录你的 Claude 账号。",
        )
```

**选项 C**（推荐）：文档说明
- 在 agent 描述中说明需要先登录
- 首次使用时提示用户登录

---

### 4. Trae CLI ⚠️ 未充分验证

**当前命令**：
```bash
trae-cli -p --output-format text "<prompt>"
```

**状态**：进程能正常退出，但未验证输出内容

**待验证**：
1. 是否需要登录/认证？
2. 是否需要自动批准权限？
3. `--output-format text` 是否正确？
4. 是否有其他必需的标志？

**验证步骤**：
```bash
# 检查帮助
trae-cli --help
trae-cli -p --help

# 测试简单命令
trae-cli -p --output-format text "你是谁"

# 测试需要权限的命令
trae-cli -p --output-format text "echo hello"
```

---

### 5. Codex CLI ❓ 未安装

**当前命令**：
```bash
codex exec --skip-git-repo-check "<prompt>"
```

**状态**：本机未安装，无法测试

**潜在问题**：
- 是否需要登录？
- 是否需要自动批准权限？
- `--skip-git-repo-check` 是否足够？

---

### 6. Qoder CLI ❓ 未安装

**当前命令**：
```bash
qodercli -p "<prompt>"
```

**状态**：本机未安装，无法测试

**潜在问题**：
- 是否需要额外标志？
- 是否支持 `-p` 非交互模式？

---

### 7. Kimi CLI ❓ 未知

**问题**：`build_partner_argv` 中没有 `kimi-cli` 的实现

```python
# runtime/execution/agents/local_partner_bridge.py
def build_partner_argv(...):
    # ...
    if partner_id == "opencode-cli":
        return [...]
    # ← 没有 kimi-cli 的处理！
    return None
```

但在 `_PARTNER_LABELS` 中有定义：
```python
_PARTNER_LABELS = {
    # ...
    "kimi-cli": "Kimi CLI",
}
```

**状态**：不支持 headless 模式，会回退到 LLM 循环

---

## 通用兼容性模式

所有 CLI 伙伴的常见兼容性要求：

### 1. 非交互模式
必须支持 headless/print-and-exit 模式：
- ✅ `claude -p`
- ✅ `codex exec`
- ✅ `opencode run`
- ✅ `trae-cli -p`
- ✅ `qodercli -p`
- ✅ `codebuddy -p`

### 2. 权限自动批准
避免等待用户交互：
- ✅ `--auto` (OpenCode)
- ⚠️ `-y` 或 `--auto` (CodeBuddy，待确认)
- ❓ 其他 CLI

### 3. 认证/登录
某些 CLI 需要预先登录：
- ⚠️ Claude Code: 需要 `/login`
- ❓ Codex CLI: 可能需要登录
- ✅ OpenCode: 默认免费模型，无需登录
- ❓ 其他

### 4. 输出格式
控制输出格式避免 ANSI 转义等：
- `--output-format text` (Trae, CodeBuddy)
- `--format json` (OpenCode，可选)
- 其他可能有类似参数

---

## 改进建议

### 1. 启动前健康检查

为每个 CLI 添加健康检查函数：

```python
def check_partner_ready(partner_id: str, command: str) -> tuple[bool, str | None]:
    """Check if a CLI partner is ready to use.
    
    Returns:
        (ready: bool, error_hint: str | None)
    """
    if partner_id == "claude-code":
        # Check login status
        result = subprocess.run(
            [command, "-p", "test"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "Not logged in" in result.stderr:
            return False, "请先运行 `claude` 然后执行 `/login` 登录"
        return True, None
    
    elif partner_id == "opencode-cli":
        # OpenCode works with free models, always ready
        return True, None
    
    # ... 其他 CLI
    
    return True, None  # Default: assume ready
```

### 2. 改进错误诊断

在 `diagnose_partner_failure` 中添加更多特定错误识别：

```python
def diagnose_partner_failure(...):
    # 现有的通用诊断
    # ...
    
    # 特定 CLI 的特定错误
    if partner_id == "claude-code":
        if "not logged in" in haystack(stderr):
            return PartnerFailureDiagnosis(
                "not_logged_in",
                "Claude Code CLI 未登录",
                "运行 `claude` 然后执行 `/login`",
            )
    
    if partner_id == "codebuddy-cli":
        if "tool is disabled" in haystack(stdout, stderr):
            return PartnerFailureDiagnosis(
                "permissions_denied",
                "CodeBuddy CLI 拒绝执行工具",
                "需要添加 `-y` 标志自动批准权限",
            )
    
    # ... 更多特定错误
```

### 3. 添加自动批准标志

为所有支持的 CLI 添加适当的自动批准标志：

```python
# 需要调查每个 CLI 的正确标志
_AUTO_APPROVE_FLAGS = {
    "opencode-cli": ["--auto"],
    "codebuddy-cli": ["-y"],  # 或 ["--auto"]？
    "codex-cli": ["--yes"],   # 待确认
    # ...
}

def build_partner_argv(...):
    # ...
    auto_flags = _AUTO_APPROVE_FLAGS.get(partner_id, [])
    return [command, "run", *auto_flags, *model_flags, prompt_arg]
```

### 4. 文档和用户指南

为每个 CLI 创建设置指南：

```markdown
# 设置本地 CLI 伙伴

## Claude Code
1. 安装: `npm install -g @anthropic-ai/claude-code`
2. 登录: 运行 `claude` 然后执行 `/login`
3. 验证: `claude -p "test"`

## OpenCode
1. 安装: `curl -fsSL https://opencode.app/install.sh | bash`
2. 无需登录（使用免费模型）
3. 验证: `opencode run --auto "test"`

## CodeBuddy
1. 安装: 访问 codebuddy.ai
2. 登录: `codebuddy login`
3. 验证: `codebuddy -p -y "test"`
```

---

## 立即行动项

### 优先级 1：修复 CodeBuddy
```bash
# 1. 确认正确的自动批准标志
codebuddy --help | grep -E "(auto|yes|-y)"

# 2. 测试
codebuddy -p -y --output-format text "echo hello"

# 3. 更新 build_partner_argv
```

### 优先级 2：改进 Claude Code 错误提示
```python
# 添加登录状态检查和友好错误提示
```

### 优先级 3：验证 Trae CLI
```bash
# 完整测试 Trae CLI 的功能
trae-cli -p --output-format text "分析这个项目"
```

### 优先级 4：文档
```markdown
# 创建用户指南
docs/local-cli-partners-setup-guide.md
```

---

## 总结

**已修复**：
- ✅ OpenCode CLI (添加 `--auto`)

**待修复**：
- ⚠️ CodeBuddy CLI (需要 `-y` 或类似标志)
- ⚠️ Claude Code (需要登录检查和友好提示)

**待验证**：
- ❓ Trae CLI (命令能退出但未验证输出)
- ❓ Codex CLI (未安装)
- ❓ Qoder CLI (未安装)
- ❓ Kimi CLI (无 headless 实现)

**改进方向**：
1. 启动前健康检查
2. 特定 CLI 的错误诊断
3. 统一的自动批准机制
4. 完整的用户设置指南
