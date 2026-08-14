# 本地 CLI 伙伴兼容性问题诊断

## 问题描述

访问 http://localhost:3000/#/workspace/realtime/tTIlkFZNxyx4tOF2Ook3kM 时，
看到 OpenCode CLI 伙伴超时错误：

```
Local partner "OpenCode CLI 伙伴" timed out (no result within 240s).

建议：可以把任务拆小一点，或调大 OCTOPUS_LOCAL_PARTNER_TIMEOUT 后重试。
```

## 根本原因

**OpenCode CLI 未配置 AI 提供商凭证**

验证：
```bash
$ /Users/dangbei/.opencode/bin/opencode providers list
┌  Credentials ~/.local/share/opencode/auth.json
│
└  0 credentials  # ← 没有配置任何提供商！
```

当 OpenCode 没有凭证时，`opencode run` 命令会：
1. 启动但无法调用 AI 模型
2. 可能等待用户交互配置
3. 最终超时（240秒后）

## 解决方案

### 方案 1：配置 OpenCode 凭证（推荐）

```bash
# 添加提供商凭证
opencode providers add

# 或者使用环境变量
export ANTHROPIC_API_KEY="sk-ant-..."
# 或
export OPENAI_API_KEY="sk-..."
```

### 方案 2：在 Octopus 中禁用 OpenCode 伙伴

如果不需要使用 OpenCode CLI，可以在 Octopus 中禁用该伙伴：

```bash
# 查找 OpenCode 伙伴 agent 配置
find agents -name "*opencode*" -type f

# 编辑或删除 agents/local_opencode_cli/profile.jsonc
```

### 方案 3：增加超时时间（临时方案）

```bash
# 设置更长的超时时间
export OCTOPUS_LOCAL_PARTNER_TIMEOUT=600  # 10分钟

# 重启 Octopus
make dev-full
```

## 技术细节

### OpenCode CLI 调用流程

1. **Octopus 检测到 LocalPartner agent**
   - `agents/local_opencode_cli/profile.jsonc` 中定义
   - `runtime: "local_partner"`
   - `local_partner_id: "opencode-cli"`

2. **构建命令行参数**
   - `runtime/execution/agents/local_partner_bridge.py:build_partner_argv()`
   - 生成：`["opencode", "run", "-m", "<model>", "<prompt>"]`

3. **执行 CLI**
   - `runtime/sensing/gateway/realtime_local_partner.py:drive_local_partner()`
   - 默认超时：240 秒
   - 无 shell 注入风险（`shell=False`）

4. **超时处理**
   - 240 秒后返回超时错误
   - 不会回退到 Octopus 自己的模型（避免意外计费）

### OpenCode CLI 参数

```bash
opencode run [message..]

Positionals:
  message  message to send  [array] [default: []]

Options:
  -m, --model        model to use in the format of provider/model  [string]
  -c, --continue     continue the last session  [boolean]
  -s, --session      session id to continue  [string]
  --auto             auto-approve permissions (dangerous!)  [boolean]
  --format           format: default or json  [string]
  # ... 更多选项
```

### 当前实现

```python
# runtime/execution/agents/local_partner_bridge.py
def build_partner_argv(partner_id, command, prompt, model=None, adapter_notes=()):
    # ...
    if partner_id == "opencode-cli":
        return [
            command,           # "opencode"
            "run",
            *(["-m", m] if m else []),
            prompt_arg,        # 完整提示词作为一个参数
        ]
    # ...
```

这个实现是**正确的**，问题不在于命令构建，而在于 OpenCode 没有配置凭证。

## 验证修复

### 1. 配置凭证后测试

```bash
# 配置 OpenCode
opencode providers add

# 手动测试
opencode run "你是谁"

# 应该能看到响应（不再超时）
```

### 2. 在 Octopus 中测试

```bash
# 启动 Octopus
make dev-full

# 访问 http://localhost:3000
# 创建新对话，选择 "OpenCode CLI 伙伴"
# 发送消息，应该正常响应
```

## 其他本地 CLI 伙伴

Octopus 支持的本地 CLI 伙伴：

| Partner ID | Command | Status |
|------------|---------|--------|
| claude-code | `claude -p` | ✅ 可用 |
| codex-cli | `codex exec` | ✅ 可用 |
| opencode-cli | `opencode run` | ⚠️ 需要凭证配置 |
| trae-cli | `trae-cli -p` | ✅ 可用 |
| qoder-cli | `qodercli -p` | ✅ 可用 |
| codebuddy-cli | `codebuddy -p` | ✅ 可用 |
| kimi-cli | `kimi` | ✅ 可用 |

所有这些 CLI 都需要：
1. 正确安装在 PATH 中
2. 配置好 AI 提供商凭证
3. 能够在非交互模式下运行

## 改进建议

### 1. 添加凭证检查

在执行前检查 CLI 是否有可用凭证：

```python
def check_opencode_ready() -> bool:
    """Check if opencode has credentials configured."""
    try:
        result = subprocess.run(
            ["opencode", "providers", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "0 credentials" not in result.stdout
    except Exception:
        return False
```

### 2. 更友好的错误提示

```python
if partner_id == "opencode-cli" and not check_opencode_ready():
    return LocalPartnerResult(
        ok=False,
        error="OpenCode CLI 未配置 AI 提供商",
        fix_hint="运行 `opencode providers add` 配置凭证",
    )
```

### 3. 诊断命令

添加 Octopus 诊断命令：

```bash
# 检查所有本地伙伴状态
octopus partner-check

# 输出：
# ✅ claude-code: 已安装, 已登录
# ✅ codex-cli: 已安装, 已登录
# ⚠️ opencode-cli: 已安装, 未配置凭证
# ❌ trae-cli: 未安装
```

## 总结

**问题**：OpenCode CLI 没有配置 AI 提供商凭证  
**影响**：`opencode run` 命令超时（240秒）  
**修复**：运行 `opencode providers add` 配置凭证  
**预防**：添加启动前凭证检查和友好错误提示

配置凭证后，OpenCode CLI 伙伴应该能正常工作。
