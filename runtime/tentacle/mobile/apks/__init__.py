"""Octopus Mobile 集成子包.

提供 Octopus Mobile（Android 客户端）↔ octopus-agent 之间的桥梁：

- :mod:`skill_export` —— 把 Octopus Mobile 的 BaseTool 导出为 SKILL.md
- :mod:`tool_bridge` —— 工具调用桥接（JSON-RPC envelope）
- :mod:`version` —— Octopus Mobile 端版本兼容矩阵

详见 ``docs/mobile/architecture.md`` 第 2.2 节。
"""
