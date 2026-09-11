# Codex 热点：任务角色与模型代理

Echo 的「设置 → 模型」提供「Echo 模型热点」。当前共享来源为提供方本机 Codex 的 ChatGPT 套餐账号；接入方可直接在 Echo 中选择热点模型。不会创建 OpenAI API Key，也不会在套餐失败时切换到 API 计费。

## 提供方

1. 打开设置 → 模型 → Echo 模型热点 → 共享我的模型 → 开启热点。
2. 点击「添加本机 Codex 为远程角色」，可在群聊成员选择器添加 Codex，再 `@Codex` 派发任务。该本机邀请有效七天、上限 1000 次，到期后再次点击可更新。
3. 为每位同事创建独立邀请，设置名称、有效小时和调用次数上限，把连接资料私下交给对应同事。
4. 撤销邀请或关闭热点后，新请求被拒绝，正在执行的请求会停止。提供方电脑及热点服务需要保持运行。

邀请只保存凭证的哈希，连接凭证仅创建时返回。源 Codex 登录凭证始终留在提供方。当前共享上限按调用次数计算，**不是积分、美元或套餐百分比**；模型模式一个任务可能多次请求。失败请求同样计次，避免无限重试。整体最多两个并发执行。

## 同事端建立连接

服务固定监听提供方 `127.0.0.1:8322`，通过 SSH 隧道访问。提供方需已有可用的 SSH 服务和允许同事登录的身份；Echo 不会自动打开防火墙、安装 SSH 或暴露公网服务。

在同事电脑运行（替换用户和主机）：

```sh
ssh -N -L 8322:127.0.0.1:8322 用户@提供方主机
```

两端使用相同端口，确保 A2A Agent Card 公布的地址与隧道一致。

### 群聊任务模式

在同事的 Echo「添加远程角色」中填写邀请中的 `task_url` 和访问凭证。注册后加入群聊，`@Codex` 即可。任务在提供方独立工作目录执行，通过现有 A2A 通道返回进度、回复和文件。不同邀请的任务存储与工作目录分开；不能用一个邀请访问另一个邀请的任务。

### 模型模式

同事本机工具继续在本机执行，只有模型输入发到提供方。在同事 Echo 的「设置 → 模型 → Echo 模型热点」填写隧道地址（使用上方隧道时为 `http://127.0.0.1:8322/v1`）和邀请凭证，读取并添加模型，然后在聊天中选择。其他客户端需要支持 HTTP Responses 流式协议。

Codex 自定义 provider 示例，在同事自己的配置中选择（不要覆盖整个配置文件）：

```toml
model_provider = "echo_hotspot"

[model_providers.echo_hotspot]
name = "Echo Codex Hotspot"
base_url = "http://127.0.0.1:8322/v1"
env_key = "ECHO_CODEX_HOTSPOT_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
```

将邀请凭证放入同事本机进程环境变量 `ECHO_CODEX_HOTSPOT_KEY`，不要提交到项目。保留自己的模型设置，模型需在提供方账号支持范围内；`GET /v1/models` 可列出可用模型。

已支持 `POST /v1/responses`、流式正文、function/custom tool 调用及工具结果输入。服务端不运行这些工具。客户端每次应发送完整 `input` 历史；暂不支持 Chat Completions、WebSocket、`previous_response_id`、服务端 conversation、后台响应或 `/responses/compact`。超过上下文限制时需客户端先整理历史。

## 运行与验证

界面会按需启动独立服务，也可手动运行：

```powershell
.\.venv\Scripts\python.exe -m runtime.sensing.gateway.codex_hotspot
```

状态及请求审计保存在 `~/.octopus/codex-hotspot`；审计记录成员、请求结果和可获得的 token 用量，不保存模型代理的提示词或回答。任务模式的文件与对话按成员单独持久保存。所有者控制凭证不会下发给受邀成员。

模型转发使用本机登录对应的 Codex 订阅后端，这是兼容性实现，不能据此推断个人套餐已获准跨人共享。源账号权限与套餐限制仍然有效；接口变动或登录过期会明确失败，不自动更换账号或计费方式。

实现依据：[Codex 认证](https://learn.chatgpt.com/docs/auth)、[App Server](https://learn.chatgpt.com/docs/app-server)。


## OpenCode 与其他客户端

入口现显示「共享我的模型」。模型服务目前由 Codex 套餐提供，兼容 Responses 的客户端均可配置连接；已实测 OpenCode 官方引擎调用成功。创建邀请后，填写模型 ID 和同事端隧道端口，点击「复制 OpenCode 模型配置」，合并到 opencode.json。配置使用 @ai-sdk/openai（Responses），不要换成仅使用 Chat Completions 的 @ai-sdk/openai-compatible。邀请凭证放在同事端 ECHO_HOTSPOT_TOKEN 环境变量。

OpenCode 会自动发送 max_output_tokens；套餐接口不支持此参数，热点会移除它，输出长度由上游模型控制。OpenCode 的客户端重试仍可能消耗额外邀请次数。

「远程角色引擎」可选择 Codex 或 OpenCode，再创建邀请或添加本机角色。OpenCode 角色复用原生隔离会话，当前使用实时验证免费价格的 Zen big-pickle，仅支持对话，不开放文件和工具操作。它可按现有远程角色流程加入群聊并通过 @ 调用。邀请码继续实行过期、撤销、次数和上下文隔离。选择 OpenCode 开启角色服务不要求 Codex 登录，但使用模型热点仍需要 Codex 登录。

这不代表已共享 OpenCode Go / Zen 付费账户，也不代表 WorkBuddy 积分可转换为模型额度。其他上游账户的模型共享仍需各自的提供方适配。

参考：[OpenCode 官方自定义提供方配置](https://opencode.ai/docs/providers)。
