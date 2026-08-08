from __future__ import annotations

import contextvars
import os
import queue
import threading
from typing import Any

from .registry import Skill, SkillRegistry
from .testing import SkillExpect, SkillTestCase

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]

try:
    import trafilatura  # type: ignore[import-untyped]

    TRAFILATURA_AVAILABLE = True
except ImportError:  # pragma: no cover
    TRAFILATURA_AVAILABLE = False
    trafilatura = None  # type: ignore[assignment]


# ═══════════════════════════════════════════════════════════
# fetch_url
# ═══════════════════════════════════════════════════════════


def _extract_main_content(html: str, url: str) -> dict[str, Any] | None:
    if not TRAFILATURA_AVAILABLE or not html:
        return None
    try:
        meta = trafilatura.extract_metadata(html, default_url=url)
        text = trafilatura.extract(
            html,
            url=url,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            with_metadata=False,
        )
    except (OSError, ValueError):
        return None
    if not text:
        return None
    meta_dict: dict[str, Any] = {}
    if meta is not None:
        as_dict = meta.as_dict() if hasattr(meta, "as_dict") else {}
        for key in ("title", "author", "date", "sitename", "description", "language"):
            val = as_dict.get(key)
            if val:
                meta_dict[key] = val
    return {"text": text, "metadata": meta_dict}


def _fetch_url(
    url: str = "",
    *,
    timeout_ms: int = 5000,
    max_bytes: int = 100_000,
    client: Any = None,
    allow_private: bool = False,
    extract: bool = False,
    **_kw: Any,
) -> dict[str, Any]:
    if not url:
        return {"error": "missing url"}

    from runtime.safety.auth.url_guard import check_url

    verdict = check_url(url, allow_private=allow_private)
    if not verdict.allow:
        return {
            "error": f"ssrf_blocked: {verdict.reason}",
            "url": url,
            "blocked": True,
        }

    close_after = False
    pinned_fetch = client is None
    if client is None and not HTTPX_AVAILABLE:
        return {"error": "httpx not installed"}

    try:
        if pinned_fetch:
            from runtime.safety.auth.url_guard import safe_httpx_get

            resp = safe_httpx_get(
                url,
                timeout=timeout_ms / 1000,
                allow_private=allow_private,
                follow_redirects=False,
            )
        else:
            resp = client.get(url)
    except Exception as e:  # noqa: BLE001
        return {"error": f"http_error: {type(e).__name__}: {e}"}
    finally:
        if close_after:
            client.close()

    raw = resp.text
    result: dict[str, Any] = {
        "url": str(resp.url),
        "status_code": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "length": len(raw),
    }

    if extract:
        extracted = _extract_main_content(raw, str(resp.url))
        if extracted is not None:
            text = extracted["text"]
            truncated = len(text) > max_bytes
            if truncated:
                text = text[:max_bytes]
            result.update(
                {
                    "extracted": True,
                    "truncated": truncated,
                    "content": text,
                    "metadata": extracted["metadata"],
                }
            )
            return result
        result["extract_failed"] = (
            "trafilatura_unavailable" if not TRAFILATURA_AVAILABLE else "no_main_content"
        )

    body = raw
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
    result.update(
        {
            "extracted": False,
            "truncated": truncated,
            "content": body,
        }
    )
    return result


# ═══════════════════════════════════════════════════════════
# web_search
# ═══════════════════════════════════════════════════════════


