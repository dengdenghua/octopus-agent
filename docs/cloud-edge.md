# 独立云端账号、积分与消息服务

云服务器不运行 Octopus Agent，也不运行萌侠网页或插件。它只运行一个独立的轻量业务服务和一份 SQLite 数据库；Octopus 只是可选的本地消息来源。

## 运行边界

- 云端保存用户账号、登录会话、积分余额与流水、设备、订阅权限和规范化消息。
- 密码使用带随机盐的 scrypt 强哈希，云端不保存明文密码。
- 积分余额和不可变流水在同一个事务中更新，签到、赠送和消费都有幂等业务号。
- 本地萌侠插件读取用户已经能看到的对话，将消息先写入 SQLite 队列。
- 断网时队列继续落盘；恢复后最多每批 100 条自动补传。
- 每台设备生成独立 Ed25519 私钥。私钥只保存在本机权限为 `0600` 的配置文件中。
- 设备先签署一次性 challenge，再换取有效期 15 分钟的 Bearer 令牌。
- 设备被撤销后，即使旧令牌尚未过期，消息接口也会立即拒绝。

## 云端配置

生产部署必须设置独立密钥：

```bash
OCTOPUS_CLOUD_EDGE_TOKEN_SECRET="$(openssl rand -hex 32)"
OCTOPUS_CLOUD_EDGE_ADMIN_KEY="$(openssl rand -hex 32)"
OCTOPUS_CLOUD_REGISTRATION_CODE="$(openssl rand -hex 24)"
```

三个密钥用途独立：签发登录/设备短令牌、后台管理、控制新账号注册。不要互相复用。

2G 小服务器只需启动这个轻量服务（内存上限 512MB）：

```bash
docker compose --env-file .env -f deploy/cloud-edge-compose.yml up -d --build
```

该服务默认只发布到 `127.0.0.1:8090`。用 Caddy 或 Nginx 配置 HTTPS 域名后，再把该域名填入本地“云端连接”面板。不要直接把 8090 明文端口暴露到公网。

账号与积分接口：

- `POST /v1/accounts/register`：凭注册码创建账号。
- `POST /v1/accounts/login`、`/refresh`、`/logout`：登录、轮换刷新会话和退出。
- `GET /v1/account`：读取当前账号。
- `GET /v1/points`、`GET /v1/points/ledger`：读取余额和积分流水。
- `POST /v1/points/check-in`：每日签到；同一天重复提交不会重复加分。
- `POST /v1/points/spend`：带幂等业务号的原子扣分。
- `POST /v1/admin/points/adjust`：后台赠送或扣减积分。
- `PUT /v1/admin/subscription-products/{sku}`：后台定义积分价格、功能和有效期。
- `POST /v1/subscriptions/activate`：积分扣费、流水、订阅和权限在同一事务内生效。
- `GET /v1/subscriptions`：读取当前账号的订阅记录。

设备、订阅与消息接口：

- `POST /api/cloud-edge/pairing-codes`：账号登录后创建十分钟有效的一次性配对码。
- `GET /api/cloud-edge/devices`：列出自己的设备。
- `DELETE /api/cloud-edge/devices/{device_id}`：撤销设备。
- `GET /api/cloud-edge/messages`：读取自己的规范化消息。
- `GET /api/cloud-edge/messages/stream`：SSE 实时消息流，供 Agent、订阅页面和推送服务消费。
- `POST /edge/v1/enroll`：本地设备消耗配对码并登记公钥。
- `POST /edge/v1/challenge/{device_id}` 与 `POST /edge/v1/token`：设备签名换短令牌。
- `POST /edge/v1/messages/batch`：上传去重后的消息批次。

## 本地连接

打开“萌侠消息中心”，点击顶部“云端连接”，填写：

1. HTTPS 云端地址；
2. 云端生成的一次性配对码；
3. 当前设备名称。

连接后顶部状态会显示“云端已同步”或待同步数量。断开连接只移除设备连接配置，不删除本地消息队列。

本地开发允许使用 `http://127.0.0.1` 或 `http://localhost`；非回环地址强制要求 HTTPS。
