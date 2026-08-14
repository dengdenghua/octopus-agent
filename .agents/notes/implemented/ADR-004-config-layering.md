# ADR-004: 配置分层系统

**状态**: ✅ Implemented  
**日期**: 2026-08-14  
**作者**: Octopus Team  
**实施**: 2026-08-14 (Phase 1)  
**灵感来源**: DeepSeek Harness Profile/Bundle 系统

## 决策

实现基于 YAML 的配置分层系统，支持通过 `extends` 关键字进行配置继承和深度合并。

## 问题陈述

当前 Octopus 使用单层配置 `config.local.yaml`，导致：

1. **环境切换困难**
   - 开发/测试/生产需要手动修改配置
   - 容易出错（忘记改回来）

2. **配置重复**
   - 多个环境的公共配置需要复制粘贴
   - 修改基础配置需要改多处

3. **团队协作困难**
   - 每个开发者的本地配置不同
   - 无法分享"推荐配置"

4. **无法组合**
   - 不能组合多个配置文件
   - 不能创建可复用的配置模块

## 提议的解决方案

实现**分层配置系统**，支持配置继承和组合：

### 目录结构
```
config/
├── base.yaml           # 基础配置（所有环境共享）
├── dev.yaml            # 开发环境
├── test.yaml           # 测试环境
├── prod.yaml           # 生产环境
└── profiles/
    ├── cheap-models.yaml      # 使用便宜模型
    ├── high-performance.yaml  # 高性能配置
    └── debug-mode.yaml        # 调试模式
```

### 配置继承
```yaml
# config/base.yaml
models:
  default: claude-sonnet-3.5
  fast: claude-haiku-3

database:
  pool_size: 10

realtime:
  adaptive_batching: true
```

```yaml
# config/dev.yaml
extends: base

# 覆盖：使用便宜模型
models:
  default: claude-haiku-3

# 新增：开发专用配置
debug:
  enabled: true
  verbose_logging: true

# 继承：database 配置不变
```

```yaml
# config/prod.yaml
extends: base

# 覆盖：生产优化
database:
  pool_size: 50

realtime:
  adaptive_batching: true
  max_websocket_frame_size: 256

# 继承：models 使用 base 的默认值
```

### Profile 组合
```yaml
# config/profiles/cheap-models.yaml
models:
  default: claude-haiku-3
  fast: claude-haiku-3

# config/profiles/high-performance.yaml
realtime:
  adaptive_batching: true
  max_workers: 32

# 使用时组合
# octopus-agent --config=dev --profile=cheap-models,high-performance
```

### 加载顺序
```
1. config/base.yaml
2. config/{environment}.yaml (dev/test/prod)
3. config/profiles/*.yaml (按顺序合并)
4. 环境变量覆盖 (DATABASE_URL 等)
5. CLI 参数覆盖 (--model=opus)
```

## 实现方案

### 1. ConfigLoader
```python
# runtime/platform/config/config_loader.py
from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class ConfigLayer:
    name: str
    data: dict
    extends: str | None = None

class ConfigLoader:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self._cache: dict[str, ConfigLayer] = {}
    
    def load(
        self,
        environment: str = "dev",
        profiles: list[str] | None = None
    ) -> dict:
        """加载分层配置"""
        
        # 1. 加载 base
        base = self._load_file("base.yaml")
        result = base.data.copy()
        
        # 2. 加载环境配置
        env = self._load_file(f"{environment}.yaml")
        result = self._merge_config(result, env.data)
        
        # 3. 加载 profiles
        if profiles:
            for profile in profiles:
                p = self._load_file(f"profiles/{profile}.yaml")
                result = self._merge_config(result, p.data)
        
        # 4. 环境变量覆盖
        result = self._apply_env_vars(result)
        
        return result
    
    def _merge_config(self, base: dict, overlay: dict) -> dict:
        """深度合并配置"""
        result = base.copy()
        for key, value in overlay.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_config(result[key], value)
            else:
                result[key] = value
        return result
    
    def _load_file(self, filename: str) -> ConfigLayer:
        """加载单个配置文件"""
        if filename in self._cache:
            return self._cache[filename]
        
        path = self.config_dir / filename
        with open(path) as f:
            data = yaml.safe_load(f)
        
        layer = ConfigLayer(
            name=filename,
            data=data.get("config", data),  # 支持 root 或 config key
            extends=data.get("extends")
        )
        
        self._cache[filename] = layer
        return layer
```

### 2. CLI 集成
```python
# runtime/cli.py
@click.command()
@click.option("--config", default="dev", help="Configuration environment")
@click.option("--profile", multiple=True, help="Additional profiles")
def main(config: str, profile: tuple[str, ...]):
    loader = ConfigLoader(Path("config"))
    cfg = loader.load(environment=config, profiles=list(profile))
    
    # 使用配置
    init_app(cfg)
```

### 3. 配置验证
```python
# runtime/platform/config/config_schema.py
from pydantic import BaseModel, Field

class ModelsConfig(BaseModel):
    default: str = Field(..., description="Default model")
    fast: str | None = Field(None, description="Fast model")

class DatabaseConfig(BaseModel):
    url: str = Field(..., description="Database URL")
    pool_size: int = Field(10, ge=1, le=100)

class Config(BaseModel):
    models: ModelsConfig
    database: DatabaseConfig
    # ... 其他配置

# 加载后验证
cfg_dict = loader.load("prod")
cfg = Config(**cfg_dict)  # Pydantic 自动校验
```

## 替代方案

### 方案 A：环境变量 + 模板
```yaml
# config.yaml
models:
  default: ${MODEL_DEFAULT:-claude-sonnet-3.5}
```

