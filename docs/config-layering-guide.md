# 配置分层系统使用指南

## 概述

Octopus Agent 支持通过 `extends` 关键字进行配置继承，实现配置复用和分层管理。这一特性从 **DeepSeek Harness** 的设计中吸收而来。

## 基本用法

### 创建基础配置

```yaml
# config/base.yaml
name: octopus-base
version_compat: "0.2"
preset: null

budget:
  max_tokens: 50000
  max_usd: 0.50

planner:
  type: llm
  model: claude-haiku-4-5-20251001
```

### 继承基础配置

```yaml
# config/dev.yaml
extends: base.yaml

name: octopus-dev

# 覆盖预算配置
budget:
  max_tokens: 100000
  max_usd: 2.00
```

加载 `dev.yaml` 时会自动继承 `base.yaml` 的所有配置，并用 `dev.yaml` 中的值覆盖。

## 特性

### 1. 深度合并（Deep Merge）

嵌套字典会递归合并，而不是完全替换：

```yaml
# base.yaml
immunity:
  trusted_sources:
    - "skill://public/*"
  attack_threshold: 3
  unknown_policy: quarantine

# prod.yaml
extends: base.yaml
immunity:
  attack_threshold: 2  # 覆盖
  enable_adaptive: true  # 新增
```

结果：
- `attack_threshold`: 2（来自 prod.yaml）
- `unknown_policy`: quarantine（继承自 base.yaml）
- `enable_adaptive`: true（来自 prod.yaml）
- `trusted_sources`: 保持不变（继承自 base.yaml）

### 2. 多层继承链

支持多级继承：

```yaml
# base.yaml
budget:
  max_tokens: 50000

# dev.yaml
extends: base.yaml
budget:
  max_tokens: 100000

# dev-large.yaml
extends: dev.yaml
budget:
  max_tokens: 200000
```

### 3. 相对路径

`extends` 支持相对路径，相对于当前配置文件的目录：

```yaml
# config/environments/production.yaml
extends: ../base.yaml  # 引用上级目录的 base.yaml
```

### 4. 环境变量插值

`extends` 与环境变量插值兼容：

```yaml
# prod.yaml
extends: base.yaml
oct:
  jwt_secret: ${OCT_JWT_SECRET}  # 从环境变量读取
```

## 安全限制

### 循环引用检测

系统会检测并拒绝循环引用：

```yaml
# a.yaml
extends: b.yaml

# b.yaml
extends: a.yaml  # ❌ 错误：循环引用
```

### 继承深度限制

最大继承深度为 10 层，防止过深的继承链：

```yaml
# config1.yaml → config2.yaml → ... → config11.yaml
# ❌ 错误：超过最大深度限制
```

## 预设配置模板

Octopus 提供三个预设配置模板：

### 1. `config/base.yaml`

最小化基础配置，适合作为其他配置的起点。

### 2. `config/dev.yaml`

开发环境配置：
- 更大的预算（100k tokens, $2.00）
- 启用本地认证
- 允许客户端绕过审批（仅单用户）
- 启用持久化学习

### 3. `config/prod.yaml`

生产环境配置：
- 更强大的模型（Sonnet）
- 更大的预算（200k tokens, $5.00）
- 严格的安全配置
- 启用 LLM 判断和信任信号
- 生产级沙箱

## 使用示例

### 快速开始

```bash
# 使用开发环境配置启动
.venv/bin/python -m runtime serve --config config/dev.yaml

# 使用生产环境配置启动
.venv/bin/python -m runtime serve --config config/prod.yaml
```

### 创建自定义配置

```yaml
# config/my-custom.yaml
extends: dev.yaml

name: my-experiment

# 只覆盖需要改变的部分
planner:
  model: claude-opus-4-7  # 使用更强的模型

budget:
  max_tokens: 150000  # 调整预算
```

### 多环境管理

