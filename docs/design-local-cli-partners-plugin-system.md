# 本地 CLI 伙伴插件化架构设计

## 问题

当前硬编码方式维护成本高：
- 每个 CLI 的参数硬编码在 `build_partner_argv()`
- 新增 CLI 需要修改核心代码
- 版本更新需要跟踪每个 CLI 的 API 变化
- 错误诊断逻辑混杂在一起

```python
# 当前硬编码方式（不可扩展）
def build_partner_argv(partner_id, command, prompt, model=None):
    if partner_id == "claude-code":
        return [command, "-p", *(["--model", m] if m else []), prompt]
    if partner_id == "codex-cli":
        return [command, "exec", *(["-m", m] if m else []), "--skip-git-repo-check", prompt]
    if partner_id == "opencode-cli":
        return [command, "run", *(["-m", m] if m else []), "--auto", prompt]
    # ... 7+ more hardcoded cases
    return None
```

## 解决方案：插件化架构

### 核心理念

1. **声明式配置**：每个 CLI 用 JSON/YAML 描述自己的参数
2. **可插拔**：放在独立目录，自动发现
3. **开发者维护**：每个 CLI 的维护者负责自己的插件
4. **向后兼容**：保留内置支持，但优先加载外部插件

---

## 架构设计

### 1. 插件目录结构

```
runtime/execution/agents/local_partners/
├── __init__.py
├── plugin_loader.py          # 插件加载器
├── base.py                    # 基类和接口
├── builtin/                   # 内置插件（向后兼容）
│   ├── claude_code.json
│   ├── codex_cli.json
│   ├── opencode_cli.json
│   ├── trae_cli.json
│   ├── qoder_cli.json
│   └── codebuddy_cli.json
└── custom/                    # 用户自定义插件
    └── my_custom_cli.json
```

### 2. 插件配置格式（JSON Schema）

```json
{
  "$schema": "https://octopus.ai/schemas/local-partner-plugin-v1.json",
  "version": "1.0",
  "partner_id": "opencode-cli",
  "display_name": "OpenCode CLI",
  "command": "opencode",
  
  "detection": {
    "check_command": ["opencode", "--version"],
    "version_regex": "^(\\d+\\.\\d+\\.\\d+)$",
    "min_version": "1.18.0"
  },
  
  "invocation": {
    "subcommand": "run",
    "args_template": [
      "{command}",
      "run",
      {"if": "model", "then": ["-m", "{model}"]},
      "--auto",
      {"if": "format_json", "then": ["--format", "json"]},
      "{prompt}"
    ],
    "stdin": null,
    "timeout_seconds": 240,
    "shell": false
  },
  
  "model": {
    "supports_custom_model": true,
    "model_flag": "-m",
    "model_format": "{provider}/{model}",
    "default_models": [
      "opencode/big-pickle",
      "opencode/deepseek-v4-flash-free"
    ]
  },
  
  "auth": {
    "required": false,
    "check_command": ["opencode", "providers", "list"],
    "logged_in_pattern": "\\d+ credentials",
    "login_hint": "OpenCode 使用免费模型，无需登录"
  },
  
  "error_patterns": [
    {
      "pattern": "Unexpected server error",
      "kind": "server_error",
      "title": "OpenCode 服务器错误",
      "hint": "请检查网络连接或稍后重试"
    },
    {
      "pattern": "Unknown model",
      "kind": "invalid_model",
      "title": "不支持的模型",
      "hint": "运行 `opencode models` 查看可用模型"
    }
  ],
  
  "capabilities": {
    "supports_stdin_prompt": false,
    "supports_auto_approve": true,
    "supports_output_format": true,
    "supports_session_continuation": true,
    "max_prompt_length": 100000
  }
}
```

### 3. Python 插件类（可选，高级用途）

对于需要复杂逻辑的 CLI，支持 Python 插件：

