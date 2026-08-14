# 本地 CLI 伙伴兼容性问题诊断与修复

## 问题描述

访问 http://localhost:3000/#/workspace/realtime/tTIlkFZNxyx4tOF2Ook3kM 时，
看到 OpenCode CLI 伙伴超时错误：

```
Local partner "OpenCode CLI 伙伴" timed out (no result within 240s).

建议：可以把任务拆小一点，或调大 OCTOPUS_LOCAL_PARTNER_TIMEOUT 后重试。
```

## 根本原因

**OpenCode CLI 缺少 `--auto` 标志**

OpenCode `run` 命令在非交互模式下需要 `--auto` 标志来自动批准权限请求。
没有这个标志，CLI 会等待用户交互确认，导致超时。

验证：
```bash
# ❌ 会卡住等待权限确认
$ opencode run "你是谁"

# ✅ 正常工作
$ opencode run --auto "你是谁"
> build · big-pickle
我是 opencode，一个命令行 AI 编程助手...
```

## 修复方案

### 已修复

在 `runtime/execution/agents/local_partner_bridge.py` 中添加 `--auto` 标志：

```python
if partner_id == "opencode-cli":
    return [
        command,
        "run",
        *(["-m", m] if m else []),
        "--auto",  # ← 添加此标志
        prompt_arg,
    ]
```

修复后的命令：
```bash
opencode run --auto "你是谁"
```

### OpenCode 模型格式

OpenCode 使用自己的模型命名空间：
```bash
# 可用的模型
opencode/big-pickle                    # 默认
opencode/deepseek-v4-flash-free        # DeepSeek 免费版
opencode/hy3-free
opencode/laguna-s-2.1-free
opencode/mimo-v2.5-free
opencode/nemotron-3-ultra-free
opencode/nemotron-3.5-lightning-free
```

使用示例：
```bash
opencode run -m opencode/deepseek-v4-flash-free --auto "分析代码"
```

## 测试验证

### 1. 直接测试 OpenCode CLI

```bash
# 测试默认模型
$ opencode run --auto "echo hello"
> build · big-pickle
$ echo hello
hello

# 测试指定模型
$ opencode run -m opencode/deepseek-v4-flash-free --auto "你是谁"
我是 opencode，一个命令行 AI 编程助手...
```

### 2. 在 Octopus 中测试

```bash
# 重启 Octopus
make dev-full

# 访问 http://localhost:3000
# 创建新对话，选择 "OpenCode CLI 伙伴"
# 发送消息，应该能在 240 秒内正常响应
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
