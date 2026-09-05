# 云分享中继部署

该部署面只负责把桌面端已经清洗过的对话快照放到固定公网域名，并让收件人匿名读取。
它不在云端运行 Agent，也不开放桌面端的本地 `8000/3000` 端口。

固定入口：

- 公共页面：`https://share.echo-age.com/#/share/<opaque-token>`
- 设备写入：`POST /edge/v1/thread-shares`
- 设备列表：`GET /edge/v1/thread-shares`
- 设备撤销：`DELETE /edge/v1/thread-shares/<share-id>`
- 公共页面解析：`POST /api/public/thread-shares/resolve`，JSON body 为
  `{"token":"<opaque-token>"}`
- Cloud Edge 原生解析：`POST /api/v1/public/thread-shares/resolve`
- 本地服务中继（账号鉴权）：`POST/GET /api/cloud-edge/thread-shares`，撤销使用
  `DELETE /api/cloud-edge/thread-shares/<share-id>`

设备写入接口继续使用 Cloud Edge 的短期设备 Bearer token；本地服务中继由 Cloud Edge
校验账号会话或服务凭证；只有公共页面解析接口无需登录。旧版
`GET /api/public/thread-shares/<opaque-token>` 和
`GET /api/v1/public/thread-shares/<opaque-token>` 仅作为迁移兼容，不应再由新客户端生成。
桌面端必须使用服务端返回的绝对 `share_url`，不能用 `window.location.origin`、`Host` 请求头
或 `localhost` 拼接公网链接。

## 1. 准备持久目录与环境变量

```bash
cd /opt/octopus-agent
cp deploy/cloud-edge.env.example .env.cloud-edge
chmod 600 .env.cloud-edge
sudo install -d -m 0750 -o 10001 -g 10001 data/cloud-edge
```