def _resolve_backend() -> str:
    explicit = (os.environ.get("WEB_SEARCH_BACKEND") or "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("DOUBAO_SEARCH_API_KEY"):
        return "doubao"
    if os.environ.get("TAVILY_API_KEY"):
        return "tavily"
    if os.environ.get("BRAVE_API_KEY"):
        return "brave"
    if os.environ.get("SERPER_API_KEY"):
        return "serper"
    if os.environ.get("SEARXNG_URL"):
        return "searxng"
    return "ddg"


def _web_search(
    query: str = "",
    *,
    max_results: int = 5,
    timeout_ms: int = 8000,
    client: Any = None,
    backend: str | None = None,
    **_kw: Any,
) -> dict[str, Any]:
    if not query:
        return {"error": "missing query", "results": []}

    chosen = (backend or _resolve_backend()).lower()
    close_after = False
    if client is None:
        if not HTTPX_AVAILABLE:
            return {"error": "httpx not installed", "results": []}
        client = httpx.Client(timeout=timeout_ms / 1000)
        close_after = True

    try:
        if chosen == "doubao":
            key = os.environ.get("DOUBAO_SEARCH_API_KEY", "")
            if not key:
                return {"error": "doubao_missing_key", "results": []}
            return _doubao_search(client, key, query, max_results)
        if chosen == "tavily":
            key = os.environ.get("TAVILY_API_KEY", "")
            if not key:
                return {"error": "tavily_missing_key", "results": []}
            return _tavily_search(client, key, query, max_results)
        if chosen == "brave":
            key = os.environ.get("BRAVE_API_KEY", "")
            if not key:
                return {"error": "brave_missing_key", "results": []}
            return _brave_search(client, key, query, max_results)
        if chosen == "serper":
            key = os.environ.get("SERPER_API_KEY", "")
            if not key:
                return {"error": "serper_missing_key", "results": []}
            return _serper_search(client, key, query, max_results)
        if chosen == "searxng":
            base = os.environ.get("SEARXNG_URL", "")
            if not base:
                return {"error": "searxng_missing_url", "results": []}
            return _searxng_search(client, base, query, max_results)
        if chosen == "ddg":
            return _ddg_search(client, query, max_results)
        return {"error": f"unknown_backend: {chosen}", "results": []}
    finally:
        if close_after:
            client.close()


def _doubao_search(client: Any, api_key: str, query: str, max_results: int) -> dict[str, Any]:
    """豆包搜索 (Doubao Search) — 火山引擎为 AI Agent 构建的联网搜索服务。

    使用 Global 版端点 (``search_api/global_search``)，覆盖全球站点、每条结果带
    ``ContentTokenCount`` 等对 Agent 友好的字段。返回字段参考官方文档与开源实现
    huashu-doubao-search。
    """
    endpoint = "https://open.feedcoopapi.com/search_api/global_search"
    try:
        r = client.post(
            endpoint,
            json={
                "query": query,
                "doc_count": max_results,
                "max_snippet_length": 600,
                "max_image_count_per_doc": 0,
            },
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"doubao_error: {type(e).__name__}: {e}", "results": []}

    meta_err = (data.get("ResponseMetadata") or {}).get("Error")
    if meta_err:
        return {
            "error": f"doubao_api_error: {str(meta_err.get('Message') or meta_err)[:300]}",
            "results": [],
        }

    docs = (data.get("Result") or {}).get("Documents") or []
    results: list[dict[str, str]] = []
    for item in docs[:max_results]:
        snippets: list[str] = []
        for part in item.get("Snippet") or []:
            if part.get("Type") == "text" and part.get("Text"):
                snippets.append(str(part["Text"]).strip())
        doc_info = item.get("DocumentInfo") or {}
        results.append(
            {
                "title": item.get("Title") or "",
                "url": item.get("Url") or "",
                "snippet": "\n".join(snippets)[:400],
                "host": (item.get("HostInfo") or {}).get("Hostname") or "",
                "publish_time": doc_info.get("PublishTime") or "",
            }
        )
    return {"query": query, "backend": "doubao", "results": results}


def _tavily_search(client: Any, api_key: str, query: str, max_results: int) -> dict[str, Any]:
    try:
        r = client.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": max_results},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"tavily_error: {type(e).__name__}: {e}", "results": []}

    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", "")[:400],
        }
        for item in data.get("results", [])[:max_results]
    ]
    return {"query": query, "backend": "tavily", "results": results}


