---
type: "AdapterSubsystem"
title: "Adapters · Integrations"
description: "Molili 桥接 · Local auth 路由 · 各家第三方集成的 router proxy。"
tags: ["backend", "adapters"]
tier: "standard"
---
# Adapters · Integrations

> Molili 桥接 · Local auth 路由 · 各家第三方集成的 router proxy。

**Source**: `runtime/adapters/integrations/`

## Modules

| Module | Summary |
| --- | --- |
| `local_auth/config.py` | — |
| `local_auth/router.py` | — |
| `oct/client.py` | oct 账号网关 HTTP 客户端 helpers。 |
| `oct/config.py` | oct 账号网关集成配置。 |
| `oct/links.py` | oct 账号绑定存储:agent actor → oct 网关 JWT + 积分快照。 |
| `oct/router_account.py` | oct 账号管理路由 · /api/account/oct/*。 |
| `oct/router_auth.py` | — |
| `oct/router_proxy.py` | oct LLM 代理路由 · /api/oct/openai/v1/*。 |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `local_auth/config.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def hash_password(plaintext)` | Hash a password using bcrypt with a random salt. |
| func | `def verify_password(plaintext, hashed)` | Verify a plaintext password against a bcrypt or legacy sha256 hash. |
| class | `class LocalAuthConfig(BaseModel)` |  |

### `local_auth/router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_local_auth_router(config, identity_store, clock)` |  |

### `oct/client.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OctClientError(RuntimeError)` |  |
| func | `def is_dead_token(status_code)` | 网关 401 = JWT 失效/未登录 → 需要重新登录。 |
| func | `def is_insufficient_credits(status_code)` | 网关 402 = 积分不足。 |
| func | `def mask_email(email)` |  |
| func | `def post_public(url, body, timeout, http_client)` | 无鉴权 POST(发码/登录)。日志脱敏 email。 |
| func | `def get_auth(url, token, timeout, params, http_client)` | 带 Bearer 的 GET(account/billing 查询)。 |
| func | `def post_auth(url, body, token, timeout, http_client)` | 带 Bearer 的 POST(daily-claim/orders/estimate)。 |

### `oct/config.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OctConfig(BaseModel)` |  |
| func | `def load_oct_config_from_dict(data)` |  |

### `oct/links.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OctLink` |  |
| class | `class OctLinkStore` |  |

### `oct/router_account.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_account_router(config, link_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, http_client)` |  |

### `oct/router_auth.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def actor_from_email(email)` | 从邮箱派生稳定 actor_id。全小写,避免大小写不一致拆成两个身份。 |
| func | `def create_auth_router(config, link_store, identity_store, jwt_secret, jwt_issuer, jwt_audience, http_client)` |  |

### `oct/router_proxy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_proxy_router(config, link_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, http_client)` |  |


## Who imports this

**1** file(s) reference this package:

- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/ui/_app_auth_routers.py`

