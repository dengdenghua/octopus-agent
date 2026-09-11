# 官方模型与自定义 API 共享接入

用户要求：官方模型、自定义 API 是共享来源，Codex 和 OpenCode 均可使用；设置页和输入框读取同一份官方目录。

## 实现

- `loadModels` 合并自定义连接与官方 `/api/oct/openai/v1/models`；设置页 `OfficialModelsSection` 改用同一个 `useModels` 缓存，不再独立请求和维护列表。
- 官方模型使用 `official/<id>`，自定义连接保留 `octopus-custom-model:v1:` 唯一标识。两个端点使用相同模型名时仍保留准确来源。
- OpenCode 菜单增加官方模型、自定义 API 来源，并保留 Zen / Go；Codex 菜单区分官方、自定义 API、ChatGPT 订阅。
- 共享调用经宿主的 ScopedResponsesProxy。OpenCode 注入临时本地代理地址和回合凭据，不接收上游账号 Key；共享代理进程不进入热复用池，随回合关闭。
- SharedExecutionRouter 将官方请求送入账号感知的官方服务路由，自定义请求送入准确的已配置路由；官方服务不可用时不回退自定义 API。
- Codex 保留自定义连接的唯一选择标识，不提前降成可能重名的上游模型名称。
- 补齐 Responses SSE 的 item/content 开始、增量、结束顺序，让 OpenCode 的 SDK 能正确消费；沿用已有代理整轮响应适配，本轮没有实现上游 token 实时转发。

## 验证与边界

- 前端 86 项测试通过，包含同目录读取与 OpenCode 官方/API 选择；TypeScript、变更文件 ESLint、生产构建通过。
- 后端 120 项测试通过，包含模型选择隔离、作用域凭据、Responses 协议、Codex 执行与 OpenCode 生命周期；不变量检查 0 项问题。
- 本机真实 OpenCode 进程通过本地模拟模型代理收到 `shared-proxy-ok` 和成功回执；Codex Responses 回归包含本机真实 App Server 文本及工具循环。
- 未发送真实计费模型请求。实际官方上游授权、余额及供应商行为不能仅由本地模拟测试证明。
- 后端重启后预览要求重新登录，已请用户恢复登录；当前实际页面验收尚未完成。