分别生成四个独立值并写入 `.env.cloud-edge`，不要互相复用。第四个
`OCTOPUS_CLOUD_SHARE_RELAY_KEY` 只允许创建、查询和撤销分享，不能访问账号、积分或
其他 Cloud Edge 管理接口：

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 24
openssl rand -hex 32
```

`OCTOPUS_PUBLIC_SHARE_BASE_URL` 必须是无尾斜杠的固定 HTTPS origin。默认保留
30 天、每个 owner 最多 50 条、单快照 1 MiB、全库 512 MiB；演示环境可缩短 TTL，
生产环境应结合磁盘监控和清理任务调整。

启动并确认中继仍只监听回环：

```bash
docker compose --env-file .env.cloud-edge -f deploy/cloud-edge-compose.yml up -d --build
docker compose --env-file .env.cloud-edge -f deploy/cloud-edge-compose.yml ps
curl --fail http://127.0.0.1:8090/readyz
```

`data/cloud-edge` 保存 SQLite、分享快照与撤销/过期状态。升级前至少备份该目录；恢复时
保持 UID/GID `10001:10001` 和 `0750` 权限。不要只备份镜像，也不要把 `/data` 改成
匿名卷。

## 2. 接入 Octopus 网关

在运行本地/私有 Octopus 网关的服务器环境中加入以下配置，然后重启网关。API key 的值
与云端 `OCTOPUS_CLOUD_SHARE_RELAY_KEY` 相同，但变量名不同是为了明确调用方与接收方：

```dotenv
OCTOPUS_PUBLIC_SHARE_RELAY_URL=https://share.echo-age.com
OCTOPUS_PUBLIC_SHARE_RELAY_API_KEY=<与云端分享中继 key 相同>
```

凭证只进入 Python 网关环境，不得写入 `VITE_*`、前端包、二维码或桌面 renderer。未配置
中继时仍支持本机预览，但微信、朋友圈和二维码会明确提示“仅本机可访问”。

网关使用当前租户与账号生成不可逆的 owner scope，并只在服务端请求头中发送；Cloud Edge
据此隔离不同用户的分享配额、列表和撤销权限。即使另一个用户获得 `share_id`，也不能撤销
不属于自己的分享。若改用 `OCTOPUS_PUBLIC_SHARE_RELAY_BEARER_TOKEN`，请求会走
`/edge/v1/thread-shares`，由 Cloud Edge 的设备令牌直接完成 owner 绑定。

## 3. 发布公共页面

Nginx 配置默认从 `/var/www/octopus-share` 提供前端：

```bash
corepack enable
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
sudo install -d -m 0755 /var/www/octopus-share
sudo rsync -a --delete frontend/dist/ /var/www/octopus-share/
```

前端与中继同源，因此公共页面向 `/api/public/thread-shares/resolve` 发 POST 不需要 CORS。
Nginx 保留外部稳定路径，并在代理层转换为 Cloud Edge 的
`/api/v1/public/thread-shares/resolve`。token 只放在 JSON body，不放 URL、查询参数或请求头。
旧 token-path GET 仍能兼容迁移期客户端，但必须尽快淘汰。

## 4. DNS、证书与 Nginx

给 `share.echo-age.com` 配置指向服务器的 A/AAAA 记录。先使用现有 Certbot webroot
`/var/www/certbot` 申请证书，再单独启用分享 vhost：

```bash
sudo install -d -m 0755 /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d share.echo-age.com
sudo cp deploy/share.echo-age.com.nginx.conf /etc/nginx/sites-available/share.echo-age.com.conf
sudo ln -s /etc/nginx/sites-available/share.echo-age.com.conf /etc/nginx/sites-enabled/share.echo-age.com.conf
sudo nginx -t
sudo systemctl reload nginx
```

若证书申请前还没有任何 vhost 承接 ACME challenge，先临时启用一个只包含 80 端口和
`/.well-known/acme-challenge/` 的 server block；证书签发后再启用完整配置。不要停止或
覆盖现有 `ai/api/os.echo-age.com` 配置。

配置只向公网暴露分享所需的窄路径：公共解析、设备 Bearer 写入，以及预留的账号鉴权
`/api/cloud-edge/thread-shares` 中继。Cloud Edge 的其他账号后台和管理接口不会因为这个
域名整体公开。`8090` 保持绑定 `127.0.0.1`，安全组只开放 80/443。

## 5. 日志与隐私

能力 token 等价于匿名读取凭证。新流程的固定 `/resolve` URL 可以记录路由、状态和耗时，
但日志格式不得包含请求体、查询串或 Referer。示例 vhost 使用只记录 method 与 `$uri` 的
`octopus_share_safe` 格式，并对仍在路径中携带敏感值的以下兼容路由显式
`access_log off`：

- 旧 `/api/v1/public/thread-shares/<token>`
- 旧 `/api/public/thread-shares/<token>`
- `/edge/v1/thread-shares/*`
- `/api/cloud-edge/thread-shares/*`
- 预留的 `/s/*`

不得把这些 location 改回包含 `$request`、`$request_uri`、`$args` 或 `$uri` 的
combined/JSON 访问日志。需要观测时记录 `$request_id`、状态码、耗时和固定路由名，不记录
路径参数；应用日志同样不得输出 token、Authorization 或完整请求体。

## 6. 上线核查

```bash
curl --fail https://share.echo-age.com/
curl -i -X POST -H 'Content-Type: application/json' \
  --data '{"token":"not-a-real-token"}' \
  https://share.echo-age.com/api/public/thread-shares/resolve
curl --fail http://127.0.0.1:8090/readyz
sudo nginx -T | grep -F 'server_name share.echo-age.com'
```

第二条应返回受控的 `404`，不应跳转登录页；Nginx access log 最多出现固定 `/resolve`
路径，不能出现测试 token 或请求体。
随后用一台已配对桌面设备创建分享，确认返回 URL 的 origin 固定为
`https://share.echo-age.com`，另一台未登录浏览器可打开，撤销后立即不可读。

示例 Nginx 已分别为匿名读取和管理写入配置按 IP 限速；上线后应结合真实流量调整速率，
并配置磁盘/备份告警、过期清理监控以及 Cloud Edge SQLite 的一致性备份。需要多副本时
先把状态迁移到共享数据库/对象存储；单个本地 SQLite 卷不能直接水平扩容。