def _brave_search(client: Any, api_key: str, query: str, max_results: int) -> dict[str, Any]:
    try:
        r = client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"brave_error: {type(e).__name__}: {e}", "results": []}

    web = (data.get("web") or {}).get("results") or []
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": (item.get("description") or "")[:400],
        }
        for item in web[:max_results]
    ]
    return {"query": query, "backend": "brave", "results": results}


def _serper_search(client: Any, api_key: str, query: str, max_results: int) -> dict[str, Any]:
    try:
        r = client.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": max_results},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"serper_error: {type(e).__name__}: {e}", "results": []}

    organic = data.get("organic") or []
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": (item.get("snippet") or "")[:400],
        }
        for item in organic[:max_results]
    ]
    return {"query": query, "backend": "serper", "results": results}


def _searxng_search(client: Any, base_url: str, query: str, max_results: int) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/search"
    headers: dict[str, str] = {"Accept": "application/json"}
    api_key = os.environ.get("SEARXNG_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        r = client.get(
            endpoint,
            params={"q": query, "format": "json"},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": f"searxng_error: {type(e).__name__}: {e}", "results": []}

    items = data.get("results") or []
    results = [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": (item.get("content") or "")[:400],
        }
        for item in items[:max_results]
    ]
    return {"query": query, "backend": "searxng", "results": results}