```python
# runtime/execution/agents/local_partners/custom/my_cli.py
from runtime.execution.agents.local_partners.base import LocalPartnerPlugin

class MyCustomCLIPlugin(LocalPartnerPlugin):
    """Custom plugin for MyCustom CLI."""
    
    partner_id = "mycustom-cli"
    display_name = "MyCustom CLI"
    command = "mycustom"
    
    def build_argv(self, prompt: str, model: str | None = None, **kwargs) -> list[str]:
        """Build command line arguments."""
        argv = [self.command, "exec"]
        
        # Custom logic for model handling
        if model:
            provider, model_name = model.split("/", 1)
            argv.extend(["--provider", provider, "--model", model_name])
        
        # Custom prompt preprocessing
        if len(prompt) > 10000:
            # Split long prompts
            prompt = self._truncate_prompt(prompt, 10000)
        
        argv.append(prompt)
        return argv
    
    def check_ready(self) -> tuple[bool, str | None]:
        """Check if CLI is ready to use."""
        # Custom readiness check
        result = subprocess.run([self.command, "status"], capture_output=True)
        if "authenticated" not in result.stdout.decode():
            return False, "请先运行 `mycustom login` 登录"
        return True, None
    
    def diagnose_failure(self, exit_code: int, stdout: str, stderr: str) -> dict:
        """Diagnose specific failure modes."""
        if "quota exceeded" in stderr:
            return {
                "kind": "quota_exceeded",
                "title": "API 配额已用完",
                "hint": "请检查你的订阅状态或等待配额重置",
            }
        return super().diagnose_failure(exit_code, stdout, stderr)
```

### 4. 插件加载器

```python
# runtime/execution/agents/local_partners/plugin_loader.py
import json
from pathlib import Path
from typing import Any

class LocalPartnerPluginRegistry:
    """Registry for local CLI partner plugins."""
    
    def __init__(self):
        self._plugins: dict[str, dict[str, Any]] = {}
        self._plugin_dir = Path(__file__).parent
        self._load_builtin_plugins()
        self._load_custom_plugins()
    
    def _load_builtin_plugins(self):
        """Load built-in plugins from builtin/ directory."""
        builtin_dir = self._plugin_dir / "builtin"
        if builtin_dir.exists():
            for plugin_file in builtin_dir.glob("*.json"):
                self._load_json_plugin(plugin_file, source="builtin")
    
    def _load_custom_plugins(self):
        """Load custom plugins from custom/ directory."""
        custom_dir = self._plugin_dir / "custom"
        if custom_dir.exists():
            for plugin_file in custom_dir.glob("*.json"):
                self._load_json_plugin(plugin_file, source="custom")
            
            # Also load Python plugins
            for plugin_file in custom_dir.glob("*.py"):
                if plugin_file.stem != "__init__":
                    self._load_python_plugin(plugin_file)
    
    def _load_json_plugin(self, path: Path, source: str):
        """Load a JSON plugin configuration."""
        with open(path) as f:
            config = json.load(f)
        partner_id = config["partner_id"]
        config["_source"] = source
        config["_path"] = str(path)
        self._plugins[partner_id] = config
    
    def _load_python_plugin(self, path: Path):
        """Load a Python plugin module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find plugin class
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, LocalPartnerPlugin) and 
                    attr != LocalPartnerPlugin):
                    plugin_instance = attr()
                    self._plugins[plugin_instance.partner_id] = {
                        "_type": "python",
                        "_instance": plugin_instance,
                        "_path": str(path),
                    }
    
    def get(self, partner_id: str) -> dict[str, Any] | None:
        """Get plugin configuration by partner_id."""
        return self._plugins.get(partner_id)
    
    def list_all(self) -> list[dict[str, Any]]:
        """List all registered plugins."""
        return list(self._plugins.values())
    
    def build_argv(
        self, 
        partner_id: str, 
        command: str, 
        prompt: str,
        model: str | None = None,
        **kwargs
    ) -> list[str] | None:
        """Build argv for a partner using its plugin."""
        plugin = self.get(partner_id)
        if not plugin:
            return None
        
        # Python plugin
        if plugin.get("_type") == "python":
            instance = plugin["_instance"]
            return instance.build_argv(prompt, model=model, **kwargs)
        
        # JSON plugin
        return self._build_argv_from_template(plugin, command, prompt, model, **kwargs)
    
    def _build_argv_from_template(
        self,
        plugin: dict,
        command: str,
        prompt: str,
        model: str | None,
        **kwargs
    ) -> list[str]:
        """Build argv from JSON template."""
        template = plugin["invocation"]["args_template"]
        argv = []
        
        for item in template:
            if isinstance(item, str):
                # Simple string replacement
                value = item.format(
                    command=command,
                    prompt=prompt,
                    model=model or "",
                )
                if value:  # Skip empty strings
                    argv.append(value)
            
            elif isinstance(item, dict):
                # Conditional inclusion
                if item.get("if") == "model" and model:
                    for subitem in item["then"]:
                        argv.append(subitem.format(model=model))
                elif item.get("if") == "format_json" and kwargs.get("format") == "json":
                    argv.extend(item["then"])
        
        return argv

# Global registry instance
_registry = LocalPartnerPluginRegistry()

def get_plugin_registry() -> LocalPartnerPluginRegistry:
    """Get the global plugin registry."""
    return _registry
```

