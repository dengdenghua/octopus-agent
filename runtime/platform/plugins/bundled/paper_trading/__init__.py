"""模拟炒股(paper_trading)插件 — 可插拔、带页面的模拟交易模块。

核心是自含行情模拟器(内置 A 股股票池 + 盘中随机游走报价),提供:

- 一个完整前端页面 ``/api/plugins/paper-trading/page``(行情/交易/平台交易/自选/持仓/成交);
- 一组交易 API(报价/下单/持仓/成交/重置);
- 一个 ``paper_trading.quote`` skill,让 agent 也能查询模拟报价;
- **平台配资盘**(``/platform/*``):申请资金 / 合约 / 持仓 / 真实买卖委托,
  写操作强制 ``confirm`` 二次确认后才真正提交到平台;
- 可选的**平台实时大盘**(``live_mode: true``):只读拉取配置的后端行情。

本地模拟账户持久化到 JSON,重启不丢;平台操作走平台账号。纯个人练习用。
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

from runtime.execution.suckers.registry import Skill
from runtime.platform.plugins.plugin_base import ModulePlugin

from .live import (
    DEFAULT_BASE_URL,
    LiveDataSource,
    LivePushClient,
    _normalize_push,
)
from .service import PaperTradingEngine, WatchlistStore, is_trading_time

try:
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import HTMLResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    StreamingResponse = None  # type: ignore[assignment,misc]
    BaseModel = None  # type: ignore[assignment,misc]


class _OrderIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    code: str
    side: str = "buy"
    order_type: str = "market"
    price: float | None = None
    qty: int = 100


class _CredentialsIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    phone: str = ""
    password: str = ""


class _GroupIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    name: str = ""


class _StockIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    code: str = ""


class _FavIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    code: str = ""


class _PlatformApplyIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    """申请/扩大配资合约(真实操作,需 confirm)。"""

    contract_type: int = 1  # 1按天 2按周 3按月
    principal: float = 1000.0  # 保证金
    multiple: int = 10  # 倍数
    confirm: bool = False


class _PlatformOrderIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    """平台真实买卖委托(需 confirm)。entrust_type: 0限价 1市价。"""

    contract_id: str = ""
    stock_code: str = ""
    stock_name: str = ""
    entrust_type: int = 0
    price: float | None = None
    qty: int = 100
    confirm: bool = False


class _PlatformMoneyIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    """追加资金 / 提盈(需 confirm)。"""

    contract_id: str = ""
    money: float = 0.0
    confirm: bool = False


class _PlatformCancelIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    """撤单(需 confirm)。"""

    order_id: str = ""
    contract_id: str = ""
    confirm: bool = False


class _PlatformStockIn(BaseModel):  # type: ignore[misc]  # noqa: PGH003
    """平台卖出面板查询(只读)。"""

    contract_id: str = ""
    stock_code: str = ""


def _build_engine(
    initial_cash: float = 1_000_000.0,
    data_dir: str = "~/.octopus/data/paper_trading",
) -> PaperTradingEngine:
    engine = PaperTradingEngine(initial_cash=initial_cash, data_dir=data_dir)
    engine.load()
    return engine


def _proxy_disabled_page(base_url: str) -> str:
    """``proxy_origin`` 未开启时的说明页。

    不静默给一个空白 iframe —— 直接说明为什么关着、怎么开、以及开启的代价。
    """
    from .proxy import upstream_origin

    origin = upstream_origin(base_url) or "http://114.66.32.152:58868"
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>模拟炒股 · 平台原站未接入</title>
<style>
  body{{margin:0;background:#10131f;color:#e6e9f0;
       font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;}}
  .box{{max-width:560px;padding:28px 32px;background:#1a1d33;
        border:1px solid #39415f;border-radius:8px;line-height:1.9;}}
  h1{{font-size:16px;margin:0 0 12px;color:#f0b90b;}}
  code{{background:#10131f;border:1px solid #39415f;border-radius:3px;
        padding:1px 6px;font-size:12px;}}
  p{{margin:10px 0;font-size:13px;color:#9aa4b8;}}
  a{{color:#f0b90b;}}
</style></head><body><div class="box">
<h1>平台原站接入未开启</h1>
<p>本页通过同源反向代理嵌入平台原站。该功能默认关闭,需在插件配置里设置
   <code>proxy_origin: true</code> 后重启后端。</p>
<p><b>开启前请了解代价</b>:同源代理会让原站脚本以本应用的 origin 权限运行,
   可读取同源 <code>localStorage</code>(其中包含本应用的登录令牌);
   且原站为明文 HTTP 传输。</p>
<p>也可以直接在新窗口打开原站(不共享登录态):
   <a href="{origin}/trade/#/transaction" target="_blank" rel="noreferrer noopener">
   {origin}/trade ↗</a></p>
</div></body></html>"""


