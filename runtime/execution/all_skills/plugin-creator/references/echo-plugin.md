# Echo 插件接口参考

先定位目标项目中的下列接口；本文中的路径相对于 Echo 项目根目录：

- `runtime/platform/plugins/plugin_base.py`：`ModulePlugin`、`ModuleContext` 与注册接口。
- `runtime/platform/plugins/plugin_hub.py`：发现、加载、停用及卸载。
- `runtime/platform/plugins/plugin_loader.py`：`PluginManifest` 清单模型。
- `runtime/execution/suckers/registry.py`：`Skill` 定义、参数与处理函数契约。
- `runtime/platform/plugins/bundled/github/`：带真实工具注册的现有实现。

## 最小结构

```text
example_plugin/
  plugin.yaml
  __init__.py
```

`plugin.yaml` 示例：

```yaml
name: example_plugin
version: 0.1.0
description: 返回输入文本的字符数
author: echo
provides:
  - example_plugin.skills
config_schema:
  type: object
  properties: {}
```

`__init__.py` 示例（实现前核对当前版本的 Skill 参数接口）：

```python
from runtime.execution.suckers.registry import Skill
from runtime.platform.plugins.plugin_base import ModulePlugin


class ExamplePlugin(ModulePlugin):
    name = "example_plugin"
    version = "0.1.0"

    def register_skills(self):
        if self.ctx is None:
            return
        self.ctx.register_skill(Skill(
            name="example_plugin.count_chars",
            description="统计传入 text 字符串的字符数。",
            trusted_source="plugin://example_plugin",
            handler=self.count_chars,
        ))

    @staticmethod
    def count_chars(text: str = ""):
        return {"count": len(text)}
```

保持目录名、清单名和运行时插件名一致。使用包内相对路径加载资源；持久数据使用宿主的数据目录。只声明真正提供的能力与所需依赖。

清单静态检查可使用 `PluginManifest.model_validate(yaml.safe_load(...))`；它不代替 PluginHub 的依赖、能力或生命周期检查。编译入口文件不会执行插件，适合先检查语法。集成验证使用临时 SkillRegistry 和宿主测试上下文，确认技能可调用、注册项可撤销，再走真实安装流程。

若需要前端页面、MCP 服务或可分发工作台包，继续读取该项目的 `workbench_package.py` 和同类型插件的清单，按实际契约添加资源，避免假设每个插件都必须带这些组件。
