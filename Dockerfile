# syntax=docker/dockerfile:1.7
# octopus-agent · 多阶段构建
# 阶段 1: 固定 Node manifest → Vite 构建前端
# 阶段 2: 固定 uv + Python manifest → uv.lock 安装后端依赖
# 阶段 3: 同一 Python manifest → 运行时（最小镜像）
#
# 构建:
#   docker build -t octopus-agent .
#
# 本地启动（必须显式提供已启用认证的配置）:
#   docker run --rm -p 127.0.0.1:8000:8000 \
#     -v $(pwd)/config.yaml:/etc/octopus/config.yaml:ro octopus-agent
# 生产部署（持久化 + 配置）:
#   docker run --rm -p 127.0.0.1:8000:8000 \
#     -v $(pwd)/data:/data \
#     -v octopus-resources:/app/resources \
#     -v $(pwd)/config.yaml:/etc/octopus/config.yaml:ro \
#     -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
#     octopus-agent

# ═══════════════════════════════════════════════════════════
# 阶段 1 · webui-builder · Vite + React 前端构建
# ═══════════════════════════════════════════════════════════

FROM node:22.23.2-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS webui-builder

WORKDIR /webui

# 利用 Docker 层缓存: 先复制清单 + pnpm 锁文件 -> 安装依赖 -> 再复制源码
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN corepack enable && pnpm install --frozen-lockfile

# 源码变更不影响依赖缓存层
COPY frontend/ ./
# The Vite closeBundle guard proves the historical public pet assets are byte
# identical to their canonical Godot sources before omitting them from dist.
# Copy only those two authoring sources into this throw-away builder stage;
# they are not copied into the final runtime image.
COPY pet-sidecar/models/octopus/octopus.fbx /pet-sidecar/models/octopus/octopus.fbx
COPY pet-sidecar/models/character_rigged_clean.glb /pet-sidecar/models/character_rigged_clean.glb

RUN pnpm run build
# 产物在 /webui/dist · 运行时阶段复制到 /app/webui


# ═══════════════════════════════════════════════════════════
# 阶段 2 · py-builder · uv.lock 安装后端依赖
# ═══════════════════════════════════════════════════════════

FROM ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9 AS uv
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS py-builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/install \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /build

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md MANIFEST.in LICENSE NOTICE skills.lock.json ./
COPY runtime/ ./runtime/
COPY tools/ ./tools/
COPY octopus_runtime/ ./octopus_runtime/

# 只从提交的 uv.lock 解析并安装。--locked 使 pyproject/lock 漂移直接失败，
# --no-sources 禁止本地 tool.uv.sources 在发布镜像中替换 registry 来源。
RUN uv sync --locked --no-dev --no-editable --no-sources \
    --python /usr/local/bin/python \
    --extra serve --extra tracing --extra web --extra hearts-redis


# ═══════════════════════════════════════════════════════════
# 阶段 3 · runtime · 最小运行时镜像
# ═══════════════════════════════════════════════════════════

FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/install/bin:${PATH}" \
    OCTOPUS_DEPLOYMENT_MODE=production \
    OCTOPUS_DATA_DIR=/data \
    OCTOPUS_CONFIG=/etc/octopus/config.yaml \
    OCTOPUS_WEBUI_DIST=/app/webui \
    OCTOPUS_RESOURCES_DIR=/app/resources

# Strict/shared deployments need a real process sandbox. Bubblewrap is the
# preferred Linux backend; startup/CI still executes a real probe because a
# host may disable user namespaces, in which case Landlock >= 5.13 is the
# fail-closed fallback.  Install the exact Debian security build directly;
# TARGETARCH selects an independently verified official package hash.
ARG TARGETARCH
RUN set -eux; \
    case "${TARGETARCH}" in \
      amd64) bwrap_sha256="3cc9134a3286ad01a323dcd924ba123eb634cefaeec82d774257e06308aeaadb" ;; \
      arm64) bwrap_sha256="d044ba1d7961d835669035fcd1e11121f1dc960a1a2e1c6489a93ea44e083557" ;; \
      *) echo "unsupported TARGETARCH for bubblewrap: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    bwrap_url="https://security.debian.org/debian-security/pool/updates/main/b/bubblewrap/bubblewrap_0.8.0-2+deb12u1_${TARGETARCH}.deb"; \
    python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' \
      "${bwrap_url}" /tmp/bubblewrap.deb; \
    echo "${bwrap_sha256}  /tmp/bubblewrap.deb" | sha256sum --check --strict; \
    dpkg --install /tmp/bubblewrap.deb; \
    test "$(dpkg-query --show --showformat='${Version}' bubblewrap)" = "0.8.0-2+deb12u1"; \
    rm /tmp/bubblewrap.deb

RUN groupadd --gid 10001 octopus && \
    useradd --uid 10001 --gid 10001 --home-dir /data --shell /usr/sbin/nologin --no-create-home octopus && \
    mkdir -p /data /etc/octopus /app/webui /app/resources && \
    chown -R octopus:octopus /data /etc/octopus /app

# 只复制已安装的依赖（不含构建工具链）
COPY --from=py-builder  /install     /install
COPY --from=webui-builder /webui/dist /app/webui

# 运行时资源目录 · planner / registry-managed skills / prompts / protocols。
# production 模式只使用随构建发布的 immutable catalog；slug-only lock 仅供本地模式刷新。
COPY agents/    /app/resources/agents/
COPY skills/    /app/resources/skills/
COPY skills.lock.json /app/resources/skills.lock.json
COPY prompts/   /app/resources/prompts/
COPY protocols/ /app/resources/protocols/
COPY teams/     /app/resources/teams/
COPY config.example.yaml /etc/octopus/config.example.yaml
RUN chown -R octopus:octopus /app/resources /etc/octopus

USER octopus
WORKDIR /data

EXPOSE 8000

# 入口点支持任意子命令:
#   docker run octopus-agent octopus-agent run "帮我做X"
#   docker run octopus-agent octopus-agent loop "目标" --config /etc/octopus/config.yaml
ENTRYPOINT ["octopus-agent"]
CMD ["serve", "--config", "/etc/octopus/config.yaml", "--host", "0.0.0.0", "--port", "8000"]