```
config/
├── base.yaml           # 基础配置
├── dev.yaml            # 开发环境
├── staging.yaml        # 预发布环境
├── prod.yaml           # 生产环境
└── ci.yaml             # CI 环境
```

每个环境都继承 `base.yaml`，只覆盖差异部分。

## API 使用

### Python API

```python
from runtime.platform.config.loader import load_from_yaml

# 启用 extends 解析（默认）
config = load_from_yaml("config/dev.yaml")

# 禁用 extends 解析（向后兼容）
config = load_from_yaml("config/dev.yaml", resolve_extends=False)
```

### 向后兼容性

不使用 `extends` 的配置文件继续按原方式工作，无需修改：

```yaml
# 传统配置（无 extends）仍然有效
name: my-octopus
version_compat: "0.2"
preset: personal
# ... 完整配置
```

## 最佳实践

### 1. 单一基础配置

创建一个 `base.yaml` 包含所有默认值，所有环境配置继承它：

```yaml
# base.yaml - 单一真相来源
# dev.yaml, staging.yaml, prod.yaml 都继承这个
```

### 2. 最小化覆盖

只在子配置中覆盖真正需要改变的值：

```yaml
# ✅ 好：只覆盖必要的
extends: base.yaml
budget:
  max_tokens: 100000

# ❌ 差：复制了不必要的配置
extends: base.yaml
name: dev
version_compat: "0.2"
preset: personal
budget:
  max_tokens: 100000
planner:
  type: llm
  model: claude-haiku-4-5-20251001
```

### 3. 明确继承链

避免过长的继承链（建议 ≤ 3 层）：

```yaml
# ✅ 好：清晰的继承
base.yaml → dev.yaml → dev-large.yaml

# ❌ 差：过深的继承
base.yaml → common.yaml → shared.yaml → dev-base.yaml → dev.yaml
```

### 4. 环境特定配置

为每个部署环境创建专门的配置文件：

```yaml
# config/prod-us-west.yaml
extends: prod.yaml
name: octopus-prod-us-west
journal_file: /var/log/octopus/us-west/journal.jsonl
```

### 5. 注释继承来源

在覆盖值时添加注释说明原因：

```yaml
extends: base.yaml

# 开发环境需要更多预算用于实验
budget:
  max_tokens: 100000

# 开发环境允许绕过审批加快迭代
safety:
  allow_client_approval_bypass: true
```

## 故障排除

### 错误：`extends target not found`

**原因**：extends 路径错误或文件不存在

**解决**：
```bash
# 检查文件是否存在
ls -la config/base.yaml

# 使用相对路径
extends: ./base.yaml  # 同目录
extends: ../base.yaml  # 上级目录
```

### 错误：`circular extends detected`

**原因**：配置文件互相引用

**解决**：重新组织继承关系，确保单向依赖：
```
base.yaml (无 extends)
  ↓
dev.yaml (extends: base.yaml)
  ↓
dev-large.yaml (extends: dev.yaml)
```

### 错误：`extends chain too deep`

**原因**：继承链超过 10 层

**解决**：简化继承结构，合并中间层配置

## 技术细节

### 合并算法

1. 加载 base 配置（递归解析其 extends）
2. 加载 current 配置
3. 深度合并：
   - 字典：递归合并键值
   - 列表：current 完全覆盖 base
   - 标量：current 覆盖 base
4. 移除 `extends` 键
5. 应用环境变量插值
6. Pydantic 验证

### 性能考虑

- extends 解析在启动时一次性完成
- 循环引用检测使用访问集合（O(n)）
- 深度合并是递归的，但配置文件通常较小

## 相关资源

- [ADR-004: Configuration Layering](../.agents/notes/implemented/ADR-004-config-layering.md) - 已实施的架构决策
- [config.example.yaml](../config.example.yaml) - 完整配置示例
- [schema.py](../runtime/platform/config/schema.py) - 配置模式定义

## 致谢

此功能的设计灵感来自 [DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-V3) 的配置系统，在其基础上进行了适配和增强。
