# Echo 模型热点（当前来源：Codex 套餐）

同事的客户端执行本地工具，模型请求通过邀请凭证发送给提供方网关。网关使用提供方本机已登录的 ChatGPT/Codex 账号，返回 Responses SSE 事件，不向同事发送登录凭证。此原型不代表套餐跨用户共享获得官方授权，所用套餐端点的兼容性仍可能变化。

## 提供方

更新并重启 Echo 后端，刷新页面。在「设置 → 模型 → Echo 模型热点」打开「共享我的模型」，开启热点，填写接入者名称、有效小时和请求次数上限，创建邀请。邀请凭证仅在创建时显示；需要重新发放时撤销旧邀请。

也可手动启动服务：

```powershell
.\.venv\Scripts\python.exe -m runtime.sensing.gateway.codex_hotspot
```

默认仅监听 `127.0.0.1:8322`，新建服务默认关闭共享。需要本机 Codex 的 ChatGPT 登录，当前读取文件凭证；只使用系统密钥链的登录尚不支持。认证刷新交给原生 Codex App Server，不自动切换到另一个账号或 API 计费。

## 接入方

通过已有 SSH 访问权限建立隧道（将 `用户@提供方主机` 替换为真实地址）：

```sh
ssh -N -L 18322:127.0.0.1:8322 用户@提供方主机
```

在同事自己的 Echo 中打开「设置 → 模型 → Echo 模型热点」，填写上述隧道地址 `http://127.0.0.1:18322/v1` 和邀请凭证，点击「连接并读取模型」，选择模型后点击「添加到 Echo 模型列表」。然后在聊天的模型选择器中选择该来源，即可使用 Echo 自己的会话和本机工具，无需额外启动 Codex 客户端。连接保存在现有自定义模型配置中，重启后仍可使用；也可在该列表测试、编辑或删除。

其他支持 Responses 协议的模型客户端可设置：

- Base URL：`http://127.0.0.1:18322/v1`
- Bearer 凭证：邀请中显示的 token，不能填提供方的 Codex 登录令牌。
- 模型：从该地址的 `GET /models` 获取。
- 请求：`POST /responses`，`stream=true`；每次发送完整 input 历史。

Codex 客户端可使用独立配置目录测试以下 provider 配置，避免覆盖现有工作配置：

```toml
model_provider = "echo_hotspot"

[model_providers.echo_hotspot]
name = "Echo Hotspot"
base_url = "http://127.0.0.1:18322/v1"
env_key = "ECHO_HOTSPOT_TOKEN"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
```

将邀请 token 放入接入方环境变量 `ECHO_HOTSPOT_TOKEN`；模型名称从 `/models` 选择。这里只保证 Responses HTTP 流式接口，尚未验证所有 Codex 客户端功能的兼容性。暂不支持 `/chat/completions`、WebSocket、服务端 compact、后台请求、previous_response_id 或服务端 conversation。

邀请面板新增「复制 Codex 模型配置」，可指定接入方本地隧道端口（默认 18322），复制内容不含邀请凭证。配置关闭客户端的 HTTP 及 SSE 自动重试，避免客户端绕过网关的不重试策略而再次消耗次数。首次合并请使用独立配置目录测试，保留已有模型名称。

## 行为与限制

- 支持 function/custom 工具声明与工具结果转发，工具由接入方客户端执行。拒绝上游托管工具及提供方账号的文件 ID、存储项目引用。
- 邀请可过期或撤销，关闭热点会停止接入；固定最大并发 2。通过隧道连接的接入者仍需要邀请凭证。
- 上限按模型请求次数计算，不是 token 或套餐百分比。失败请求也可能消耗一次邀请次数，网关不自动重试。
- 自行开发的接入端可为每个逻辑模型请求提供独立 `Idempotency-Key`（最多 200 个可见 ASCII 字符）。相同成员重复提交同一标识返回 409，不再次执行、不再次计数；更换内容也不能复用标识。首次请求失败后同样保留记录，避免断线后盲目重跑。此机制不缓存回复正文，也不是结果重放接口；没有该请求头的客户端仍需关闭自身自动重试。
- 请求体最多 2 MiB，响应最多 16 MiB，流式阶段最多 300 秒。认证或额度失败直接报错。
- 用量统计记录上游报告的输入、输出 token，不记录模型请求正文。流中断或上游不报告用量时，token 统计可能不完整。
- 当前主机上已验证真实套餐认证、模型枚举、Responses 流式回复，以及 function 工具调用与客户端回传结果的完整回环；Echo 原生模型分发器也已通过真实本地 TCP 热点获得回复。未完成跨机器及长会话验收。

## 验证记录

2026-09-11，本机真实模型 `gpt-6-astra` 返回 `MODEL_HOTSPOT_OK`，随后请求客户端执行 `echo_probe`，收到客户端提供的工具结果后返回 `MODEL_TOOL_HOTSPOT_OK`。SSE 消费端必须处理 `response.output_item.done` 等事件，不能只依赖 `response.completed.response.output` 包含完整输出。

热点、取消释放并发、邀请限制、工具与账号状态边界及桥接回归合计 17 项测试通过。验证脚本使用临时热点目录，结束后不会留下已启用的共享或同事邀请。

后续独立原生 Codex CLI 验证中，接入端没有提供方登录凭证，仅持邀请 token，可以通过真实 TCP 监听器完成模型往返并正常退出。读取接入端文件的测试被该隔离客户端本地工具策略拒绝，未通过文件读取验收；网关不改变接入方的工具权限或沙箱。跨机器 SSH 及长会话压缩仍待验收，当前不要将该原型视为完整的长会话 Codex 替代服务。

独立 CLI 的纯模型验证返回 `GUEST_MODEL_PROXY_OK`，退出码 0，审计记录一次已完成请求。新增接入配置复制与不含凭证检查的界面测试通过；热点相关后端回归共 15 项通过，覆盖同一请求的并发去重、重启后保留记录及不同成员的请求标识隔离。