**优点**:
- 实现简单
- 符合 12-factor app

**缺点**:
- 无法表达复杂的配置差异
- 环境变量过多难以管理
- 无法组合配置

**结论**: 作为补充，但不能替代分层配置

---

### 方案 B：Python 配置文件
```python
# config/dev.py
from config.base import *

MODEL_DEFAULT = "claude-haiku-3"
DEBUG = True
```

**优点**:
- 灵活（可以写逻辑）
- Python 开发者熟悉

**缺点**:
- 安全风险（执行代码）
- 难以静态分析
- 非 Python 用户不友好

**结论**: 不推荐

---

### 方案 C：DSH 的 Bundle 系统（完整吸收）
```yaml
# bundle.yaml
name: octopus-base
version: 1.0.0
dependencies:
  - cordis-core
  - fs-local
plugins:
  - name: model-router
    config: { ... }
```

**优点**:
- 可分发（npm 包）
- 依赖管理
- 插件化

**缺点**:
- 复杂度高
- 需要包管理器
- 与 Octopus 当前架构不匹配

**结论**: 未来可以考虑，但当前过于复杂

---

## 提议的方案（方案 D）：YAML 分层 + Pydantic 校验 ✅

**优点**:
- 简单易懂（YAML 格式）
- 类型安全（Pydantic 校验）
- 灵活（继承 + 组合）
- 渐进式（向后兼容现有配置）

**缺点**:
- 需要设计合并语义
- 循环依赖检测

## 实施计划

### ✅ Phase 1（已完成 - 2026-08-14）：基础实现
- ✅ 增强 `ConfigLoader` 支持 `extends`
- ✅ 实现深度合并逻辑 (`_deep_merge`)
- ✅ 实现循环引用检测 (`_resolve_extends`)
- ✅ 创建示例配置（base.yaml, dev.yaml, prod.yaml）
- ✅ 编写 12 个单元测试（全部通过）
- ✅ 编写配置分层使用指南

**实施细节**:
- 文件: `runtime/platform/config/loader.py`
- 测试: `tests/unit/platform/config/test_config_extends.py`
- 文档: `docs/config-layering-guide.md`
- 示例: `config/base.yaml`, `config/dev.yaml`, `config/prod.yaml`

**关键特性**:
1. 深度合并：嵌套字典递归合并
2. 多层继承：支持继承链（最多 10 层）
3. 循环检测：防止 A→B→A 循环引用
4. 相对路径：支持 `../base.yaml` 跨目录引用
5. 环境变量：与 `${ENV_VAR}` 插值兼容
6. 向后兼容：现有配置无需修改

### ⏳ Phase 2（下周）：Profile 支持
- [ ] 支持 `--profile` 参数
- [ ] Profile 组合逻辑
- [ ] 配置验证（Pydantic）

### Phase 3（下下周）：迁移现有配置
- [ ] 拆分 `config.local.yaml` → `config/base.yaml` + `config/dev.yaml`
- [ ] 创建常用 profiles
- [ ] 文档更新

### Phase 4（1 个月后）：高级特性
- [ ] 配置热重载
- [ ] 配置 diff 工具
- [ ] 配置模板生成器

## 开放问题

- [ ] **合并语义**：数组合并是 append 还是 replace？
  - 提议：默认 replace，支持 `__merge__: append` 标记

- [ ] **循环依赖**：如何检测 `A extends B extends A`？
  - 提议：加载时追踪依赖链，检测循环

- [ ] **性能**：是否缓存合并后的配置？
  - 提议：启动时合并一次，缓存到内存

- [ ] **向后兼容**：如何支持现有的 `config.local.yaml`？
  - 提议：优先加载 `config/`，fallback 到 `config.local.yaml`

## 成功标准

1. ✅ 开发者可以用 `extends: base.yaml` 快速继承配置
2. ✅ 团队可以共享推荐的配置模板（base/dev/prod）
3. ✅ 配置重复减少（基础配置单一来源）
4. ✅ 新人 onboarding 更快（推荐配置开箱即用）
5. ✅ 向后兼容（现有 `config.local.yaml` 仍可用）

## 实施结果

**代码变更**:
- 修改 `runtime/platform/config/loader.py` (+88 行)
  - 新增 `_deep_merge()` 函数
  - 新增 `_resolve_extends()` 函数
  - 增强 `load_from_yaml()` 支持 `resolve_extends` 参数

**测试覆盖**:
- 新增 `tests/unit/platform/config/test_config_extends.py`
- 12 个测试用例，全部通过
- 覆盖：简单继承、深度合并、多层继承、循环检测、错误处理

**配置模板**:
- `config/base.yaml` - 基础配置（105 行）
- `config/dev.yaml` - 开发环境（21 行，继承 base.yaml）
- `config/prod.yaml` - 生产环境（39 行，继承 base.yaml）

**文档**:
- `docs/config-layering-guide.md` - 完整使用指南

**测试结果**:
```bash
$ .venv/bin/pytest tests/unit/platform/config/test_config_extends.py -v
======================== 12 passed in 0.35s =========================

$ python -c "from runtime.platform.config.loader import load_from_yaml; ..."
Testing config/dev.yaml (extends base.yaml)...
  ✅ dev.yaml loaded successfully
Testing config/prod.yaml (extends base.yaml)...
  ✅ prod.yaml loaded successfully
Testing backward compatibility with config.local.yaml (no extends)...
  ✅ config.local.yaml loaded successfully (backward compatible)
```

## 后续计划

Phase 2-4 保持不变，待团队讨论后推进。

---

**实施日期**: 2026-08-14  
**实施人员**: Claude Opus 5 + User  
**相关文档**: [配置分层使用指南](../../docs/config-layering-guide.md)
