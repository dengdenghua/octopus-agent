"""平台实时行情只读客户端(live 数据源)。

按对方 App 的接口协议,连接其后端拉取**真实行情数据**:

- 登录: ``POST /api/member/member/login``,密码用 **RSA-1024(PKCS#1 v1.5)** 加密
  (公钥来自 ``POST /api/system/systemConfigs/getPublicKey``,与 App 一致);
- 大盘概览: ``POST /api/market/v2/data/doAction?event=todayStock``,返回 **gzip JSON**
  (真实指数价格 + 全市场涨跌家数 + 市场状态);
- 公司简况: ``GET /api/market/brief?code=<symbol>``(真实财报/基本面)。

默认只拉行情;同时提供**可选的账户/合约/下单方法**(申请资金、买入、卖出等)供插件调用。
JWT token 缓存在本地状态目录(默认 ~/.octopus/data/paper_trading/token.json),
过期自动重登。账号密码只在登录时使用,不写入任何文件(从环境变量或凭证文件读取)。
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    HAS_CRYPTO = True
except Exception:  # pragma: no cover
    HAS_CRYPTO = False

_logger = logging.getLogger(__name__)

ENV_PHONE = "PAPER_TRADING_PHONE"
ENV_PASSWORD = "PAPER_TRADING_PASSWORD"

# 平台返回这些 code 表示会话失效(登录信息已过期),自动重登后重试一次。
_AUTH_EXPIRED_CODES = {20040, 20041, 20042, 10001}


class PlatformClientError(RuntimeError):
    """平台客户端错误(登录失败/网络/解析)。"""


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * ((4 - len(s) % 4) % 4))


def _mask_phone(phone: str) -> str:
    """手机号打码用于展示:138****3548。"""
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return "***" if phone else ""


class PlatformClient:
    """只读行情客户端:登录 → 拿 JWT → 拉真实行情。"""

    def __init__(
        self,
        base_url: str,
        phone: str = "",
        password: str = "",
        state_dir: str = "~/.octopus/data/paper_trading",
        timeout: float = 12.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.phone = phone or os.environ.get(ENV_PHONE, "")
        self.password = password or os.environ.get(ENV_PASSWORD, "")
        self.timeout = timeout
        self.state_dir = Path(state_dir).expanduser()
        self._token: str | None = None

    # ── 凭证 ─────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        base_url: str,
        phone: str = "",
        password: str = "",
        state_dir: str = "~/.octopus/data/paper_trading",
        credentials_file: str = "~/.octopus/data/paper_trading/credentials.json",
    ) -> PlatformClient:
        """从配置 + 可选凭证文件加载。凭证文件 {phone, password},chmod 600。"""
        client = cls(base_url, phone, password, state_dir)
        path = Path(credentials_file).expanduser()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                client.phone = client.phone or str(data.get("phone", ""))
                client.password = client.password or str(data.get("password", ""))
            except Exception as exc:  # noqa: BLE001
                _logger.warning("paper_trading: 凭证文件读取失败: %s", exc)
        return client

    @property
    def token_path(self) -> Path:
        return self.state_dir / "token.json"

    @property
    def has_credentials(self) -> bool:
        return bool(self.phone and self.password)

    @property
    def account_name(self) -> str:
        """从当前 JWT 解码平台账号名(如 HL51550949),未登录返回空串。"""
        if not self._token:
            return ""
        try:
            claims = json.loads(_b64url_decode(self._token.split(".")[1]))
            return str(claims.get("account") or "")
        except Exception:  # noqa: BLE001
            return ""

    def save_credentials(
        self,
        phone: str,
        password: str,
        credentials_file: str = "~/.octopus/data/paper_trading/credentials.json",
    ) -> Path:
        """把平台账号凭证写到本地文件(chmod 600)。只落盘,不校验。"""
        path = Path(credentials_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"phone": phone, "password": password}, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.chmod(0o600)
        tmp.replace(path)
        path.chmod(0o600)
        self.phone = phone
        self.password = password
        return path

    def clear_credentials(
        self,
        credentials_file: str = "~/.octopus/data/paper_trading/credentials.json",
    ) -> None:
        """删除本地凭证文件,并清空客户端内存中的账号。"""
        path = Path(credentials_file).expanduser()
        try:
            if path.exists():
                path.unlink()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 清除凭证失败: %s", exc)
        self.phone = ""
        self.password = ""
        self._token = None

    # ── 基础 HTTP ────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        """发一次带鉴权的请求;若平台判定会话失效(code 20040 等),自动重登后重试一次。"""
        resp = self._request_once(method, path, payload, auth=auth)
        if auth and isinstance(resp, dict) and resp.get("code") in _AUTH_EXPIRED_CODES:
            _logger.warning("paper_trading: 会话失效(%s),强制重登后重试 %s", resp.get("code"), path)
            try:
                self.login(force=True)
            except Exception as exc:  # noqa: BLE001
                raise PlatformClientError(f"重登失败: {exc}") from exc
            resp = self._request_once(method, path, payload, auth=auth)
        return resp

    def _request_once(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        auth: bool = True,
    ) -> dict[str, Any]:
        headers = {"User-Agent": "okhttp/4.9.0"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if auth and self._token:
            # 平台用 `token` 请求头鉴权(部分接口也认 Authorization)
            headers["token"] = self._token
            headers["Authorization"] = "Bearer " + self._token
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise PlatformClientError(f"HTTP {exc.code} {path}: {exc.read()[:200]}") from exc
        except Exception as exc:  # noqa: BLE001
            raise PlatformClientError(f"网络错误 {path}: {exc}") from exc
        try:
            return json.loads(body)
        except ValueError as exc:
            raise PlatformClientError(f"响应非 JSON {path}: {body[:120]}") from exc

    # ── 登录 ─────────────────────────────────────────────

    def _load_token(self) -> str | None:
        try:
            if self.token_path.exists():
                data = json.loads(self.token_path.read_text(encoding="utf-8"))
                tok = data.get("token")
                if tok:
                    # 粗略检查未过期(读 JWT exp)
                    try:
                        payload = _b64url_decode(tok.split(".")[1])
                        claims = json.loads(payload)
                        exp = int(claims.get("exp", 0))
                        if exp > 0 and exp < 1760000000:  # 明显过期则重登
                            return None
                    except Exception:  # noqa: BLE001
                        return tok
                    return tok
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: token 读取失败: %s", exc)
        return None

    def _save_token(self, token: str) -> None:
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.token_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"token": token}), encoding="utf-8")
            tmp.replace(self.token_path)
            try:
                tmp.chmod(0o600)
                self.token_path.chmod(0o600)
            except Exception:  # pragma: no cover
                pass
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: token 保存失败: %s", exc)

    def login(self, force: bool = False) -> str:
        """登录拿 JWT。成功缓存 token;返回 token 字符串。"""
        if not force:
            cached = self._load_token()
            if cached:
                self._token = cached
                return cached
        if not self.has_credentials:
            raise PlatformClientError(
                f"未配置平台账号:请设置环境变量 {ENV_PHONE}/{ENV_PASSWORD} "
                "或在 ~/.octopus/data/paper_trading/credentials.json 提供 {phone,password}"
            )
        if not HAS_CRYPTO:
            raise PlatformClientError("缺少 cryptography 库,无法做 RSA 加密")

        # 1) 拉 RSA 公钥
        resp = self._request("POST", "/system/systemConfigs/getPublicKey", {}, auth=False)
        if resp.get("code") != 1:
            raise PlatformClientError(f"获取公钥失败: {resp}")
        pub_b64 = (resp.get("data") or {}).get("publicKey", "")
        if not pub_b64:
            raise PlatformClientError("公钥为空")
        pem = (
            "-----BEGIN PUBLIC KEY-----\n"
            + "\n".join(pub_b64[i : i + 64] for i in range(0, len(pub_b64), 64))
            + "\n-----END PUBLIC KEY-----\n"
        )
        pub = serialization.load_pem_public_key(pem.encode("utf-8"))

        # 2) RSA 加密密码
        encrypted = base64.b64encode(
            pub.encrypt(self.password.encode("utf-8"), padding.PKCS1v15())
        ).decode()

        # 3) 登录
        resp = self._request(
            "POST",
            "/member/member/login",
            {"phone": self.phone, "loginPassword": encrypted},
            auth=False,
        )
        if resp.get("code") != 1:
            raise PlatformClientError(f"登录失败: {resp}")
        data = resp.get("data") or {}
        token = data.get("token")
        if not token:
            raise PlatformClientError(f"登录响应无 token: {resp}")
        self._token = token
        self._save_token(token)
        return token

    def _ensure_token(self) -> str:
        if self._token:
            return self._token
        return self.login()

    # ── 会员 / 账户(只读) ─────────────────────────────────

    @property
    def member_id(self) -> str:
        """从 JWT 解码 memberId。"""
        if not self._token:
            return ""
        try:
            claims = json.loads(_b64url_decode(self._token.split(".")[1]))
            return str(claims.get("memberId") or "")
        except Exception:  # noqa: BLE001
            return ""

    def get_member_info(self) -> dict[str, Any]:
        self._ensure_token()
        return (
            self._request(
                "POST",
                "/member/member/getMemberBaseInfo",
                {"memberId": self.member_id, "account": self.account_name or self.phone},
            ).get("data")
            or {}
        )

    def list_contracts(self) -> list[dict[str, Any]]:
        """当前合约列表(轻量):contractId/contractName/amountAvailable/totalTradersMoney。"""
        self._ensure_token()
        resp = self._request(
            "POST", "/contract/ContractListMember/memberId", {"memberId": self.member_id}
        )
        if resp.get("code") != 1:
            raise PlatformClientError(f"合约列表失败: {resp}")
        return resp.get("data") or []

    def contract_list_full(self) -> list[dict[str, Any]]:
        """完整合约列表(含账户汇总字段:合约总值/浮动盈亏/预警线/合约编号等)。"""
        self._ensure_token()
        resp = self._request("POST", "/contract/ContractList/select", {"memberId": self.member_id})
        if resp.get("code") != 1:
            raise PlatformClientError(f"合约详情失败: {resp}")
        data = resp.get("data") or {}
        return data.get("contractListVOS") or []

    def contract_details(self, contract_id: str) -> dict[str, Any]:
        """单个合约详情(尽力而为;接口偶发 40013 时降级返回空)。"""
        self._ensure_token()
        try:
            resp = self._request(
                "POST",
                "/contract/ContractList/contractDetails",
                {
                    "token": self._token,
                    "memberId": self.member_id,
                    "id": contract_id,
                    "contractStats": 0,
                },
            )
            if resp.get("code") == 1:
                return resp.get("data") or {}
            _logger.warning("paper_trading: 合约详情接口返回 %s", resp)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 合约详情拉取失败: %s", exc)
        return {}

    def positions(self) -> Any:
        """当前持仓(返回持仓列表)。"""
        self._ensure_token()
        resp = self._request("POST", "/stock/position", {"token": self._token})
        if resp.get("code") != 1:
            raise PlatformClientError(f"持仓失败: {resp}")
        return self._maybe_gunzip(resp.get("data"))

    def orders(
        self, contract_id: str = "", type_: int = 1, current: int = 1, size: int = 20
    ) -> dict[str, Any]:
        """委托/成交记录(type_=1 已成交,2 已撤单)。

        平台对非空响应返回 gzip 的 ``{stockOrderVOList:[...], pages:N}``,空记录返回 ``[]``。
        统一归一化为 ``{"list":[...], "pages":N, "total":N, "type":type_}``。
        """
        self._ensure_token()
        payload: dict[str, Any] = {
            "token": self._token,
            "memberId": self.member_id,
            "type": type_,
            "current": current,
            "size": size,
        }
        if contract_id:
            payload["contractId"] = contract_id
        resp = self._request("POST", "/stock/stockOrder", payload)
        if resp.get("code") != 1:
            raise PlatformClientError(f"委托记录失败: {resp}")
        data = self._maybe_gunzip(resp.get("data"))
        if isinstance(data, dict):
            items = data.get("stockOrderVOList") or data.get("list") or []
            pages = int(data.get("pages") or 1)
        elif isinstance(data, list):
            items, pages = data, 1
        else:
            items, pages = [], 1
        return {
            "list": items,
            "pages": max(1, pages),
            "total": len(items),
            "type": type_,
        }

    def money_records(
        self,
        contract_id: str = "",
        type_: int | str = "",
        date: str = "",
        current: int = 1,
        size: int = 20,
    ) -> list[dict[str, Any]]:
        """资金流水/交易明细(申请/买入成功/卖出成功/提盈/结算等)。"""
        self._ensure_token()
        payload: dict[str, Any] = {
            "token": self._token,
            "memberId": self.member_id,
            "contractId": contract_id or "",
            "type": type_,
            "date": date,
            "current": current,
            "size": size,
        }
        resp = self._request("POST", "/contract/ContractList/getContractMoneyRecord", payload)
        if resp.get("code") != 1:
            raise PlatformClientError(f"资金流水失败: {resp}")
        data = self._maybe_gunzip(resp.get("data"))
        if isinstance(data, dict):
            return data.get("moneyRecordVOS") or data.get("list") or []
        return data if isinstance(data, list) else []

    def rate_table(self) -> list[dict[str, Any]]:
        """配资费率表(倍数/按天/按周/按月利率)。"""
        self._ensure_token()
        resp = self._request("POST", "/contract/getContractRateTable", {"memberId": self.member_id})
        if resp.get("code") != 1:
            raise PlatformClientError(f"费率表失败: {resp}")
        return resp.get("data") or []

    def apply_options(self) -> dict[str, Any]:
        """申请资金档位/类型(按天/按周/按月 + 保证金档位 + 倍数)。"""
        self._ensure_token()
        resp = self._request("POST", "/contract/system/type", {"memberId": self.member_id})
        if resp.get("code") != 1:
            raise PlatformClientError(f"申请选项失败: {resp}")
        return resp.get("data") or {}

    def sell_panel(self, contract_id: str, stock_code: str) -> dict[str, Any]:
        """卖出面板(只读):可卖数量 + 各项费率。"""
        self._ensure_token()
        resp = self._request(
            "POST",
            "/stock/SellStock/show",
            {
                "contractId": contract_id,
                "memberId": self.member_id,
                "stockCode": stock_code,
            },
        )
        if resp.get("code") != 1:
            raise PlatformClientError(f"卖出面板失败: {resp}")
        return resp.get("data") or {}

    # ── 合约/交易操作(真实,仅在用户明确触发时调用) ────────

    def apply_contract(
        self,
        contract_type: int,
        principal: float,
        multiple: int,
    ) -> dict[str, Any]:
        """申请/扩大配资合约。contract_type: 1按天 2按周 3按月(与平台一致)。"""
        self._ensure_token()
        return self._request(
            "POST",
            "/contract/applycontract/add",
            {
                "contractType": int(contract_type),
                "principal": float(principal),
                "multiple": int(multiple),
                "memberId": self.member_id,
            },
        )

    def buy(
        self,
        contract_id: str,
        stock_code: str,
        stock_name: str,
        entrust_type: int,
        price: float | None,
        number: int,
    ) -> dict[str, Any]:
        """买入(真实下单)。entrust_type: 0限价 1市价;number 须为 100 整数倍。"""
        self._ensure_token()
        payload: dict[str, Any] = {
            "contractId": contract_id,
            "memberId": self.member_id,
            "stockCode": stock_code,
            "stockName": stock_name,
            "entrustType": str(int(entrust_type)),
            "entrustNumber": int(number),
        }
        if entrust_type == 0:
            payload["entrustPrice"] = float(price) if price else 0.0
        return self._request("POST", "/stock/BuyStock/insert", payload)

    def sell(
        self,
        contract_id: str,
        stock_code: str,
        stock_name: str,
        entrust_type: int,
        price: float | None,
        number: int,
    ) -> dict[str, Any]:
        """卖出(真实下单)。"""
        self._ensure_token()
        payload: dict[str, Any] = {
            "contractId": contract_id,
            "memberId": self.member_id,
            "stockCode": stock_code,
            "stockName": stock_name,
            "entrustType": str(int(entrust_type)),
            "entrustNumber": int(number),
        }
        if entrust_type == 0:
            payload["entrustPrice"] = float(price) if price else 0.0
        return self._request("POST", "/stock/SellStock/insert", payload)

    def cancel_order(self, order_id: str, contract_id: str) -> dict[str, Any]:
        """撤单。"""
        self._ensure_token()
        return self._request(
            "POST",
            "/stock/cancelOrder/cancel",
            {
                "orderId": order_id,
                "contractId": contract_id,
                "memberId": self.member_id,
            },
        )

    def add_capital(self, contract_id: str, money: float) -> dict[str, Any]:
        """追加资金(扩大合约可用资金)。"""
        self._ensure_token()
        return self._request(
            "POST",
            "/contract/appendcapital/additional",
            {"contractId": contract_id, "memberId": self.member_id, "money": float(money)},
        )

    def withdraw_profit(self, contract_id: str, money: float) -> dict[str, Any]:
        """提盈。"""
        self._ensure_token()
        return self._request(
            "POST",
            "/contract/WithdrawProfit/extract",
            {"contractId": contract_id, "memberId": self.member_id, "money": float(money)},
        )

    # ── 行情 ─────────────────────────────────────────────

    @staticmethod
    def _gunzip_b64(data: str) -> dict[str, Any]:
        raw = base64.b64decode(data)
        try:
            raw = gzip.decompress(raw)
        except Exception as exc:  # noqa: BLE001
            raise PlatformClientError(f"gzip 解压失败: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise PlatformClientError(f"行情数据非 JSON: {raw[:120]}") from exc

    @staticmethod
    def _maybe_gunzip(data: Any) -> Any:
        """有些接口返回 gzip base64 字符串,有些直接返回 JSON(list/dict)。"""
        if not isinstance(data, str):
            return data
        if data.startswith("H4sI"):  # base64 gzip magic
            return PlatformClient._gunzip_b64(data)
        try:
            return json.loads(data)
        except ValueError:
            return data

    def fetch_today_stock(self) -> dict[str, Any]:
        """大盘概览:真实指数 + 全市场涨跌家数 + 市场状态。"""
        resp = self._request("POST", "/market/v2/data/doAction?event=todayStock", {})
        if resp.get("code") != 1:
            raise PlatformClientError(f"todayStock 失败: {resp}")
        return self._gunzip_b64(resp.get("data", ""))

    def fetch_brief(self, code: str) -> dict[str, Any]:
        """单只股票公司简况(真实基本面)。code 形如 600519.sh。"""
        resp = self._request("GET", f"/market/brief?code={code}")
        if resp.get("code") != 1:
            raise PlatformClientError(f"market/brief 失败: {resp}")
        return resp.get("data") or {}

    def fetch_stock_choose(self) -> list[dict[str, Any]]:
        """平台自选列表(带实时行情:现价/涨跌幅/量/分时)。

        对应前端 ``getStockChooseV2`` -> ``POST /stock/stockCodeV2``(gzip)。
        未登录态会由 ``_ensure_token`` 兜底;失败抛 :class:`PlatformClientError`。
        """
        self._ensure_token()
        resp = self._request(
            "POST",
            "/stock/stockCodeV2",
            {"memberId": self.member_id, "event": "subscribe", "isCompress": True},
        )
        if resp.get("code") != 1:
            raise PlatformClientError(f"自选失败: {resp}")
        data = self._maybe_gunzip(resp.get("data"))
        if isinstance(data, dict):
            return data.get("optionalVOList") or []
        return []

    def fetch_real_quotes(self, codes: list[str]) -> list[dict[str, Any]]:
        """单股实时报价(现价/涨跌幅/涨跌停/分时等)。

        对应前端 ``kLineRealTime`` -> ``doAction?event=kLineRealTime``(gzip)。
        ``codes`` 形如 ["600519.sh", "003032.sz"];失败抛 :class:`PlatformClientError`。
        """
        self._ensure_token()
        resp = self._request(
            "POST",
            "/market/v2/data/doAction?event=kLineRealTime",
            {"url": "kLineRealTime", "event": "subscribe", "params": list(codes or [])},
        )
        if resp.get("code") != 1:
            raise PlatformClientError(f"实时报价失败: {resp}")
        data = self._maybe_gunzip(resp.get("data"))
        if isinstance(data, list):
            return data
        return []


__all__ = ["PlatformClient", "PlatformClientError"]


# ── 可选实时行情源 ────────────────────────────────────────

DEFAULT_BASE_URL = "http://114.66.32.152:58868/api"


class LiveDataSource:
    """可选的真实行情源(只读):包装 :class:`PlatformClient`,带缓存 TTL 与优雅降级。

    页面/API 每几秒刷新一次,但本类会按 ``ttl`` 合并请求,避免高频打对方后端。
    登录失败 / 无凭证 / 网络异常一律降级返回 ``{available: False, ...}``,
    绝不抛出异常、绝不影响本地模拟交易功能。
    """

    def __init__(
        self,
        client: PlatformClient,
        ttl: float = 30.0,
        credentials_file: str = "~/.octopus/data/paper_trading/credentials.json",
    ) -> None:
        self._client = client
        self._ttl = max(1.0, float(ttl))
        self._credentials_file = credentials_file
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0
        self._watch_cache: dict[str, Any] | None = None
        self._watch_cached_at = 0.0
        self._watch_ttl = max(2.0, min(self._ttl, 10.0))
        self._lock = threading.Lock()

    @classmethod
    def from_config(
        cls,
        cfg: dict[str, Any],
        state_dir: str = "~/.octopus/data/paper_trading",
        credentials_file: str = "~/.octopus/data/paper_trading/credentials.json",
    ) -> LiveDataSource:
        base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL)
        ttl = float(cfg.get("live_ttl") or 30.0)
        client = PlatformClient.from_config(
            base_url, state_dir=state_dir, credentials_file=credentials_file
        )
        return cls(client, ttl=ttl, credentials_file=credentials_file)

    @property
    def client(self) -> PlatformClient:
        return self._client

    @property
    def available(self) -> bool:
        return self._client.has_credentials

    @property
    def configured(self) -> bool:
        """本地是否已保存凭证(文件存在或客户端内存有账号)。"""
        if self._client.has_credentials:
            return True
        return Path(self._credentials_file).expanduser().exists()

    @property
    def phone(self) -> str:
        return self._client.phone or ""

    @property
    def account(self) -> str:
        """展示用账号:优先 JWT 里的 account,否则打码手机号。"""
        return self._client.account_name or _mask_phone(self.phone)

    def save_credentials(self, phone: str, password: str) -> dict[str, Any]:
        """保存平台凭证到本地(chmod 600)并尝试登录验证。"""
        phone = (phone or "").strip()
        password = password or ""
        if not phone or not password:
            return {"saved": False, "ok": False, "error": "手机号和密码不能为空"}
        self._client.save_credentials(phone, password, self._credentials_file)
        with self._lock:
            self._cache = None
            self._cached_at = 0.0
        try:
            self._client.login(force=True)
            return {
                "ok": True,
                "saved": True,
                "verified": True,
                "account": self._client.account_name or _mask_phone(phone),
            }
        except Exception as exc:  # noqa: BLE001 — 已落盘,登录验证失败单独提示
            _logger.warning("paper_trading: 凭证已保存但登录验证失败: %s", exc)
            return {
                "ok": True,
                "saved": True,
                "verified": False,
                "account": _mask_phone(phone),
                "error": str(exc),
            }

    def clear_credentials(self) -> dict[str, Any]:
        """删除本地凭证文件并清空内存账号。"""
        self._client.clear_credentials(self._credentials_file)
        with self._lock:
            self._cache = None
            self._cached_at = 0.0
        return {"ok": True, "message": "已清除平台凭证"}

    def overview(self, force: bool = False) -> dict[str, Any]:
        """实时大盘概览(带缓存)。失败降级,不抛异常。"""
        now = time.time()
        if not force and self._cache and now - self._cached_at < self._ttl:
            return self._cache
        with self._lock:
            if not force and self._cache and time.time() - self._cached_at < self._ttl:
                return self._cache
            self._cache = self._build_overview()
            self._cached_at = time.time()
            return self._cache

    def watch(self, force: bool = False) -> dict[str, Any]:
        """盯盘聚合:大盘 + 平台持仓 + 平台自选(全部真实行情)。

        独立短 TTL(``_watch_ttl``,2~10s)让盯盘更实时,但不会比大盘的
        ``_ttl`` 更激进。任一来源失败只降级对应字段,不抛异常。
        """
        now = time.time()
        if not force and self._watch_cache and now - self._watch_cached_at < self._watch_ttl:
            return self._watch_cache
        with self._lock:
            if not force and self._watch_cache and time.time() - self._watch_cached_at < self._watch_ttl:
                return self._watch_cache
            self._watch_cache = self._build_watch()
            self._watch_cached_at = time.time()
            return self._watch_cache

    # ── 内部 ─────────────────────────────────────────────

    def _build_overview(self) -> dict[str, Any]:
        try:
            self._client.login()  # token 未过期则不发网络请求
            raw = self._client.fetch_today_stock()
        except Exception as exc:  # noqa: BLE001 — 降级,不让页面/下单受影响
            _logger.warning("paper_trading: 实时行情拉取失败(降级): %s", exc)
            return {
                "available": False,
                "source": self._client.base_url,
                "status": "",
                "fetched_at": "",
                "error": str(exc),
                "indices": [],
                "breadth": {"up": 0, "down": 0, "unchanged": 0, "stop": 0},
            }
        indices: list[dict[str, Any]] = []
        for s in raw.get("stockVOS") or []:
            price = s.get("price")
            if price is None:
                continue
            prev = s.get("yClose")
            chg = s.get("risefall")
            pct = s.get("increase")
            indices.append(
                {
                    "symbol": s.get("symbol") or "",
                    "name": s.get("name") or s.get("symbol") or "",
                    "price": round(float(price), 2),
                    "prev_close": round(float(prev), 2) if prev is not None else None,
                    "change": round(float(chg), 2) if chg is not None else None,
                    "change_pct": round(float(pct), 2) if pct is not None else None,
                    "spark": [round(float(x), 2) for x in (s.get("increases") or [])],
                }
            )
        return {
            "available": True,
            "source": self._client.base_url,
            "status": raw.get("stockStatus") or "",
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "indices": indices,
            "breadth": {
                "up": int(raw.get("up") or 0),
                "down": int(raw.get("down") or 0),
                "unchanged": int(raw.get("unchanged") or 0),
                "stop": int(raw.get("stop") or 0),
            },
        }

    def _build_watch(self) -> dict[str, Any]:
        """盯盘数据聚合:大盘 + 平台持仓 + 平台自选(真实行情)。

        三个来源各自降级:大盘走 ``_build_overview``(已有降级),持仓/自选
        失败只把对应字段置空并带 warning,不拖垮整个盯盘页。
        """
        try:
            self._client.login()  # token 未过期则不发网络请求
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 盯盘登录失败(降级): %s", exc)
            return {
                "available": False,
                "source": self._client.base_url,
                "status": "",
                "fetched_at": "",
                "error": str(exc),
                "indices": [],
                "breadth": {"up": 0, "down": 0, "unchanged": 0, "stop": 0},
                "positions": [],
                "watchlist": [],
            }
        overview = self._build_overview()  # 自己的缓存路径,这里直接取最新
        positions: Any = []
        watchlist: list[dict[str, Any]] = []
        try:
            positions = self._client.positions()
            if not isinstance(positions, list):
                positions = []
        except Exception as exc:  # noqa: BLE001 — 单点降级
            _logger.warning("paper_trading: 盯盘持仓拉取失败(降级): %s", exc)
            positions = []
        try:
            watchlist = self._client.fetch_stock_choose() or []
        except Exception as exc:  # noqa: BLE001 — 单点降级
            _logger.warning("paper_trading: 盯盘自选拉取失败(降级): %s", exc)
            watchlist = []
        return {
            "available": True,
            "source": self._client.base_url,
            "status": overview.get("status", ""),
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "indices": overview.get("indices", []),
            "breadth": overview.get("breadth", {}),
            "positions": positions,
            "watchlist": watchlist,
        }


__all__ = [
    "PlatformClient",
    "PlatformClientError",
    "LiveDataSource",
    "LivePushClient",
    "DEFAULT_BASE_URL",
    "_mask_phone",
    "_ws_sign",
    "_gunzip_json_b64",
    "_normalize_quote",
    "_normalize_push",
]


# ── 平台实时推送(socket.io v2 / engine.io v3,原始 WebSocket) ──────────────

try:
    import asyncio
    import urllib.parse
    from collections import defaultdict

    import websockets

    HAS_WEBSOCKETS = True
except Exception:  # pragma: no cover
    HAS_WEBSOCKETS = False


def _ws_sign(key: int, ts: float | None = None) -> str:
    """平台签名 ``getSignString(key)``:秒级时间戳逐位 XOR key 后 base64。

    - 握手 URL 用 key=1234;
    - 订阅消息体用 key=5678。
    """
    secs = str(int(ts if ts is not None else time.time()))
    return base64.b64encode("".join(chr(ord(ch) ^ key) for ch in secs).encode()).decode()


def _gunzip_json_b64(payload: Any) -> Any:
    """gzip+base64 推送解码。非 gzip 字符串(已是 JSON)直接解析,否则原样返回。"""
    if not isinstance(payload, str):
        return payload
    if payload.startswith("H4sI"):
        try:
            return json.loads(gzip.decompress(base64.b64decode(payload)))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 推送 gzip 解码失败: %s", exc)
            return payload
    try:
        return json.loads(payload)
    except ValueError:
        return payload


def _normalize_quote(q: dict[str, Any]) -> dict[str, Any]:
    """把平台实时报价压成紧凑字段(去掉全量分时,量化/盯盘够用)。

    输入 ``kLineRealTime`` 里的单条报价,输出:
    code/name/market/state + price/涨跌幅/涨跌额 + 开高低收 + 量额换手 +
    十档买一买二/卖一卖二 + 更新时间。
    """
    if not isinstance(q, dict):
        return {}
    asks, bids = q.get("tenGearSell") or [], q.get("tenGearBuy") or []

    def _top(levels: list[Any]) -> list[dict[str, Any]]:
        out = []
        for lv in levels:
            if not isinstance(lv, dict):
                continue
            price = lv.get("price")
            if price:
                out.append(
                    {"level": lv.get("level") or "", "price": float(price), "vol": int(lv.get("vol") or 0)}
                )
            if len(out) >= 2:
                break
        return out

    return {
        "code": q.get("stockCode") or "",
        "name": q.get("stockName") or "",
        "market": q.get("market") or "",
        "exchange": q.get("exchangeType") or "",
        "state": q.get("stockState") or "",
        "price": q.get("currentPrice"),
        "change_pct": q.get("stockIncrease"),
        "change": q.get("stockRiseFall"),
        "open": q.get("openPrice"),
        "high": q.get("highPrice"),
        "low": q.get("lowPrice"),
        "prev_close": q.get("yClose"),
        "volume": q.get("vol"),
        "amount": q.get("amount"),
        "turnover": q.get("exchangeRate"),
        "amplitude": q.get("amplitude"),
        "pe": q.get("pe"),
        "pb": q.get("pb"),
        "bids": _top(bids),
        "asks": _top(asks),
        "ts": q.get("lastUpdateDate") or "",
    }


def _normalize_push(event: str, data: Any) -> Any:
    """把某事件推送压成紧凑结构(SSE/量化默认用)。

    - ``kLineRealTime``: data 是列表 -> 逐条 ``_normalize_quote``;
    - 其余事件(todayStock/stockPosition 等)本来就紧凑,原样返回。
    """
    if event == "kLineRealTime" and isinstance(data, dict) and isinstance(data.get("data"), list):
        return {"data": [_normalize_quote(q) for q in data["data"] if isinstance(q, dict)], "raw": False}
    return data


class LivePushClient:
    """平台实时行情推送客户端(只读)。

    与对方 App 同协议,连一条常驻 WebSocket,把行情**推**给本地(而非轮询):

    - 握手 URL: ``/socket.io/?EIO=3&source=h5&sign=<_ws_sign(1234)>&transport=websocket``;
    - 连接后发 ``40`` 进入默认命名空间;
    - 订阅: ``42["<event>",{url,event:"subscribe",uuid,params,token,source:"h5",sign,isCompress}]``;
    - 推送: ``42["<event>",{code:1,data:"H4sI...gzip-base64"}]``(已自动解压);
    - 心跳: 服务端定时发 ``2``,客户端回 ``3``。

    后台线程维护连接,断线自动重连(重取 token、重新 sign、重订阅)。
    每个事件支持多个回调;同时保存按事件的 ``latest`` 快照,可被量化策略/页面读取。
    """

    EVENT_CONNECT = "connect"

    def __init__(
        self,
        client: PlatformClient,
        host: str = "114.66.32.152:58868",
        *,
        reconnect_delay: float = 3.0,
        reconnect_max: float = 30.0,
        subscribe_timeout: float = 20.0,
        socket_timeout: float = 15.0,
        auto_start: bool = True,
    ) -> None:
        self._client = client
        self._host = host or ""
        self._reconnect_delay = float(reconnect_delay)
        self._reconnect_max = float(reconnect_max)
        self._subscribe_timeout = float(subscribe_timeout)
        self._socket_timeout = float(socket_timeout)
        self._callbacks: dict[str, list[Any]] = defaultdict(list)
        self._global_callbacks: list[Any] = []  # 全事件回调(SSE/策略通吃)
        self._subs: dict[str, tuple[Any, list[Any]]] = {}  # event -> (params, callbacks)
        self._latest: dict[str, Any] = {}
        self._latest_at: dict[str, float] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._last_error: str = ""
        self._started_at = 0.0
        self._connected_at = 0.0
        self._reconnect_count = 0
        self._push_count: dict[str, int] = defaultdict(int)
        self._loop: Any | None = None  # 当前 WS 事件循环(用于跨线程发订阅)
        self._ws: Any | None = None  # 当前连接对象
        if auto_start:
            self.start()

    # ── 生命周期 ─────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> bool:
        """启动后台推送线程;已启动则幂等返回。"""
        if not HAS_WEBSOCKETS:
            self._last_error = "缺少 websockets 依赖"
            return False
        if not self._client.has_credentials:
            self._last_error = "未配置平台凭证"
            return False
        with self._lock:
            if self.running:
                return True
            self._stop.clear()
            self._started_at = time.time()
            self._thread = threading.Thread(
                target=self._run_loop, name="paper-trading-push", daemon=True
            )
            self._thread.start()
            return True

    def stop(self) -> None:
        """停止推送线程(断开连接)。"""
        self._stop.set()
        thread = self._thread
        self._thread = None
        self._connected = False
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    # ── 订阅 / 回调 ──────────────────────────────────────

    def subscribe(
        self,
        event: str,
        params: list[Any] | None = None,
        callback: Any | None = None,
    ) -> None:
        """订阅某个推送事件。

        - ``event``: ``kLineRealTime``(个股实时)/ ``todayStock``(大盘)/
          ``itemByStepDetailsV3``(分时+盘口)/ ``stockPosition``(持仓) 等;
        - ``params``: 订阅参数(如个股代码列表 ["605080.sh","003032.sz"]);
        - ``callback``: 可选,收到该事件数据时调用 callback(event, data)。
        断线重连后会自动重新订阅所有已注册事件。
        """
        with self._lock:
            self._subs[event] = (list(params or []), self._callbacks[event])
            if callback is not None and callback not in self._callbacks[event]:
                self._callbacks[event].append(callback)
        # 已连上:立即向服务器发订阅帧,拿到实时/快照推送
        self._send_subscribe_now(event, list(params or []))

    def _send_subscribe_now(self, event: str, params: list[Any]) -> None:
        loop = self._loop
        if loop is None or self._ws is None:
            return
        token = self._client._token or ""
        try:
            asyncio.run_coroutine_threadsafe(self._send_frame(loop, event, params, token), loop)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 推送订阅帧失败(%s): %s", event, exc)

    async def _send_frame(
        self, loop: Any, event: str, params: list[Any], token: str
    ) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(self._frame(event, params, token))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("paper_trading: 发送订阅帧失败(%s): %s", event, exc)

    def unsubscribe(self, event: str, callback: Any | None = None) -> None:
        with self._lock:
            if callback is not None:
                self._callbacks[event] = [
                    c for c in self._callbacks[event] if c is not None and c != callback
                ]
                if self._callbacks[event]:
                    self._subs[event] = (list(self._subs.get(event, ([], []))[0]), self._callbacks[event])
                    return
            self._subs.pop(event, None)
            self._callbacks.pop(event, None)

    def add_global_callback(self, callback: Any) -> None:
        """注册全事件回调:任一推送事件都会调用 callback(event, data)。"""
        with self._lock:
            if callback not in self._global_callbacks:
                self._global_callbacks.append(callback)

    def remove_global_callback(self, callback: Any) -> None:
        with self._lock:
            self._global_callbacks = [c for c in self._global_callbacks if c is not callback]

    def latest(self, event: str) -> Any:
        """最近一次收到的(已解码)事件数据;无则 None。"""
        with self._lock:
            return self._latest.get(event)

    def latest_at(self, event: str) -> float:
        with self._lock:
            return self._latest_at.get(event, 0.0)

    def push_count(self, event: str) -> int:
        with self._lock:
            return self._push_count.get(event, 0)

    def status(self) -> dict[str, Any]:
        """连接状态摘要(供 /live/push/status)。"""
        with self._lock:
            return {
                "enabled": HAS_WEBSOCKETS and self._client.has_credentials,
                "running": self.running,
                "connected": self._connected,
                "host": self._host,
                "started_at": datetime.fromtimestamp(self._started_at).isoformat(timespec="seconds")
                if self._started_at
                else "",
                "connected_at": datetime.fromtimestamp(self._connected_at).isoformat(timespec="seconds")
                if self._connected_at
                else "",
                "reconnect_count": self._reconnect_count,
                "last_error": self._last_error,
                "events": {
                    ev: {
                        "params": params,
                        "pushes": self._push_count.get(ev, 0),
                        "last_at": datetime.fromtimestamp(self._latest_at.get(ev, 0)).isoformat(
                            timespec="seconds"
                        )
                        if self._latest_at.get(ev, 0)
                        else "",
                    }
                    for ev, (params, _cb) in self._subs.items()
                },
            }

    # ── 内部:后台线程 ────────────────────────────────────

    def _run_loop(self) -> None:
        backoff = self._reconnect_delay
        while not self._stop.is_set():
            try:
                asyncio.run(self._connect_once())
                backoff = self._reconnect_delay
            except Exception as exc:  # noqa: BLE001 — 重连循环,必须全兜住
                self._last_error = str(exc)[:200]
                _logger.warning("paper_trading: 推送连接异常,%.0fs 后重连: %s", backoff, exc)
            self._connected = False
            if self._stop.is_set():
                break
            self._stop.wait(backoff)
            backoff = min(backoff * 2, self._reconnect_max)

    async def _connect_once(self) -> None:
        client = self._client
        try:
            token = client.login()  # token 未过期则不发网络请求
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"登录失败: {exc}"
            _logger.warning("paper_trading: 推送前登录失败: %s", exc)
            return
        if not self._host:
            self._last_error = "推送 host 为空"
            return
        base = self._host if self._host.startswith("ws") else f"ws://{self._host}"
        if base.endswith("/api"):
            base = base[:-4]
        q = urllib.parse.urlencode(
            {"EIO": 3, "source": "h5", "sign": _ws_sign(1234), "transport": "websocket"}
        )
        url = f"{base}/socket.io/?{q}"
        _logger.info("paper_trading: 推送连接 %s", url[:80])
        try:
            async with websockets.connect(
                url,
                origin="http://" + self._host.split("/")[0],
                compression=None,
                proxy=None,
                ping_interval=None,
            ) as ws:
                self._loop = asyncio.get_running_loop()
                self._ws = ws
                self._connected = True
                self._connected_at = time.time()
                # engine.io open 包
                open_pkt = await asyncio.wait_for(ws.recv(), timeout=self._subscribe_timeout)
                # socket.io v2 默认命名空间 CONNECT
                await ws.send("40")
                await asyncio.wait_for(ws.recv(), timeout=self._subscribe_timeout)
                # 重订阅所有事件
                with self._lock:
                    subs = list(self._subs.items())
                for ev, (params, _cb) in subs:
                    await ws.send(self._frame(ev, params, token))
                    _logger.info("paper_trading: 已订阅 %s %s", ev, params)
                # 读循环
                while not self._stop.is_set():
                    try:
                        frame = await asyncio.wait_for(ws.recv(), timeout=self._socket_timeout)
                    except asyncio.TimeoutError:
                        await ws.send("3")  # 超时兜底发 pong
                        continue
                    if frame == "2":  # engine.io ping -> pong
                        await ws.send("3")
                        continue
                    self._on_frame(frame)
        finally:
            self._connected = False
            self._loop = None
            self._ws = None

    def _frame(self, event: str, params: list[Any], token: str) -> str:
        payload = {
            "url": event,
            "event": "subscribe",
            "uuid": f"{int(time.time() * 1000)}-{abs(hash(event + str(params))) % 10_000_000}",
            "params": list(params or []),
            "token": token,
            "source": "h5",
            "sign": _ws_sign(5678),
            "isCompress": True,
        }
        return f'42["{event}",{json.dumps(payload, ensure_ascii=False)}]'

    def _on_frame(self, frame: str) -> None:
        if not frame.startswith("42"):
            return
        body = frame[2:]
        try:
            arr = json.loads(body)
        except ValueError:
            return
        if not isinstance(arr, list) or len(arr) < 2:
            return
        event, data = arr[0], arr[1]
        if event == self.EVENT_CONNECT:
            return
        decoded = data
        if isinstance(data, dict) and data.get("data") is not None:
            decoded = dict(data)
            decoded["data"] = _gunzip_json_b64(data.get("data"))
        with self._lock:
            self._latest[event] = decoded
            self._latest_at[event] = time.time()
            self._push_count[event] += 1
            callbacks = list(self._callbacks.get(event, [])) + list(self._global_callbacks)
        for cb in callbacks:
            try:
                cb(event, decoded)
            except Exception as exc:  # noqa: BLE001 — 回调异常不能拖垮推送
                _logger.warning("paper_trading: 推送回调异常(%s): %s", event, exc)