### 5. 更新 local_partner_bridge.py

```python
# runtime/execution/agents/local_partner_bridge.py
from runtime.execution.agents.local_partners.plugin_loader import get_plugin_registry

def build_partner_argv(
    partner_id: str,
    command: str,
    prompt: str,
    model: str | None = None,
    adapter_notes: list[str] | tuple[str, ...] = (),
) -> list[str] | None:
    """Build argv using plugin system (with fallback to legacy hardcoded logic)."""
    
    prompt_arg = build_partner_prompt(prompt, adapter_notes=adapter_notes)
    
    # Try plugin system first
    registry = get_plugin_registry()
    argv = registry.build_argv(partner_id, command, prompt_arg, model=model)
    if argv:
        return argv
    
    # Fallback to legacy hardcoded logic (for backward compatibility)
    m = _clean_model(model)
    if partner_id == "claude-code":
        return [command, "-p", *(["--model", m] if m else []), prompt_arg]
    # ... (keep existing hardcoded logic as fallback)
    
    return None
```

---

## 优势

### 1. 低维护成本
- ✅ 新增 CLI：只需添加 JSON 文件
- ✅ 参数变化：编辑配置，无需改代码
- ✅ 社区贡献：用户提交插件 PR

### 2. 灵活性
- ✅ JSON 插件：简单 CLI，声明式配置
- ✅ Python 插件：复杂逻辑，完全控制
- ✅ 混合模式：内置 + 自定义

### 3. 可发现性
```bash
# 列出所有已安装的 CLI 伙伴
octopus partner list

# 输出：
# ✅ opencode-cli (builtin) - OpenCode CLI v1.18.18
# ✅ codebuddy-cli (builtin) - CodeBuddy CLI v2.124.0
# ⚠️ claude-code (builtin) - Claude Code (未登录)
# ✅ mycustom-cli (custom) - MyCustom CLI v1.0.0
```

### 4. 向后兼容
- 保留现有硬编码逻辑作为 fallback
- 逐步迁移到插件系统
- 不影响现有用户

---

## 迁移路径

### 阶段 1：基础设施（1-2 天）
1. 创建插件目录结构
2. 实现 `LocalPartnerPlugin` 基类
3. 实现 `LocalPartnerPluginRegistry`
4. 更新 `build_partner_argv()` 使用插件系统

### 阶段 2：内置插件（2-3 天）
1. 将现有 7 个 CLI 转为 JSON 插件
2. 测试每个插件
3. 保留 hardcoded 逻辑作为 fallback

