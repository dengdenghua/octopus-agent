# Deployment Quickstart

This page is the shortest path from a fresh checkout to a running Octopus
service. Use the longer `docs/deployment.md` when you need Docker, k8s, or
systemd details.

## Python Local

```bash
pip install -e ".[dev,serve,web]"
python -m runtime quickstart --non-interactive
python -m runtime quickstart --non-interactive --serve
```

Open:

```text
http://127.0.0.1:8000
```

The first command creates `config.yaml` if it is missing and runs `doctor`.
The second command repeats the checks and starts the FastAPI service.

## Docker

```bash
cp .env.example .env
cp config.example.yaml config.yaml
docker compose up -d
docker compose logs -f octopus-agent
```

For a commercial/shared deployment, set `execution.deployment_mode` to
`commercial` (or `shared`) in `config.yaml`. `serve` performs a startup check
for a hard process sandbox and refuses to run when bwrap/Seatbelt is missing.
Local development keeps the default `local` mode.

Stop it with:

```bash
docker compose down
```

## Windows Desktop Build (Optional)

The desktop shell is **opt-in**. `frontend/electron/` is the canonical shell;
`extras/desktop/` only retains the PyInstaller backend build helper.

```bash
corepack enable
pnpm --dir frontend install --frozen-lockfile
uv sync --locked --python 3.11.9 --extra desktop-core --extra desktop-build
pnpm --dir extras/desktop backend:build:win
pnpm --dir frontend build
```

正式 Windows 安装器必须由 `windows-code-signing` 受保护环境中的代码签名证书构建；
缺少证书/密码、SHA-256 RFC3161 时间戳或任一 Authenticode 复验都会停止。开发者本地
复现时还需临时设置 `GITHUB_SHA`、`CSC_LINK`（base64 PKCS#12）和
`CSC_KEY_PASSWORD` 后运行 `pnpm --dir frontend electron:build:win`，不得把这些值写入
仓库或 shell profile。推荐直接使用 `build-win.yml`，它会额外生成 SHA-bound artifact 与
`SHA256SUMS`。

The resulting Windows installer contains a fixed PyInstaller backend. First
launch never downloads Python dependencies and never falls back to system
Python or uv; a missing backend aborts startup. Linux AppImage builds are also
enabled on `main`: `build-linux.yml` bundles the pinned backend and Codex
runtime, starts the extracted package, requires `/readyz`, and uploads a
commit-bound CI artifact with checksums. It is not yet attached to the SemVer
release workflow, so treat it as a verified CI artifact rather than a public
Linux release. macOS desktop distribution remains disabled until it has an
equivalent bundled backend, smoke test, signing, and notarization path.

For development (run the backend separately, then Vite + Electron with hot
reload):

```bash
pnpm --dir frontend electron:dev
```

> Self-hosted or developer use — skip this; the web frontend (`frontend/`) is
> the canonical UI and is ~30 MB vs ~200 MB for the desktop bundle.
> See [`frontend/electron/README.md`](../frontend/electron/README.md) and the
> legacy helper notes in [`extras/desktop/README.md`](../extras/desktop/README.md).

## Health Checks

```bash
python -m runtime doctor --config config.yaml
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/status
```

If you do not have an LLM key yet, keep the generated static config and run the
deterministic demos first.