class PaperTradingPlugin(ModulePlugin):
    name = "paper_trading"
    display_name = "模拟炒股"
    version = "0.4.0"
    description = (
        "模拟炒股练习插件 — 本地模拟交易面板 + 「平台交易」页对接平台配资盘"
        "(申请资金/合约/持仓/真实买卖委托,全部二次确认),可选用 live_mode 只读"
        "接入平台实时大盘。纯个人练习用。"
    )
    author = "Octopus"

    def __init__(self) -> None:
        super().__init__()
        self.engine: PaperTradingEngine | None = None
        self.live: LiveDataSource | None = None
        self.push: LivePushClient | None = None
        self.watchlists: WatchlistStore | None = None
        self.auto_trade = False  # 程序化/agent 自动下单开关(默认关,须显式开启)
        self.proxy_origin = False  # 平台原站同源反代(默认关,须显式开启;见 proxy.py)
        self._proxy_base_url = ""
        self._proxy_state_dir = "~/.octopus/data/paper_trading"
        self._proxy_credentials_file = "~/.octopus/data/paper_trading/credentials.json"

    # ── 生命周期 ─────────────────────────────────────────

    def on_load(self, ctx: Any) -> None:
        cfg = dict(ctx.config or {})
        initial_cash = float(cfg.get("initial_cash", 1_000_000))
        data_dir = str(cfg.get("data_dir") or "~/.octopus/data/paper_trading")
        self.engine = _build_engine(initial_cash=initial_cash, data_dir=data_dir)
        self.watchlists = WatchlistStore(data_dir=data_dir)
        credentials_file = str(
            cfg.get("credentials_file") or "~/.octopus/data/paper_trading/credentials.json"
        )
        # 可选平台实时行情(只读)。无凭证/失败自动降级,不影响本地模拟。
        if bool(cfg.get("live_mode", True)):
            self.live = LiveDataSource.from_config(
                cfg, state_dir=data_dir, credentials_file=credentials_file
            )
        self.auto_trade = bool(cfg.get("auto_trade", False))
        self.proxy_origin = bool(cfg.get("proxy_origin", False))
        self._proxy_base_url = str(cfg.get("base_url") or DEFAULT_BASE_URL)
        self._proxy_state_dir = data_dir
        self._proxy_credentials_file = credentials_file
        super().on_load(ctx)

    # ── Skill:agent 可查询模拟报价 ────────────────────────

    def register_skills(self) -> None:
        if self.ctx is None or self.engine is None:
            return
        with contextlib.suppress(Exception):
            self.ctx.register_skill(
                Skill(
                    name="paper_trading.quote",
                    description=(
                        "查询模拟炒股(paper_trading)插件里某个 A 股的当前模拟报价"
                        "(现价/涨跌幅/昨收)。参数 code 必填,如 '600519'。纯模拟数据,"
                        "不连真实行情。"
                    ),
                    summary="查询模拟行情报价(code 必填)",
                    affinity=["trading", "stock", "quote", "market"],
                    cost_profile="low",
                    trusted_source="plugin://paper_trading",
                    handler=self._quote_skill,
                )
            )
        if self.auto_trade:
            with contextlib.suppress(Exception):
                self.ctx.register_skill(
                    Skill(
                        name="paper_trading.trade",
                        description=(
                            "在平台配资盘**真实下单**(平台为模拟盘):买入/卖出/申请资金/追加资金/"
                            "提盈/撤单。**仅当用户明确要求自动交易且 auto_trade 已开启时才可调用**;"
                            "未开启时一律拒绝。参数:action 必填(buy/sell/apply/add_capital/withdraw/"
                            "cancel)+ 对应字段(buy/sell 需要 contract_id、stock_code、stock_name、qty、"
                            "entrust_type(0限价/1市价)、price(限价必填);apply 需要 principal、multiple、"
                            "contract_type(1按天/2按周/3按月);add_capital/withdraw 需要 contract_id、money;"
                            "cancel 需要 order_id、contract_id)。qty 须为 100 的整数倍。这是真实操作,"
                            "提交即被平台受理、无法撤销,下单前务必核对参数。可用 dry_run=true 先试运行。"
                        ),
                        summary="平台真实下单(action 必填;仅 auto_trade 开启可用)",
                        affinity=["trading", "stock", "order", "trade", "position"],
                        cost_profile="low",
                        trusted_source="plugin://paper_trading",
                        handler=self._trade_skill,
                    )
                )

    def _quote_skill(self, code: str = "", **_kwargs: Any) -> dict[str, Any]:
        engine = self.engine
        if engine is None:
            return {"error": "paper_trading 插件未初始化"}
        if not code:
            return {"error": "需要 code 参数,如 600519"}
        quote = engine.quote(code)
        if quote is None:
            return {"error": f"未知股票代码: {code}"}
        return quote

    # ── agent 自动下单 skill(auto_trade 开启后可用) ──────

    def _trade_skill(self, action: str = "", dry_run: bool = False, **kw: Any) -> dict[str, Any]:
        """``paper_trading.trade``:agent 直接向平台真实下单。

        仅在 ``auto_trade=true`` 时放行(等于用户授权程序化交易);缺授权一律拒绝。
        ``dry_run=true`` 只返回执行计划,不真正提交。
        """
        if not self.auto_trade:
            return {
                "ok": False,
                "error": (
                    "自动交易未开启(auto_trade=false):已拒绝自动下单。"
                    "请让用户在「平台交易」页人工操作,或开启 auto_trade 配置后重启插件。"
                ),
            }
        client = self._platform_client()
        if client is None:
            return {"ok": False, "error": "未连接平台账号,请先在「平台交易」页登录"}
        plan = self._trade_plan(client, action, **kw)
        if isinstance(plan, dict) and "error" in plan:
            return {"ok": False, "error": plan["error"]}
        what, fn, fn_kw = plan
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "action": what,
                "params": dict(fn_kw),
                "note": "未提交:dry_run=true 仅生成执行计划",
            }
        return self._platform_write(fn, confirm=True, what=what, **fn_kw)

    def _trade_plan(self, client, action: str, **kw: Any) -> Any:
        """把 agent 的 action 参数翻译成平台客户端调用 (what, fn, kwargs)。"""
        action = (action or "").strip().lower()

        if action in ("buy", "sell"):
            missing = [
                k for k in ("contract_id", "stock_code", "stock_name", "qty") if not kw.get(k)
            ]
            if missing:
                return {
                    "error": f"{'买入' if action == 'buy' else '卖出'}缺少参数: {', '.join(missing)}"
                }
            entrust_type = int(kw.get("entrust_type", 0))
            price = kw.get("price")
            if entrust_type == 0 and not price:
                return {"error": "限价单需要 price(市价 entrust_type=1 可不填)"}
            qty = int(kw.get("qty") or 0)
            if qty <= 0 or qty % 100 != 0:
                return {"error": "数量必须为正的 100 整数倍"}
            fn = client.buy if action == "buy" else client.sell
            return (
                "真实买入" if action == "buy" else "真实卖出",
                fn,
                {
                    "contract_id": str(kw["contract_id"]),
                    "stock_code": str(kw["stock_code"]),
                    "stock_name": str(kw["stock_name"]),
                    "entrust_type": entrust_type,
                    "price": price,
                    "number": qty,
                },
            )
        if action == "apply":
            missing = [k for k in ("principal", "multiple") if not kw.get(k)]
            if missing:
                return {"error": f"申请资金缺少参数: {', '.join(missing)}"}
            principal = float(kw.get("principal") or 0)
            if principal < 100:
                return {"error": "保证金至少 100 元"}
            return (
                "申请资金",
                client.apply_contract,
                {
                    "contract_type": int(kw.get("contract_type", 1)),
                    "principal": principal,
                    "multiple": int(kw.get("multiple", 10)),
                },
            )
        if action in ("add_capital", "withdraw"):
            missing = [k for k in ("contract_id", "money") if not kw.get(k)]
            if missing:
                return {
                    "error": f"{'追加资金' if action == 'add_capital' else '提盈'}缺少参数: {', '.join(missing)}"
                }
            money = float(kw.get("money") or 0)
            if money <= 0:
                return {"error": "金额必须大于 0"}
            fn = client.add_capital if action == "add_capital" else client.withdraw_profit
            return (
                "追加资金" if action == "add_capital" else "提取盈利",
                fn,
                {"contract_id": str(kw["contract_id"]), "money": money},
            )
        if action == "cancel":
            missing = [k for k in ("order_id", "contract_id") if not kw.get(k)]
            if missing:
                return {"error": f"撤单缺少参数: {', '.join(missing)}"}
            return (
                "撤单",
                client.cancel_order,
                {"order_id": str(kw["order_id"]), "contract_id": str(kw["contract_id"])},
            )
        return {
            "error": f"未知 action: {action!r}(可选 buy/sell/apply/add_capital/withdraw/cancel)"
        }

    # ── 平台配资盘(真实交易)辅助 ──────────────────────────

    def _platform_client(self):
        """取已登录的平台客户端;未启用 live_mode / 未配凭证返回 None。"""
        live = self.live
        if live is None or not live.configured:
            return None
        return live.client

    def _push_client(self) -> LivePushClient | None:
        """懒创建并启动实时推送客户端(常驻 WS,行情推送而非轮询)。

        首次调用时启动后台线程;凭证缺失/依赖缺失时返回 None(纯降级,不抛异常)。
        供页面 SSE、量化策略回调、/live/push/* 使用。
        """
        live = self.live
        if live is None or not live.configured:
            return None
        push = self.push
        if push is None:
            host = live.client.base_url.replace("http://", "").replace("https://", "").rstrip("/")
            if host.endswith("/api"):
                host = host[:-4]
            try:
                push = LivePushClient(live.client, host=host, auto_start=True)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("paper_trading: 推送客户端创建失败: %s", exc)
                return None
            self.push = push
        return push

    def _platform_read(self, fn, **kw):
        """只读平台接口:统一包装,失败/未登录优雅降级为 {ok:false}。"""
        client = self._platform_client()
        if client is None:
            return {
                "ok": False,
                "error": "未连接平台账号,请先在「平台交易」页登录(配置平台手机号+密码)",
            }
        try:
            return {"ok": True, "data": fn(**kw)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _platform_write(self, fn, *, confirm: bool, what: str, **kw):
        """平台真实操作(申请资金/买卖/追加/提盈/撤单)。

        必须显式 ``confirm=True`` 才会真正打到平台;否则直接拒绝。
        任何网络/业务错误都包装为 {ok:false, error},不让页面崩。
        """
        if not confirm:
            return {
                "ok": False,
                "error": f"已拦截:该操作将在平台真实执行({what}),请在页面确认后重试",
            }
        client = self._platform_client()
        if client is None:
            return {
                "ok": False,
                "error": "未连接平台账号,请先在「平台交易」页登录",
            }
        try:
            return {"ok": True, "data": fn(**kw)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ── 页面 + API 路由 ───────────────────────────────────

    def register_routes(self) -> None:
        if self.ctx is None or APIRouter is None:
            return
        engine = self.engine
        if engine is None:
            return
        # degrade, don't crash:无 FastAPI 上下文(如纯 skill 环境)则不挂路由
        app = self.ctx.fastapi_app
        if app is None:
            return
        plugin_dir = self.ctx.plugin_dir
        page_path = Path(plugin_dir) / "page" / "index.html"

        router = APIRouter(prefix="/api/plugins/paper-trading", tags=["paper_trading"])

        # 平台原站同源反代(默认关闭)。开启后 /page 里的 iframe 才有东西可指。
        # 段名必须是 origin 而非 assets —— 详见 proxy.py 的说明。
        proxy_mounted = False
        if self.proxy_origin:
            from .proxy import register_origin_proxy

            proxy_mounted = register_origin_proxy(
                router,
                base_url=self._proxy_base_url,
                state_dir=self._proxy_state_dir,
                credentials_file=self._proxy_credentials_file,
            )

        @router.get("/page", response_class=HTMLResponse)
        def serve_page() -> HTMLResponse:
            if not proxy_mounted:
                return HTMLResponse(content=_proxy_disabled_page(self._proxy_base_url))
            html = "模拟炒股页面缺失(page/index.html)"
            try:
                if page_path.exists():
                    html = page_path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                html = f"读取页面失败: {exc}"
            return HTMLResponse(content=html)

        @router.get("/watch", response_class=HTMLResponse)
        def serve_watch_page() -> HTMLResponse:
            watch_html = "盯盘页面缺失(page/watch.html)"
            try:
                watch_path = Path(plugin_dir) / "page" / "watch.html"
                if watch_path.exists():
                    watch_html = watch_path.read_text(encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                watch_html = f"读取盯盘页面失败: {exc}"
            return HTMLResponse(content=watch_html)

        @router.get("/symbols")
        def symbols() -> dict[str, Any]:
            return {"symbols": [{"code": c, "name": n} for c, n, _b in engine.universe]}

        @router.get("/quotes")
        def quotes() -> dict[str, Any]:
            engine.tick()
            return {"quotes": engine.quotes(), "trading": is_trading_time()}

        @router.get("/live/overview")
        def live_overview() -> dict[str, Any]:
            live = self.live
            if live is None:
                return {
                    "available": False,
                    "enabled": False,
                    "source": "",
                    "message": "未启用 live_mode,仅本地模拟行情",
                }
            return live.overview()

        @router.get("/live/watch")
        def live_watch(force: bool = False) -> dict[str, Any]:
            live = self.live
            if live is None:
                return {
                    "available": False,
                    "enabled": False,
                    "source": "",
                    "message": "未启用 live_mode,仅本地模拟行情",
                }
            return live.watch(force=force)

        @router.get("/live/status")
        def live_status() -> dict[str, Any]:
            live = self.live
            if live is None:
                return {
                    "enabled": False,
                    "configured": False,
                    "available": False,
                    "account": "",
                    "source": "",
                }
            return {
                "enabled": True,
                "configured": live.configured,
                "available": live.available,
                "account": live.account if live.configured else "",
                "source": live.client.base_url,
            }

        @router.post("/live/credentials")
        def set_credentials(payload: _CredentialsIn) -> dict[str, Any]:
            live = self.live
            if live is None:
                raise HTTPException(status_code=400, detail="未启用 live_mode")
            return live.save_credentials(payload.phone, payload.password)

        @router.post("/live/credentials/clear")
        def clear_credentials() -> dict[str, Any]:
            live = self.live
            if live is None:
                return {"ok": False, "message": "未启用 live_mode"}
            return live.clear_credentials()

        @router.get("/live/push/status")
        def live_push_status() -> dict[str, Any]:
            """实时推送连接状态(WS 是否在连、各事件订阅与最近推送时间)。"""
            push = self._push_client()
            if push is None:
                return {"enabled": False, "running": False, "connected": False, "error": "推送未启用(缺凭证/依赖)"}
            return push.status()

        @router.get("/live/push/subscribe")
        def live_push_subscribe(event: str = "kLineRealTime", codes: str = "") -> dict[str, Any]:
            """订阅某个推送事件并返回其最新(已解码)快照。

            - ``event``: kLineRealTime(个股实时+十档盘口+分时) / todayStock(大盘) /
              stockPosition(持仓) / itemByStepDetailsV3(分时详情) 等;
            - ``codes``: 逗号分隔的代码列表,如 "605080.sh,003032.sz"(仅个股类事件需要)。
            订阅后该事件会持续推送到本地;可通过 /live/push/stream 或 Python 回调消费。
            """
            push = self._push_client()
            if push is None:
                return {"ok": False, "error": "推送未启用(缺凭证/依赖)"}
            params = [c.strip() for c in codes.split(",") if c.strip()]
            push.subscribe(event, params)
            return {"ok": True, "event": event, "params": params, "latest": push.latest(event)}

        @router.get("/live/push/latest")
        def live_push_latest(event: str = "kLineRealTime", light: bool = True) -> dict[str, Any]:
            """查询某个推送事件的当前最新快照(已解码)。

            - ``event``: kLineRealTime / todayStock / stockPosition 等;
            - ``light=true``: kLineRealTime 返回紧凑字段(默认,省流量)。
            供量化策略/页面按需取当前状态,无需订阅。
            """
            push = self._push_client()
            if push is None:
                return {"ok": False, "error": "推送未启用(缺凭证/依赖)"}
            latest = push.latest(event)
            if latest is None:
                return {"ok": True, "event": event, "latest": None}
            if light and event == "kLineRealTime":
                latest = _normalize_push(event, latest)
            return {"ok": True, "event": event, "latest": latest}

        @router.get("/live/push/stream")
        def live_push_stream(light: bool = True) -> Any:
            """SSE 实时推送流:把平台 WS 推送逐条转发给浏览器(替代轮询)。

            事件格式(每行一个):
                event: <event_name>
                data: <JSON>
            心跳每 15s 发一次 comment 保活。
            """
            push = self._push_client()
            if push is None or StreamingResponse is None:
                return {"ok": False, "error": "推送未启用(缺凭证/依赖)"}

            send_q: "queue.Queue[tuple[str, dict[str, Any]]]" = queue.Queue()

            def _on_event(event: str, data: dict[str, Any]) -> None:
                send_q.put((event, _normalize_push(event, data) if light else data))

            # 全事件回调:之后任何 /live/push/subscribe 订阅的新推送都会转发到这里。
            push.add_global_callback(_on_event)
            # 立即补发所有已订阅事件的最新快照,一接入就有数据。
            for ev in list(push._subs.keys()):
                latest = push.latest(ev)
                if latest is not None:
                    send_q.put((ev, _normalize_push(ev, latest) if light else latest))

            def _gen():
                try:
                    while True:
                        try:
                            event, data = send_q.get(timeout=15)
                            yield f"event: {event}\n"
                            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                        except queue.Empty:
                            yield ": keepalive\n\n"
                finally:
                    push.remove_global_callback(_on_event)

            return StreamingResponse(_gen(), media_type="text/event-stream")

        @router.post("/live/refresh")
        def refresh_live() -> dict[str, Any]:
            live = self.live
            if live is None:
                return {
                    "available": False,
                    "enabled": False,
                    "message": "未启用 live_mode,仅本地模拟行情",
                }
            return live.overview(force=True)

        # ── 平台配资盘(真实交易) ───────────────────────────
        # 只读:合约/持仓/委托/费率/档位/卖出面板;操作类一律要求 confirm。

        @router.get("/platform/status")
        def platform_status() -> dict[str, Any]:
            live = self.live
            if live is None or not live.configured:
                return {
                    "enabled": True,
                    "configured": False,
                    "available": False,
                    "account": "",
                    "source": self.live.client.base_url if self.live else "",
                    "auto_trade": self.auto_trade,
                }
            return {
                "enabled": True,
                "configured": True,
                "available": True,
                "account": live.account,
                "source": live.client.base_url,
                "auto_trade": self.auto_trade,
            }

        @router.get("/platform/overview")
        def platform_overview() -> dict[str, Any]:
            client = self._platform_client()
            if client is None:
                return {
                    "ok": False,
                    "error": "未连接平台账号,请先登录",
                    "member": {},
                    "contracts": [],
                }
            try:
                member = client.get_member_info()
                contracts = client.list_contracts()
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc), "member": {}, "contracts": []}
            return {"ok": True, "member": member, "contracts": contracts}

        @router.get("/platform/contracts")
        def platform_contracts() -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(self.live.client.list_contracts)

        @router.get("/platform/contract-details")
        def platform_contract_details() -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(self.live.client.contract_list_full)

        @router.get("/platform/positions")
        def platform_positions() -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(self.live.client.positions)

        @router.get("/platform/orders")
        def platform_orders(type_: int = 1, current: int = 1, size: int = 20) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(
                self.live.client.orders, type_=type_, current=current, size=size
            )

        @router.get("/platform/money-records")
        def platform_money_records(
            contract_id: str = "",
            type_: int | str = "",
            date: str = "",
            current: int = 1,
            size: int = 20,
        ) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(
                self.live.client.money_records,
                contract_id=contract_id,
                type_=type_,
                date=date,
                current=current,
                size=size,
            )

        @router.get("/platform/rate-table")
        def platform_rate_table() -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(self.live.client.rate_table)

        @router.get("/platform/apply-options")
        def platform_apply_options() -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(self.live.client.apply_options)

        @router.get("/platform/sell-panel")
        def platform_sell_panel(contract_id: str = "", stock_code: str = "") -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_read(
                self.live.client.sell_panel,
                contract_id=contract_id,
                stock_code=stock_code,
            )

        @router.post("/platform/apply-contract")
        def platform_apply_contract(payload: _PlatformApplyIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.apply_contract,
                confirm=payload.confirm,
                what="申请配资资金",
                contract_type=payload.contract_type,
                principal=payload.principal,
                multiple=payload.multiple,
            )

        @router.post("/platform/buy")
        def platform_buy(payload: _PlatformOrderIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.buy,
                confirm=payload.confirm,
                what="真实买入",
                contract_id=payload.contract_id,
                stock_code=payload.stock_code,
                stock_name=payload.stock_name,
                entrust_type=payload.entrust_type,
                price=payload.price,
                number=payload.qty,
            )

        @router.post("/platform/sell")
        def platform_sell(payload: _PlatformOrderIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.sell,
                confirm=payload.confirm,
                what="真实卖出",
                contract_id=payload.contract_id,
                stock_code=payload.stock_code,
                stock_name=payload.stock_name,
                entrust_type=payload.entrust_type,
                price=payload.price,
                number=payload.qty,
            )

        @router.post("/platform/add-capital")
        def platform_add_capital(payload: _PlatformMoneyIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.add_capital,
                confirm=payload.confirm,
                what="追加资金",
                contract_id=payload.contract_id,
                money=payload.money,
            )

        @router.post("/platform/withdraw-profit")
        def platform_withdraw_profit(payload: _PlatformMoneyIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.withdraw_profit,
                confirm=payload.confirm,
                what="提取盈利",
                contract_id=payload.contract_id,
                money=payload.money,
            )

        @router.post("/platform/cancel-order")
        def platform_cancel_order(payload: _PlatformCancelIn) -> dict[str, Any]:
            if self.live is None:
                return {"ok": False, "error": "未启用平台接入"}
            return self._platform_write(
                self.live.client.cancel_order,
                confirm=payload.confirm,
                what="撤单",
                order_id=payload.order_id,
                contract_id=payload.contract_id,
            )

        @router.get("/quote/{code}")
        def quote(code: str) -> dict[str, Any]:
            q = engine.quote(code)
            if q is None:
                raise HTTPException(status_code=404, detail=f"未知股票: {code}")
            return q

        @router.get("/kline/{code}")
        def kline(code: str, days: int = 60) -> dict[str, Any]:
            if days < 5:
                days = 5
            if days > 250:
                days = 250
            candles = engine.kline(code, days=days)
            if not candles:
                raise HTTPException(status_code=404, detail=f"未知股票: {code}")
            return {"code": code, "candles": candles}

        @router.get("/orderbook/{code}")
        def orderbook(code: str, levels: int = 10) -> dict[str, Any]:
            if levels < 1:
                levels = 1
            if levels > 20:
                levels = 20
            book = engine.order_book(code, levels=levels)
            if book is None:
                raise HTTPException(status_code=404, detail=f"未知股票: {code}")
            return book

        @router.get("/watchlists")
        def watchlists() -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                return {"groups": []}
            groups = []
            for g in wl.list():
                quotes = []
                for code in g["codes"]:
                    q = engine.quote(code)
                    if q:
                        quotes.append(q)
                groups.append({**g, "quotes": quotes})
            return {
                "groups": groups,
                "default_group_id": wl.default_group().id,
                "universe": [{"code": c, "name": n} for c, n, _b in engine.universe],
            }

        @router.post("/watchlists")
        def create_group(payload: _GroupIn) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            return wl.create_group(payload.name)

        @router.patch("/watchlists/{group_id}")
        def rename_group(group_id: str, payload: _GroupIn) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            return wl.rename_group(group_id, payload.name)

        @router.delete("/watchlists/{group_id}")
        def delete_group(group_id: str) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            return wl.delete_group(group_id)

        @router.post("/watchlists/{group_id}/stocks")
        def add_stock(group_id: str, payload: _StockIn) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            if engine.quote(payload.code) is None:
                return {"ok": False, "message": f"未知股票: {payload.code}"}
            return wl.add_stock(group_id, payload.code)

        @router.delete("/watchlists/{group_id}/stocks/{code}")
        def remove_stock(group_id: str, code: str) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            return wl.remove_stock(group_id, code)

        @router.post("/watchlists/fav")
        def toggle_fav(payload: _FavIn) -> dict[str, Any]:
            wl = self.watchlists
            if wl is None:
                raise HTTPException(status_code=400, detail="自选未初始化")
            if engine.quote(payload.code) is None:
                return {"ok": False, "message": f"未知股票: {payload.code}"}
            if wl.has_code(payload.code):
                # 已在自选中 → 从所有分组移除
                for g in wl.list():
                    wl.remove_stock(g["id"], payload.code)
                return {"ok": True, "code": payload.code, "in_watchlist": False}
            g = wl.default_group()
            return wl.add_stock(g.id, payload.code)

        @router.get("/account")
        def account() -> dict[str, Any]:
            return engine.account()

        @router.get("/orders")
        def orders(limit: int = 100) -> dict[str, Any]:
            return {"orders": engine.orders(limit=limit)}

        @router.post("/orders")
        def create_order(payload: _OrderIn) -> dict[str, Any]:
            return engine.place_order(
                code=payload.code,
                side=payload.side,
                order_type=payload.order_type,
                price=payload.price,
                qty=payload.qty,
            )

        @router.post("/reset")
        def reset() -> dict[str, Any]:
            return engine.reset()

        app.include_router(router)

    @property
    def capabilities(self) -> list[Any]:
        from runtime.platform.plugins.plugin_base import ProvidedCapability

        caps = super().capabilities
        caps.append(
            ProvidedCapability(
                type="api",
                name=f"{self.name}.page",
                description="带页面的模拟炒股面板(/api/plugins/paper-trading/page)",
            )
        )
        return caps


__all__ = ["PaperTradingPlugin"]