### 阶段 3：增强功能（1-2 天）
1. 实现 `octopus partner` 命令
2. 添加插件验证
3. 改进错误诊断

### 阶段 4：文档和示例（1 天）
1. 编写插件开发指南
2. 提供示例插件
3. 更新用户文档

---

## JSON 插件示例

### OpenCode CLI (完整)
```json
{
  "version": "1.0",
  "partner_id": "opencode-cli",
  "display_name": "OpenCode CLI",
  "command": "opencode",
  "detection": {
    "check_command": ["opencode", "--version"],
    "version_regex": "^(\\d+\\.\\d+\\.\\d+)$",
    "min_version": "1.18.0"
  },
  "invocation": {
    "args_template": [
      "{command}",
      "run",
      {"if": "model", "then": ["-m", "{model}"]},
      "--auto",
      "{prompt}"
    ],
    "timeout_seconds": 240
  },
  "model": {
    "supports_custom_model": true,
    "model_flag": "-m",
    "default_models": ["opencode/big-pickle"]
  },
  "auth": {"required": false}
}
```

### CodeBuddy CLI (修复)
```json
{
  "version": "1.0",
  "partner_id": "codebuddy-cli",
  "display_name": "CodeBuddy CLI",
  "command": "codebuddy",
  "invocation": {
    "args_template": [
      "{command}",
      "-p",
      {"if": "model", "then": ["-m", "{model}"]},
      "-y",
      "--output-format",
      "text",
      "{prompt}"
    ]
  }
}
```

### Claude Code (带登录检查)
```json
{
  "version": "1.0",
  "partner_id": "claude-code",
  "display_name": "Claude Code",
  "command": "claude",
  "invocation": {
    "args_template": [
      "{command}",
      "-p",
      {"if": "model", "then": ["--model", "{model}"]},
      "{prompt}"
    ]
  },
  "auth": {
    "required": true,
    "check_command": ["claude", "-p", "test"],
    "logged_in_pattern": "^((?!Not logged in).)*$",
    "login_hint": "请运行 `claude` 然后执行 `/login` 登录"
  }
}
```

---

## 用户体验

### 开发者：添加新 CLI
```bash
# 1. 创建插件配置
cat > ~/.octopus/agents/local_partners/custom/my_cli.json << 'EOF'
{
  "version": "1.0",
  "partner_id": "my-cli",
  "display_name": "My Custom CLI",
  "command": "mycli",
  "invocation": {
    "args_template": [
      "{command}",
      "exec",
      "--yes",
      "{prompt}"
    ]
  }
}
EOF

# 2. 重启 Octopus（或热重载）
octopus restart

# 3. 验证
octopus partner list
# ✅ my-cli (custom) - My Custom CLI
```

### 最终用户：使用 CLI 伙伴
```bash
# 列出可用伙伴
octopus partner list

# 检查特定伙伴状态
octopus partner check opencode-cli
# ✅ OpenCode CLI v1.18.18
# ✅ 命令可用: /Users/user/.opencode/bin/opencode
# ✅ 认证状态: 无需认证
# ✅ 测试运行: 成功

# 测试伙伴
octopus partner test opencode-cli "echo hello"
# > build · big-pickle
# $ echo hello
# hello
# ✅ 测试成功 (耗时: 2.3s)
```

---

## 总结

### 当前问题
- ❌ 硬编码，维护成本高
- ❌ 新增 CLI 需要改核心代码
- ❌ 每个 CLI 的特性混杂在一起

### 插件化方案
- ✅ 声明式配置（JSON）
- ✅ 可插拔（custom/ 目录）
- ✅ 开发者自维护
- ✅ 向后兼容
- ✅ 易于测试和调试

### 工作量估算
- 基础设施：1-2 天
- 迁移现有 CLI：2-3 天
- 增强功能：1-2 天
- 文档：1 天
- **总计：5-8 天**

要我开始实现插件化系统吗？
