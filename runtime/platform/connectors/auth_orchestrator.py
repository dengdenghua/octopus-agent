"""认证编排器 — 连接/断开/状态 + auth 头/环境变量注入。

对齐 WorkBuddy 连接器 / Codex connector_* 的认证编排:
  - CLI 型连接器: 执行 cli.json 的 init / auth / unAuth / status 命令
  - token / oauth 型: 通过网关接口收 token,加密存入 CredentialStore
  - 注入: 按 connector 的 auth_injection_rules 生成 Authorization / 自定义头,
    或按 cli.json authEnv 生成环境变量

注意: CLI auth 命令会弹浏览器/起交互进程;网关调用 connect 时默认以
``detached`` 方式(仅输出提示)执行,除非显式 ``run=true`` 同步跑。
"""
from __future__ import annotations

import contextlib
import json
import os
import platform
import re
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any

from runtime.platform.connectors import cli_lifecycle
from runtime.platform.connectors.connector_registry import ConnectorDefinition
from runtime.platform.connectors.credential_store import CredentialStore

# 允许从连接器注入的 header / env 白名单(防任意注入)
_ALLOWED_HEADERS = {
    "authorization",
    "x-oneid-access-token",
    "x-auth-token",
    "x-api-key",
    "cookie",
}
_ALLOWED_ENV_PREFIX = ("MCP_", "CONNECTOR_", "LARK_", "DWS_", "WECOM_", "WESTOCK_", "TENCENT_")


def _platform_key() -> str:
    sys = platform.system().lower()
    if sys == "darwin":
        return "darwin"
    if sys == "windows":
        return "win32"
    return "linux"


# ── 设备流会话(WorkBuddy ``authDeviceFlow``)──────────────
# CLI 登录命令往往是阻塞的设备流:后台跑 auth 命令 → 解析 verification_uri /
# user_code → 前端弹窗 + 轮询 status。登录成功或超时后终止后台进程。


@dataclass
class DeviceFlowSession:
    connector_id: str
    proc: Any  # subprocess.Popen | None
    verification_uri: str
    user_code: str
    expires_in: int
    started_at: float
    opened: bool = False


_device_flows: dict[str, DeviceFlowSession] = {}
_device_lock = threading.Lock()


def _pick_platform(cmd_map: Any) -> str | None:
    if not isinstance(cmd_map, dict):
        return None
    return cmd_map.get(_platform_key()) or cmd_map.get("darwin") or cmd_map.get("linux")


