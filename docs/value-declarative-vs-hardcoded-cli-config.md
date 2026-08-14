# 声明式配置 vs 硬编码 - 实际价值分析

## 问题场景

假设你想添加一个新的 CLI 伙伴，或者现有 CLI 的参数发生了变化。

---

## 场景 1：OpenCode CLI 升级，参数变化

### 硬编码方式（当前）❌

OpenCode v2.0 发布，`--auto` 改名为 `--non-interactive`

**需要的操作**：
1. ✏️ 修改 Python 代码
   ```python
   # runtime/execution/agents/local_partner_bridge.py (核心代码!)
   def build_partner_argv(...):
       if partner_id == "opencode-cli":
           return [command, "run", "--auto", prompt]  # ← 需要改这里
   ```

2. 🧪 运行测试套件
   ```bash
   pytest tests/ -k local_partner  # 可能需要 10+ 分钟
   ```

3. 📝 提交代码审查
   ```bash
   git commit -m "fix: update opencode CLI to v2.0 --non-interactive flag"
   # 等待团队审查、CI 通过
   ```

4. 🚀 部署到生产
   ```bash
   # 需要发布新版本
   make release
   docker build ...
   ```

5. 📦 用户更新
   ```bash
   # 所有用户需要更新 Octopus
   octopus upgrade
   ```

**问题**：
- ❌ 改的是**核心代码**，影响所有 CLI
- ❌ 需要完整的开发流程（测试、审查、发布）
- ❌ 用户必须升级 Octopus 才能用新版 OpenCode
- ❌ 如果你不是维护者，需要提 PR 等待合并

**时间成本**：1-3 天（修改 → 测试 → 审查 → 发布 → 用户升级）

---

### 声明式配置（提议）✅

**需要的操作**：
1. ✏️ 修改配置文件
   ```jsonc
   // agents/local_opencode_cli/profile.jsonc (用户可编辑!)
   {
     "capabilities": {
       "local_partner_invocation": {
         "args_template": [
           "{command}",
           "run",
           "--non-interactive",  // ← 只改这里
           "{prompt}"
         ]
       }
     }
   }
   ```

2. 🔄 重启 Octopus
   ```bash
   octopus restart  # 或热重载
   ```

3. ✅ 完成！

**优势**：
- ✅ 改的是**配置文件**，不影响核心代码
- ✅ 不需要测试、审查、发布流程
- ✅ 用户自己就能改，无需等 Octopus 更新
- ✅ 改错了可以立即回滚

**时间成本**：30 秒

---

## 场景 2：添加新的 CLI 伙伴（例如 Cursor AI）

假设 Cursor AI 发布了 CLI 工具 `cursor`，调用方式：
```bash
cursor run --approve-all "prompt"
```

### 硬编码方式（当前）❌

**需要的操作**：
1. ✏️ 修改核心 Python 代码（3 个文件）
   ```python
   # runtime/execution/agents/local_partner_bridge.py
   _PARTNER_LABELS = {
       # ...
       "cursor-cli": "Cursor AI",  # ← 添加标签
   }
   
   def build_partner_argv(...):
       # ...
       if partner_id == "cursor-cli":  # ← 添加新分支
           return [command, "run", "--approve-all", prompt]
       # ...
   ```

2. ✏️ 注册 agent
   ```python
   # runtime/execution/agents/local_partner_discovery.py
   # 添加检测逻辑
   ```

3. ✏️ 创建 agent 目录
   ```bash
   mkdir agents/local_cursor_cli
   # 手动创建 profile.jsonc, avatar.svg, SOUL.md
   ```

4. 🧪 写测试
   ```python
   # tests/test_local_partner_cursor.py
   def test_cursor_cli_argv_building():
       ...
   ```

5. 📝 提交 PR，等待审查和合并

6. 📦 等待下一个 Octopus 版本发布

**问题**：
- ❌ **普通用户做不到**（需要懂 Python、理解代码库）
- ❌ 必须修改核心代码
- ❌ 需要维护者审查和合并
- ❌ 需要等 Octopus 发布新版本

**时间成本**：
- 你：3-5 小时（写代码、测试、提交 PR）
- 维护者：1-2 天（审查、合并、发布）
- 用户：等下次更新

---

### 声明式配置（提议）✅

**需要的操作**：
1. ✏️ 复制模板并修改配置
   ```bash
   # 复制现有 agent 作为模板
   cp -r agents/local_opencode_cli agents/local_cursor_cli
   ```

2. ✏️ 编辑配置文件
   ```jsonc
   // agents/local_cursor_cli/profile.jsonc
   {
     "id": "local_cursor_cli",
     "name": "Cursor AI 伙伴",
     "runtime": "local_partner",
     "capabilities": {
       "local_partner": true,
       "local_partner_id": "cursor-cli",
       "local_partner_command": "/usr/local/bin/cursor",
       "local_partner_invocation": {
         "args_template": [
           "{command}",
           "run",
           "--approve-all",
           "{prompt}"
         ]
       }
     }
   }
   ```

3. 🎨 可选：替换头像
   ```bash
   # 放一个 cursor 的 logo
   cp ~/cursor-logo.svg agents/local_cursor_cli/avatar.svg
   ```

