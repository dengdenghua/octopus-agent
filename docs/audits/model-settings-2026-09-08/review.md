# 模型设置精简 — 2026-09-08

模型设置现在先展示默认模型和已连接服务，Codex 账号、引擎参数与诊断工具按需展开。原有模型连接、凭据和引擎配置继续保留。

入口：[本地 Echo](http://localhost:3310/#/workspace/realtime/new) → 设置 → 模型。

## 走查与修改

| 流程 | 原问题 | 完成后的行为 | 验证 |
| --- | --- | --- | --- |
| 默认模型 | 展示连接名称，缺少直接选择入口；引擎解释抢占首屏 | 展示具体模型名称，直接切换；保留准确的连接与模型路由 ID | 同名模型跨连接切换、重新挂载、Auto、既有会话覆盖值的测试通过 |
| 添加连接 | API、本地模型与 Zen 多个按钮并列 | 统一“添加连接”，包含 API、ChatGPT / Codex、Zen、本地扫描 | 菜单实页检查；本地扫描回归通过 |
| API 表单 | 协议、能力开关和推理参数同时铺开；打开表单后仍停在页首 | 常用字段为提供方、模型、Key 和地址；其余放入“高级选项”；打开后滚动并聚焦提供方 | 真实页面聚焦检查；展开保留草稿、取消不提交、增删模型行测试通过 |
| Codex | 独立账号与系统连接混在日常设置中 | 收入“Codex 账号与引擎”；可从添加连接进入账号设置 | 重复打开账号设置、系统来源不被提前切换的测试通过 |
| 高级能力 | 诊断和可选服务占用首屏、提前加载 | 本地图片理解、官方模型、诊断、推荐、多模型协同和兼容矩阵集中收纳；子内容首次展开时加载，收起后保留状态 | 初始不请求 Codex、存储启动、扫描与兼容诊断；各相关回归通过 |
| 窄屏 | 当前“模型”分类可能被横向导航裁切 | 打开、切换分类或改变窗口宽度时，将选中项保持在可见范围 | 390 × 844 实页验证通过，页面无横向溢出 |

## 前后对照

以下两张以相同的 1253 × 912 视口核对布局。界面配色和当前模型来自各次截图时的现有用户状态；本轮没有提交这些偏好的更改。

优化前：

![优化前](<D:/echo agent/docs/audits/model-settings-2026-09-08/01-before.png>)

优化后：

![优化后](<D:/echo agent/docs/audits/model-settings-2026-09-08/09-overview-comparison.png>)

默认模型选择：

![默认模型选择](<D:/echo agent/docs/audits/model-settings-2026-09-08/06-model-picker.png>)

API 表单：

![精简后的 API 表单](<D:/echo agent/docs/audits/model-settings-2026-09-08/05-api-form-final.png>)

高级功能：

![高级功能](<D:/echo agent/docs/audits/model-settings-2026-09-08/08-advanced-after.png>)

窄屏：

![窄屏模型设置](<D:/echo agent/docs/audits/model-settings-2026-09-08/07-mobile-after.png>)

## 验证结果

- 75 项测试通过：模型设置、设置对话框、Codex 控件、模型选择器和 Codex API。
- TypeScript、修改文件的 ESLint、Git diff 空白检查通过。
- 实页控制台未捕获 error；临时视口覆盖已恢复。
- 本地服务在走查中途停止，已使用现有启动脚本恢复前后端，并通过原有本地账号恢复页面会话。
- 本轮验证的是设置交互与配置逻辑，没有实际提交新的 API Key 或发起模型推理请求；不据此判定第三方免费模型的可用性。

## 相关源码

- [模型设置](<D:/echo agent/frontend/src/components/workspace/settings/model-settings-page.tsx>)
- [设置容器与窄屏导航](<D:/echo agent/frontend/src/components/workspace/settings/settings-dialog.tsx>)
- [Codex 设置](<D:/echo agent/frontend/src/components/workspace/coder-engine-control.tsx>)
- [模型选择器](<D:/echo agent/frontend/src/components/workspace/model-picker.tsx>)
- [模型设置回归测试](<D:/echo agent/frontend/src/components/workspace/settings/model-settings-page.test.tsx>)
