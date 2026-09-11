# Google / GitHub 登录配置

登录页顺序为 Google、GitHub、邮箱验证码。本地登录默认关闭，仅用于开发调试。
只有后端同时设置 `ECHO_ENV=development`、`OCTOPUS_DEPLOYMENT_MODE=local`，
并启用 `local_auth.enabled` 时，才显示「开发者登录」且允许本地登录接口。
正式部署不要设置 `ECHO_ENV=development`；即使误保留 `local_auth.enabled=true`，本地登录也会被拒绝。
未配置的第三方登录显示「暂未启用」，不会跳到无效授权页。

在运行后端的环境中配置以下变量，重启后生效（不要把密钥提交到 Git）：

```text
ECHO_AUTH_PUBLIC_URL=https://你的站点域名
ECHO_GOOGLE_CLIENT_ID=Google OAuth 客户端 ID
ECHO_GOOGLE_CLIENT_SECRET=Google OAuth 客户端密钥
ECHO_GITHUB_CLIENT_ID=GitHub OAuth App 客户端 ID
ECHO_GITHUB_CLIENT_SECRET=GitHub OAuth App 客户端密钥
```

本地开发使用 `ECHO_AUTH_PUBLIC_URL=http://localhost:3310`。
站点必须将 `/api` 转发到后端。生产环境使用 HTTPS，并保持原有 JWT 签名密钥稳定。

## Google

在 Google Cloud Console 配置 OAuth 同意屏幕，创建「Web 应用」类型的 OAuth 客户端。
授权重定向 URI：

```text
https://你的站点域名/api/auth/social/google/callback
```

本地测试填 `http://localhost:3310/api/auth/social/google/callback`。
测试状态下添加允许登录的测试用户；公开上线前完成 Google 要求的发布流程。
只申请 `openid email profile`，不申请邮件或云盘权限。

## GitHub

在 GitHub Settings → Developer settings → OAuth Apps 创建应用。
Homepage URL 填站点地址；Authorization callback URL 填：

```text
https://你的站点域名/api/auth/social/github/callback
```

本地测试填 `http://localhost:3310/api/auth/social/github/callback`。
只申请 `read:user user:email`，不申请代码仓库权限；账户需有已验证的主邮箱。

## 行为与验证

- 使用一次性 state、浏览器绑定 Cookie 和 PKCE，授权流程有效期 10 分钟。
- 服务端交换授权码、读取已验证邮箱；提供方 token 不返回浏览器或落盘。
- 登录完成后设置现有 HttpOnly 会话 Cookie，返回原来的站内页面。
- 社交账号以提供方稳定 ID 建立独立身份，不凭相同邮箱自动合并原账号或迁移数据。
- 身份记录存储于数据目录的 `social-identities.sqlite3`，重启时恢复。
- 目前待配置实际 OAuth 应用后，人工完成两个提供方的授权回调验收。
- 当前授权会话存于单个后端进程；多实例部署需粘性会话，或改用共享会话存储。

官方参考：[Google Web Server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)、[GitHub OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)。