class AuthOrchestrator:
    """连接器认证编排:负责把「连上外部服务」这件事做掉。"""

    def __init__(
        self,
        *,
        credentials: CredentialStore | None = None,
        auth_injection_rules: list[dict[str, Any]] | None = None,
    ) -> None:
        self._credentials = credentials or CredentialStore()
        self._rules = auth_injection_rules or []

    # ── 状态 ──────────────────────────────────────────────────
    def status(self, conn: ConnectorDefinition) -> dict[str, Any]:
        stored = self._credentials.list_secrets(conn.id)
        authed = self._credentials.has_credentials(conn.id)
        detail: dict[str, Any] = {
            "connector_id": conn.id,
            "auth_mode": conn.auth_mode,
            "connected": authed,
            "has_token": "access_token" in stored,
            "stored_keys": stored,
        }
        # CLI 型:如果存了 access_token 认为已连;否则(可选)跑 status 命令
        if not authed and conn.cli and "status" in conn.cli:
            code, stdout = self._run_cli(conn, conn.cli.get("status"))
            detail["cli_status"] = {
                "exit_code": code,
                "output": stdout[:500],
                "connected": code == 0 and self._match_status(conn, stdout),
            }
        # 设备流:status 确认已登录(或超时) → 终止并清理后台 auth 进程
        cli_connected = bool(
            (detail.get("cli_status") or {}).get("connected")
        ) or bool(detail.get("has_token"))
        self._finish_device_flow(conn, cli_connected)
        return detail

    def connect(
        self,
        conn: ConnectorDefinition,
        *,
        tokens: dict[str, str] | None = None,
        run_cli: bool = False,
    ) -> dict[str, Any]:
        """编排连接流程。

        - tokens 提供时直接加密存储(token/oauth 型)。
        - 否则 CLI 型执行 cli.json auth 命令(run_cli=True 时同步跑并校验)。
        """
        if conn.auth_mode == "none":
            return {"connected": True, "message": "该连接器无需认证。"}

        if tokens:
            for k, v in tokens.items():
                if v:
                    self._credentials.set_secret(conn.id, k, v)
            return {
                "connected": True,
                "connector_id": conn.id,
                "stored_keys": self._credentials.list_secrets(conn.id),
                "message": f"已保存 {len(tokens)} 项凭据(AES-256-GCM 加密)。",
            }

        if conn.cli and "auth" in conn.cli:
            cmd = _pick_platform(conn.cli.get("auth"))
            if not cmd:
                return {"connected": False, "message": "当前平台无 auth 命令。"}
            if run_cli:
                # 设备流:后台启动登录,返回 verification_uri / user_code 供前端
                # 弹窗 + 轮询 status,不再阻塞等 CLI 退出。
                if conn.cli.get("authDeviceFlow"):
                    return self.start_device_flow(conn)
                code, stdout = self._run_cli(conn, conn.cli.get("auth"), timeout=600)
                connected = code == 0 and self._match_status(conn, stdout or "")
                return {
                    "connected": connected,
                    "exit_code": code,
                    "output": (stdout or "")[:500],
                    "message": "CLI 登录完成" if connected else "CLI 登录未确认",
                }
            return {
                "connected": False,
                "message": f"请在终端执行: {cmd}\n或带 tokens 调用本接口。",
                "command": cmd,
            }

        return {"connected": False, "message": f"不支持 {conn.auth_mode} 自动连接,请提供 tokens。"}

    def disconnect(self, conn: ConnectorDefinition) -> dict[str, Any]:
        removed = self._credentials.clear_connector(conn.id)
        cli_out: str | None = None
        if conn.cli and "unAuth" in conn.cli:
            cmd = _pick_platform(conn.cli.get("unAuth"))
            if cmd:
                code, stdout = self._run_cli(conn, conn.cli.get("unAuth"))
                cli_out = stdout[:300]
        return {
            "disconnected": True,
            "credentials_removed": removed,
            "cli_output": cli_out,
        }

    # ── 设备流(WorkBuddy ``authDeviceFlow``)──────────────────
    def start_device_flow(self, conn: ConnectorDefinition) -> dict[str, Any]:
        """后台启动 CLI 设备流登录,解析 authorization URI + user_code。

        返回 ``{"connected": False, "device_flow": {...}}``,前端弹窗打开
        ``verification_uri``(URI 通常已内嵌 user_code)并轮询 ``status``。
        """
        spec = (conn.cli or {}).get("authDeviceFlow") or {}
        default_ttl = float(spec.get("defaultExpiresInSeconds", 240))
        with _device_lock:
            sess = _device_flows.get(conn.id)
            if sess and time.time() - sess.started_at < min(sess.expires_in, default_ttl):
                return self._device_flow_payload(conn, sess)
        cmd = cli_lifecycle.resolve_cmd((conn.cli or {}).get("auth"))
        if not cmd:
            return {"connected": False, "message": "当前平台无 auth 命令。"}
        env = self.resolve_env(conn)
        try:
            proc = subprocess.Popen(
                shlex.split(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, **env},
            )
        except Exception as exc:  # noqa: BLE001
            return {"connected": False, "message": f"设备流启动失败: {exc}"}
        sess = DeviceFlowSession(
            connector_id=conn.id,
            proc=proc,
            verification_uri="",
            user_code="",
            expires_in=int(default_ttl),
            started_at=time.time(),
        )
        with _device_lock:
            _device_flows[conn.id] = sess
        threading.Thread(
            target=self._drain_device_output,
            args=(conn, sess),
            daemon=True,
        ).start()
        # 等最多 6s 解析出授权 URI(命令行启动 + 首行输出)
        deadline = time.time() + 6
        while time.time() < deadline and not sess.verification_uri:
            time.sleep(0.2)
        return self._device_flow_payload(conn, sess)

    def _drain_device_output(self, conn: ConnectorDefinition, sess: DeviceFlowSession) -> None:
        spec = (conn.cli or {}).get("authDeviceFlow") or {}
        uri_re = re.compile(str(spec.get("uriPattern") or ""))
        code_re = re.compile(str(spec.get("codePattern") or ""))
        try:
            if not sess.proc or not sess.proc.stdout:
                return
            for line in sess.proc.stdout:
                if sess.verification_uri and sess.user_code:
                    break
                if uri_re.pattern and not sess.verification_uri:
                    m = uri_re.search(line)
                    if m:
                        uri = m.group(1) if m.groups() else m.group(0)
                        if cli_lifecycle.validate_auth_uri(uri, conn):
                            sess.verification_uri = uri
                if code_re.pattern and not sess.user_code:
                    m = code_re.search(line)
                    if m:
                        sess.user_code = m.group(1) if m.groups() else m.group(0)
        finally:
            if sess.proc and sess.proc.poll() is None and not sess.opened:
                # CLI 已自行退出(可能出错),避免进程泄漏
                with contextlib.suppress(Exception):
                    sess.proc.terminate()

    def _device_flow_payload(
        self,
        conn: ConnectorDefinition,
        sess: DeviceFlowSession,
    ) -> dict[str, Any]:
        spec = (conn.cli or {}).get("authDeviceFlow") or {}
        return {
            "connected": False,
            "auth_mode": conn.auth_mode,
            "device_flow": {
                "connector_id": conn.id,
                "verification_uri": sess.verification_uri,
                "user_code": sess.user_code,
                "expires_in": sess.expires_in,
                "code_embedded_in_uri": bool(spec.get("codeEmbeddedInUri")),
                "message": (
                    "已启动设备流登录,请在打开的页面完成授权。"
                    if sess.verification_uri
                    else "设备流已启动,正在等待授权地址…"
                ),
            },
        }

    def _finish_device_flow(self, conn: ConnectorDefinition, connected: bool) -> None:
        """设备流登录完成(或过期)→ 终止并清理后台 auth 进程。"""
        with _device_lock:
            sess = _device_flows.get(conn.id)
            if sess is None:
                return
            expired = time.time() - sess.started_at >= sess.expires_in
            if not (connected or expired):
                return
            _device_flows.pop(conn.id, None)
            proc = sess.proc
        if proc and proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()

    def device_flow_status(self, conn: ConnectorDefinition) -> dict[str, Any]:
        """返回活跃设备流信息(未启动/已结束 → device_flow=None)。"""
        with _device_lock:
            sess = _device_flows.get(conn.id)
            if sess is None:
                return {"connector_id": conn.id, "active": False, "device_flow": None}
            return {"connector_id": conn.id, "active": True, **self._device_flow_payload(conn, sess)}

    def cancel_device_flow(self, conn: ConnectorDefinition) -> dict[str, Any]:
        """取消进行中的设备流登录(终止后台进程)。"""
        with _device_lock:
            sess = _device_flows.pop(conn.id, None)
        if sess and sess.proc and sess.proc.poll() is None:
            with contextlib.suppress(Exception):
                sess.proc.terminate()
        return {"cancelled": True, "connector_id": conn.id}

    # ── 注入 ──────────────────────────────────────────────────
    def resolve_headers(self, conn: ConnectorDefinition) -> dict[str, str]:
        """为 MCP/HTTP 请求生成要注入的 auth 头。"""
        headers: dict[str, str] = {}
        # 0) oneid-token(腾讯统一身份):注入 X-ONEID-ACCESS-TOKEN
        if conn.auth_mode == "oneid-token":
            tok = (
                self._credentials.get_secret(conn.id, "oneid_token")
                or self._credentials.get_secret(conn.id, "access_token")
            )
            if tok:
                headers["X-ONEID-ACCESS-TOKEN"] = tok
        # 1) connector 自带规则(connectors.json auth_injection_rules)
        for rule in self._rules:
            if conn.id not in rule.get("applies_to_connectors", []):
                continue
            for inject in rule.get("inject", []):
                token_type = inject.get("token_type") or "access_token"
                header = inject.get("header") or ""
                if not header or header.lower() not in _ALLOWED_HEADERS:
                    continue
                token = self._credentials.get_secret(conn.id, token_type)
                if not token:
                    continue
                template = inject.get("value_template") or "${access_token}"
                headers[header] = template.replace("${access_token}", token)
        # 2) 兜底:有 access_token 就挂 Bearer
        if not headers and self._credentials.has_credentials(conn.id):
            token = self._credentials.get_secret(conn.id, "access_token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        return headers

    def resolve_env(self, conn: ConnectorDefinition) -> dict[str, str]:
        """为 CLI 子进程生成环境变量注入。"""
        env: dict[str, str] = {}
        for key in self._credentials.list_secrets(conn.id):
            if key.startswith(_ALLOWED_ENV_PREFIX) or key in {"access_token", "api_key"}:
                val = self._credentials.get_secret(conn.id, key)
                if val:
                    env[key] = val
        return env

    # ── CLI 辅助 ──────────────────────────────────────────────
    def _run_cli(
        self, conn: ConnectorDefinition, cmd_spec: Any, timeout: int = 120
    ) -> tuple[int, str | None]:
        cmd = _pick_platform(cmd_spec) if isinstance(cmd_spec, dict) else cmd_spec
        if not cmd:
            return -1, None
        env = self.resolve_env(conn)
        try:
            r = subprocess.run(
                shlex.split(cmd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **env},
            )
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except Exception as exc:  # noqa: BLE001
            return -1, str(exc)

    @staticmethod
    def _match_status(conn: ConnectorDefinition, output: str) -> bool:
        status_match = conn.cli.get("statusMatch") or ""
        if status_match and status_match in output:
            return True
        match_json = conn.cli.get("statusMatchJson") or {}
        if match_json:
            try:
                start = output.find("{")
                data = json.loads(output[start:]) if start >= 0 else {}
                for k, v in match_json.items():
                    if str(data.get(k)) == str(v):
                        return True
            except (json.JSONDecodeError, ValueError):  # noqa: BLE001
                pass
        return False


__all__ = ["AuthOrchestrator"]


def mcp_injection_for_server(
    server_name: str,
    *,
    registry: Any = None,
    orchestrator: AuthOrchestrator | None = None,
) -> dict[str, dict[str, str]]:
    """为 MCP server 名解析连接器认证注入(仅 已安装 + 已启用 + 已连接)。

    连接器 id 与 MCP server 名不一致(如 ``canva-ai`` → ``canva-mcp``),
    这里按 ``conn.mcp_servers`` 的 key 反查。找不到匹配 / 未安装 /
    未启用 / 未连接时返回空注入,MCP 代理侧不附加任何凭据。

    返回 ``{"headers": {...}, "env": {...}}``,分别供 HTTP / stdio 传输注入。
    """
    from runtime.platform.connectors.connector_registry import ConnectorRegistry

    registry = registry or ConnectorRegistry()
    orch = orchestrator or AuthOrchestrator()
    state = registry._state()
    for cid, st in state.items():
        if not (st.get("installed") and st.get("enabled")):
            continue
        conn = registry.get(cid)
        if conn is None or not conn.mcp_servers:
            continue
        if server_name not in conn.mcp_servers:
            continue
        return {
            "headers": orch.resolve_headers(conn),
            "env": orch.resolve_env(conn),
        }
    return {"headers": {}, "env": {}}


__all__ = ["AuthOrchestrator", "mcp_injection_for_server"]
