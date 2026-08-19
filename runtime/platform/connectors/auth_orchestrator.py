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

import json
import os
import platform
import shlex
import subprocess
from typing import Any

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

    # ── 注入 ──────────────────────────────────────────────────
    def resolve_headers(self, conn: ConnectorDefinition) -> dict[str, str]:
        """为 MCP/HTTP 请求生成要注入的 auth 头。"""
        headers: dict[str, str] = {}
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