def _ddg_search(client: Any, query: str, max_results: int) -> dict[str, Any]:
    try:
        r = client.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": "octopus-agent/0.1"},
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"ddg_error: {type(e).__name__}: {e}", "results": []}

    text = r.text
    # DDG HTML: <a class="result__a" href="URL">TITLE</a>
    import re

    items = re.findall(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        text,
        flags=re.DOTALL,
    )
    snippets = re.findall(r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', text, flags=re.DOTALL)

    def _clean(s: str) -> str:
        s = re.sub(r"<[^>]+>", "", s)
        return re.sub(r"\s+", " ", s).strip()

    results: list[dict[str, str]] = []
    for i, (url, title) in enumerate(items[:max_results]):
        snippet = snippets[i] if i < len(snippets) else ""
        results.append(
            {
                "title": _clean(title),
                "url": url,
                "snippet": _clean(snippet)[:400],
            }
        )
    return {"query": query, "backend": "ddg", "results": results}


# ═══════════════════════════════════════════════════════════
# web_fetch — extract just the answer to a prompt via cheap LLM
# ═══════════════════════════════════════════════════════════


_WEB_FETCH_SYSTEM = (
    "You extract specific information from web pages. Return ONLY the answer "
    "to the user's question, no preamble. If the page doesn't contain the "
    "answer, say 'not found in page'."
)


def _strip_html_fallback(html: str) -> str:
    """Regex-based fallback when trafilatura is unavailable.

    Strips <script>/<style> blocks then tags via html.parser, collapsing
    whitespace. Lossy but enough for ad-hoc Q&A.
    """
    import re
    from html.parser import HTMLParser

    cleaned = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self._chunks: list[str] = []

        def handle_data(self, data: str) -> None:
            self._chunks.append(data)

        def text(self) -> str:
            return "".join(self._chunks)

    parser = _Stripper()
    try:  # noqa: SIM105
        parser.feed(cleaned)
    except Exception:  # noqa: BLE001 — malformed HTML; return what we got
        pass
    return re.sub(r"\s+", " ", parser.text()).strip()


def _extract_text_for_prompt(html: str, url: str) -> str:
    """Try trafilatura.extract first, fall back to regex strip."""
    if TRAFILATURA_AVAILABLE and html:
        try:
            text = trafilatura.extract(
                html,
                url=url,
                include_links=False,
                include_comments=False,
                favor_precision=True,
            )
        except (OSError, ValueError):
            text = None
        if text:
            return text
    return _strip_html_fallback(html)


def _web_fetch(
    url: str = "",
    prompt: str = "",
    *,
    max_chars: int = 16000,
    cheap_model: str | None = None,
    client: Any = None,
    allow_private: bool = False,
    timeout_ms: int = 5000,
    llm_timeout_ms: int = 30_000,
    _llm_caller: Any = None,
    _trafilatura_override: Any = "__unset__",
    **_kw: Any,
) -> dict[str, Any]:
    if not prompt:
        question = _kw.get("question")
        if isinstance(question, str) and question.strip():
            prompt = question
    if not url:
        return {"error": "missing url", "error_type": "invalid_argument"}
    if not prompt:
        return {"error": "missing prompt", "error_type": "invalid_argument"}

    # Step 1+2: reuse fetch_url to do GET + SSRF guard.
    fetched = _fetch_url(
        url=url,
        timeout_ms=timeout_ms,
        max_bytes=max(max_chars * 4, 200_000),
        client=client,
        allow_private=allow_private,
        extract=False,
    )
    if "error" in fetched:
        return {
            "error": fetched["error"],
            "error_type": "network_error",
            "url": url,
        }

    raw_html = fetched.get("content", "") or ""
    final_url = fetched.get("url", url)

    # Step 3+4: extract + truncate.
    if _trafilatura_override == "__unset__":
        extracted_text = _extract_text_for_prompt(raw_html, final_url)
    elif _trafilatura_override is None:
        # Test hook: simulate trafilatura import-missing.
        extracted_text = _strip_html_fallback(raw_html)
    else:
        extracted_text = _trafilatura_override

    if len(extracted_text) > max_chars:
        extracted_text = extracted_text[:max_chars]

    if not extracted_text:
        return {
            "error": "empty_extract",
            "error_type": "network_error",
            "url": final_url,
        }

    # Step 5+6: cheap LLM call.
    caller = _llm_caller
    if caller is None:
        try:
            from runtime.platform.llm_infra.llm_caller import LLMCaller

            caller = LLMCaller("web_fetch_cheap", "web_fetch_default_model")
        except Exception as exc:  # noqa: BLE001
            return {
                "error": f"llm_caller_unavailable: {exc}",
                "error_type": "unsupported",
                "url": final_url,
                "fallback_extract": extracted_text,
            }

    user_msg = f"URL: {final_url}\nQuestion: {prompt}\n\nPage content:\n{extracted_text}"
    result_queue: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    caller_context = contextvars.copy_context()

    def _call_llm() -> None:
        try:
            result = caller.call(
                system=_WEB_FETCH_SYSTEM,
                user=user_msg,
                model=cheap_model,
                max_tokens=512,
                temperature=0.1,
            )
        except Exception as exc:  # noqa: BLE001 — returned to the caller thread
            result_queue.put(("error", exc))
        else:
            result_queue.put(("result", result))

    worker = threading.Thread(
        target=lambda: caller_context.run(_call_llm),
        name="web-fetch-llm",
        daemon=True,
    )
    worker.start()
    try:
        kind, payload = result_queue.get(timeout=max(0.001, llm_timeout_ms / 1000))
    except queue.Empty:
        return {
            "error": f"llm_timeout: no response within {llm_timeout_ms}ms",
            "error_type": "llm_timeout",
            "url": final_url,
            "fallback_extract": extracted_text,
        }
    if kind == "error":
        exc = payload
        return {
            "error": f"llm_failed: {type(exc).__name__}: {exc}",
            "error_type": "llm_failed",
            "url": final_url,
            "fallback_extract": extracted_text,
        }
    answer_text, meta = payload

    if not answer_text or (isinstance(meta, dict) and meta.get("error")):
        return {
            "error": (
                f"llm_failed: {meta.get('error', 'empty response')}"
                if isinstance(meta, dict)
                else "llm_failed: empty response"
            ),
            "error_type": "llm_failed",
            "url": final_url,
            "fallback_extract": extracted_text,
        }

    return {
        "ok": True,
        "url": final_url,
        "prompt": prompt,
        "answer": answer_text.strip(),
        "extracted_chars": len(extracted_text),
        "model": (meta or {}).get("model") if isinstance(meta, dict) else None,
    }


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


WEB_SKILL_NAMES = ["fetch_url", "web_search", "web_fetch"]


def register_web_skills(registry: SkillRegistry) -> int:
    if not HTTPX_AVAILABLE:
        return 0

    registry.register(
        Skill(
            name="fetch_url",
            description=(
                "用途: 对一个已知 URL 发 HTTP GET；默认返回原始 body 文本 (有上限)。开 extract=true 走 trafilatura 抽取正文 + 元数据 (title/author/date/sitename/description/language)，把导航/广告/页脚剥掉。\n"
                "何时不用: 不知道目标网址、要先「搜一下」用 web_search；要执行本地命令用 exec_shell (curl/wget 不要绕道这里)；私网地址默认被 SSRF 拦截，需要时显式 allow_private=true。\n"
                "关键参数: url (必填); extract (默认 False, 阅读文章问答时建议 True); timeout_ms (默认 5000); max_bytes (默认 100000)。\n"
                '示例: fetch_url({"url": "https://example.com/post", "extract": true})'
            ),
            affinity=["web", "io"],
            cost_profile="low",
            trusted_source="skill://public/fetch_url",
            handler=_fetch_url,
            tests=[
                SkillTestCase(
                    name="missing_url_returns_error",
                    tier="golden",
                    args={"url": ""},
                    expect=SkillExpect(schema_keys=["error"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="web_search",
            description=(
                "用途: 网上检索 — 任何「需要谷歌一下」的查询 (新闻、价格、定义、X 的现状、近期事件、产品对比) 都走这里；返回结构化 [{title, url, snippet}]。\n"
                "何时不用: 已经知道具体 URL 直接读用 fetch_url；不要用 exec_shell 跑 curl/wget 拿 HTML (没法解析)；查本地代码/配置用 grep_text 或 glob_files。\n"
                "关键参数: query (必填); max_results (默认 5); backend (可选, 留空时按环境变量自动选 doubao/tavily/brave/serper/searxng/ddg)。\n"
                '示例: web_search({"query": "langgraph 0.2 release notes", "max_results": 5})'
            ),
            affinity=["web", "search"],
            cost_profile="low",
            trusted_source="skill://public/web_search",
            handler=_web_search,
            tests=[
                SkillTestCase(
                    name="empty_query_returns_error",
                    tier="golden",
                    args={"query": ""},
                    expect=SkillExpect(schema_keys=["error", "results"]),
                ),
            ],
        )
    )
    registry.register(
        Skill(
            name="web_fetch",
            description=(
                "用途: 给一个 URL + 一个问题，由廉价 LLM 在页面正文里抽出答案；只把 answer 字符串回给主模型，不再让主模型啃 50KB 原始 HTML。\n"
                "何时不用: 只想拿原文 / 自己解析用 fetch_url(extract=true)；不知道目标网址先用 web_search；要本地文件 Q&A 用 read_file 自己问。\n"
                "关键参数: url (必填); prompt (必填, 你想从页面里得到的答案); max_chars (送进 LLM 的正文上限, 默认 16000); cheap_model (可选, 留空走 web_fetch_default_model)。\n"
                '示例: web_fetch({"url": "https://docs.example.com/limits", "prompt": "What is the rate limit?"})'
            ),
            affinity=["web", "io", "llm"],
            cost_profile="mid",
            trusted_source="skill://public/web_fetch",
            handler=_web_fetch,
            tests=[
                SkillTestCase(
                    name="missing_url_returns_error",
                    tier="golden",
                    args={"url": "", "prompt": "what?"},
                    expect=SkillExpect(schema_keys=["error", "error_type"]),
                ),
                SkillTestCase(
                    name="missing_prompt_returns_error",
                    tier="golden",
                    args={"url": "https://example.com/", "prompt": ""},
                    expect=SkillExpect(schema_keys=["error", "error_type"]),
                ),
            ],
        )
    )
    return 3
