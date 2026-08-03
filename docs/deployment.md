# 部署 · octopus-agent

一份**最小可用**的部署指南。

## 🚀 一键部署速查

| 场景 | 命令 | 需要什么 |
|---|---|---|
| **开发单机** | `make up` | docker + docker compose |
| **生产全栈**（Agent + Redis HA + Jaeger + Grafana） | `make up-full` | 同上 |
| **k8s 集群** | `make k8s-apply` | kubectl + kustomize + 集群 |
| **裸金属 / VPS** | 见 [§5 systemd](#5-裸金属--vps--systemd) | systemd · Python 3.11+ |
| **Python 直接跑** | `pip install -e ".[serve]"` + `octopus-agent serve` | Python 3.11+ |

一键停：`make down` · 看日志：`make logs` · 重启：`make restart`

---

## 五种跑法

### 1. Python 虚拟环境（开发 / 单机实验）

```bash
pip install -e ".[serve]"
octopus-agent serve --config config.yaml --port 8000
```

需要反思学习 / MCP / Anthropic？按需加 extras：
```bash
pip install -e ".[serve,anthropic,mcp,web,tracing]"
```

### 2. Docker（单容器）

```bash
docker build -t octopus-agent .

docker run --rm -p 127.0.0.1:8000:8000 \
    -v $(pwd)/data:/data \
    -v $(pwd)/config.yaml:/etc/octopus/config.yaml:ro \
    -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
    octopus-agent
```

### 3. docker compose · 单容器（推荐开发）

```bash
make up                     # 等价于下面三行
# cp config.example.yaml config.yaml
# cp .env.example .env
# docker compose up -d
```

### 4. docker compose · 全栈（推荐生产）

`docker-compose.full.yml` 额外拉起 Redis（跨机 HA · Hearts RedisCoordinator）+ Jaeger（OTel trace）+ Prometheus + Grafana：

```bash
make up-full
# →  Agent    http://localhost:8000/
# →  Jaeger   http://localhost:16686/
# →  Grafana  http://localhost:3000/   (admin / admin)
```

Agent 容器自动读 `OCTOPUS_HEARTS_REDIS_URL=redis://redis:6379/0` · multi-replica 场景下 `RedisCoordinator` 直接可用。

### 5. 裸金属 / VPS · systemd

```bash
# 1. 装代码（从 PyPI 或源码）
sudo useradd -r -s /usr/sbin/nologin octopus
sudo mkdir -p /opt/octopus-agent /var/lib/octopus /etc/octopus
sudo chown -R octopus:octopus /opt/octopus-agent /var/lib/octopus /etc/octopus
sudo -u octopus python -m venv /opt/octopus-agent/.venv
sudo -u octopus /opt/octopus-agent/.venv/bin/pip install "octopus-agent[serve]"

# 2. 放配置
sudo cp config.example.yaml /etc/octopus/config.yaml
sudo cp .env.example /etc/octopus/octopus.env
sudo chmod 600 /etc/octopus/octopus.env

# 3. 装 unit · 开机自启
sudo cp deploy/octopus-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now octopus-agent

# 4. 管理
sudo systemctl status octopus-agent
sudo journalctl -u octopus-agent -f
```

内置安全加固：`NoNewPrivileges` / `ProtectSystem=strict` / `MemoryDenyWriteExecute` / `CapabilityBoundingSet=`（全砍）/ `MemoryMax=2G`。

### 6. Kubernetes（跨机生产）

```bash
make k8s-apply     # 等价于 kubectl apply -k deploy/k8s/
make k8s-status    # 看命名空间里所有资源
make k8s-delete    # 卸载
```

`deploy/k8s/` 里含：
- `namespace.yaml` · `configmap.yaml`（默认 config）· `secret.yaml`（模板 · 填 API key）
- `pvc.yaml` · `redis.yaml`（Hearts 后端）· `deployment.yaml` · `service.yaml` · `ingress.yaml`
- `kustomization.yaml` · 用 kustomize 统一 apply

多副本自动用 `RedisCoordinator` 做 leader 选举（反思 / 调度类单点任务 leader 跑 · 其他副本服务请求）。详见 `deploy/k8s/README.md`。

访问：
- `http://localhost:8000/`           · Web dashboard
- `http://localhost:8000/api/stream` · Server-Sent Events · journal 事件实时推送
- `http://localhost:8000/v1/chat/completions` · OpenAI-compat API
- `http://localhost:8000/api/progress` · 所有 task 的当前进度

## 数据持久化

`/data`（容器内）映射到宿主 `./data` · 包含：
- `events.jsonl` · journal（如 config.journal_file 指向它）
- `kg.sqlite3` · KG 跨 session 持久化（用 `SqliteKnowledgeGraph` 时）
- 其他 agent 运行产出

**备份**：`./data` 是整个 agent 状态的单一来源 · tar 打包即可。

## 运维

### 健康检查

```bash
curl http://localhost:8000/api/health    # 聚合健康（skills/agents/channels/groups/journal_events）
curl http://localhost:8000/api/status    # 环境能力盘点（extras 装了哪些）
```

docker compose 自带 healthcheck · 30s 一次 · `docker-compose.full.yml` 命中 `/api/health`。
k8s deployment 的 liveness/readiness probe 也用 `/api/health`。

### 查 scheduler 状态

进程退出时 stderr 会打印每个 periodic task 的 success/error 计数。实时查：
```bash
docker logs octopus-agent | grep scheduler
```

### 热更新 config

```bash
# 改 config.yaml 后
docker compose restart octopus-agent
```

### 消费 OpenAI-compat 端点

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")
resp = client.chat.completions.create(
    model="octopus-agent",
    messages=[{"role": "user", "content": "list the current dir"}],
)
print(resp.choices[0].message.content)
```

## 资源占用参考

| 组件 | CPU | RSS |
|---|---|---|
| 基础 `serve`（空闲）| < 1% | ~80 MB |
| 每个并发 plan+execute | 10-30% 脉冲 | +20-50 MB 峰值 |
| MCP persistent client | < 1% | +30 MB per server |
| BackgroundRunner（intel 3600s）| < 1% 平均 · 抓时脉冲 | 取决于 fetch_top_n |

## 安全要点

- `ANTHROPIC_API_KEY` 等密钥通过 env 注 · 不要入 config.yaml
- 不可信 skill 强制走 `SubprocessBackend`（Unix 下加 RLIMIT_AS / RLIMIT_CPU）
- 把 `/data` 设独立 volume · 不与源代码目录共享
- 公开部署请在外层加 nginx / cloudflare · 本项目未内置 auth

## 生产检查清单

- [ ] `config.yaml` 用真 planner（非 mock）
- [ ] `ANTHROPIC_API_KEY` 或等价 provider 已设
- [ ] `immunity.trusted_sources` 白名单配齐
- [ ] `immunity.unknown_policy=quarantine`（或 reject）
- [ ] `budget.max_usd` 合理（单 task 上限）
- [ ] `ink` CircuitBreaker 参数按负载调（如需在代码里开）
- [ ] journal 目录备份策略 · cron tar 或挂云盘
- [ ] `/api/status` 监控接入