4. 🔄 重启 Octopus
   ```bash
   octopus restart
   ```

5. ✅ 完成！立即可用

**优势**：
- ✅ **任何用户都能做**（只需编辑 JSON）
- ✅ 不改核心代码
- ✅ 无需等维护者
- ✅ 无需等 Octopus 更新
- ✅ 可以分享配置文件给其他用户

**时间成本**：5 分钟

---

## 场景 3：同一个 CLI 的不同配置

假设你想为 OpenCode 创建两个变体：
- **OpenCode 快速版**：用 `--fast` 模式，更快但质量稍低
- **OpenCode 精确版**：用 `--thorough` 模式，更慢但质量更高

### 硬编码方式（当前）❌

**几乎不可能**，因为：
- `partner_id` 是硬编码的
- 无法为同一个 CLI 创建多个配置
- 需要大量修改核心逻辑

---

### 声明式配置（提议）✅

**需要的操作**：
```bash
# 创建两个 agent
cp -r agents/local_opencode_cli agents/local_opencode_fast
cp -r agents/local_opencode_cli agents/local_opencode_thorough
```

```jsonc
// agents/local_opencode_fast/profile.jsonc
{
  "id": "local_opencode_fast",
  "name": "OpenCode 快速版",
  "capabilities": {
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        "--fast",  // ← 不同配置
        "--auto",
        "{prompt}"
      ]
    }
  }
}

// agents/local_opencode_thorough/profile.jsonc
{
  "id": "local_opencode_thorough",
  "name": "OpenCode 精确版",
  "capabilities": {
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "run",
        "--thorough",  // ← 不同配置
        "--auto",
        "{prompt}"
      ]
    }
  }
}
```

**结果**：用户可以在 UI 中选择不同的 OpenCode 配置！

---

## 场景 4：企业定制

假设企业内部有自研的 AI CLI 工具 `internal-ai`，只能在内网使用。

### 硬编码方式（当前）❌

**不可行**：
- 不能把内部工具的代码提交到公开仓库
- 需要维护私有 fork
- 每次 Octopus 更新都要手动合并

---

### 声明式配置（提议）✅

**解决方案**：
```bash
# 在私有配置目录添加
mkdir -p ~/.octopus/agents/local_internal_ai
cat > ~/.octopus/agents/local_internal_ai/profile.jsonc << 'EOF'
{
  "id": "local_internal_ai",
  "name": "内部 AI 助手",
  "runtime": "local_partner",
  "capabilities": {
    "local_partner": true,
    "local_partner_id": "internal-ai",
    "local_partner_command": "/opt/company/bin/internal-ai",
    "local_partner_invocation": {
      "args_template": [
        "{command}",
        "--corp-mode",
        "--policy=strict",
        "execute",
        "{prompt}"
      ]
    }
  }
}
EOF
```

**优势**：
- ✅ 配置私有化，不进公开仓库
- ✅ Octopus 更新不影响这个配置
- ✅ 团队内部可以共享配置文件

---

## 核心价值总结

### 1. **解耦关注点**
```
硬编码：CLI 参数 ← 混在 → 核心执行逻辑
声明式：CLI 参数 → 配置文件 | 核心执行逻辑 → 纯粹
```

### 2. **权力下放**
```
硬编码：只有维护者能改
声明式：用户、企业、社区都能改
```

### 3. **快速迭代**
```
硬编码：修改 → 测试 → 审查 → 发布 → 用户升级（天级）
声明式：修改 → 重启（秒级）
```

### 4. **降低风险**
```
硬编码：改错核心代码 → 影响所有功能 → 严重事故
声明式：改错配置 → 只影响一个 CLI → 秒级回滚
```

### 5. **社区生态**
```
硬编码：新 CLI 需要提 PR → 等待合并 → 官方支持
声明式：用户写配置 → 分享到社区 → 即刻可用 → 自然形成生态
```

---

## 类比理解

### 硬编码 = 买品牌电脑
- ❌ 配置固定，想加内存需要找厂商
- ❌ 新功能要等下一代产品
- ❌ 不满意也只能等官方更新

### 声明式 = 组装电脑
- ✅ 配置灵活，自己换内存
- ✅ 新硬件出来立即能用
- ✅ 不满意随时调整

---

## 实际案例对比

### Nginx (声明式配置) ✅
```nginx
# nginx.conf
server {
    listen 80;
    server_name example.com;
}
```
- 用户自己写配置
- 改了重启即生效
- 社区有无数配置示例

### 假如 Nginx 硬编码 ❌
```python
# 每个网站都要改代码
if domain == "example.com":
    listen_port = 80
    ssl = False
```
- 每个网站都要提 PR
- 等待 Nginx 发布新版本
- Nginx 早就死了

---

## 结论

**声明式配置的价值 = 灵活性 × 可扩展性 × 社区力量**

对于本地 CLI 伙伴：
- ✅ 用户可以自己适配新 CLI（5 分钟）
- ✅ CLI 参数变化可以立即修改（30 秒）
- ✅ 企业可以定制内部工具（不改核心代码）
- ✅ 社区可以贡献配置文件（形成生态）
- ✅ 维护者可以专注核心逻辑（不被琐事淹没）

**最重要的是**：把控制权交给用户，而不是锁在代码里。
