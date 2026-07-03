"""Token compression for tool observations before they enter the LLM
message stream.

Goal: when a tool produces verbose output (HTML page bodies,
JSON-RPC dumps, long search results), the model only needs the
*meaningful* slice. Trim it on the way INTO messages, leave the
full version intact in step.observation / journal so display +
guards keep their fidelity.

Compression passes (each is a no-op when it doesn't apply). Opt-in
via OCTOPUS_TOKEN_JUICE=1 — default OFF to preserve runtime behavior
until real-traffic validation, not just synthetic-fixture benchmarks:

  1. HTML → Markdown-ish prose (drop tags, keep visible text, keep
     <code>/<pre> ranges intact)
  2. Long URL shortening: URLs > 80 chars become "<domain.com/...>"
  3. Consecutive duplicate-line dedup
  4. Bulky JSON-array trimming (lists > 12 items collapse to first
     5 + last 2 + count marker)
  5. Hard char cap (keeps last N chars after head, since errors
     usually live near the tail)

Sentinel patterns the runtime expects (e.g. `(工具失败)`,
`(real tool execution succeeded)`, `[1/N tool_name]` parallel-batch
headers) are NEVER stripped — the regex set guards them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

# Patterns the loop downstream depends on; never compress past them.
_PROTECTED_RE = re.compile(
    r"(\(工具失败\)|\(工具执行异常\)|\(工具未注册\)|"
    r"\(real tool execution succeeded\)|"
    r"\[\d+/\d+ [^\]]+\]|"
    r"\[自动诊断结果\]|\[关联文件预读\])",
)

_HTML_TAG_RE = re.compile(r"<[^<>]{1,500}>")
_HTML_SCRIPT_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_INDICATOR_RE = re.compile(r"<(html|body|div|p|span|a)\b", re.IGNORECASE)
_LONG_URL_RE = re.compile(r"https?://[^\s\"'<>\)]{80,}")
_DUPLICATE_LINE_RUN_RE = re.compile(r"(.+)(\n\1){3,}")
# Same shape but for JSON-escaped strings (tool outputs that
# embed stdout as a "stdout" field literally write "\n" not a real
# newline — a regex that only sees real \n misses these).
_DUPLICATE_ESCAPED_LINE_RUN_RE = re.compile(r"(.+?)(\\n\1){3,}")


@dataclass(frozen=True)
class JuiceStats:
    """Before/after char counts for a single compression pass.

    The runtime logs these so we can quantify token savings on real
    workloads. Tokens ≈ chars / 4 for English, ≈ chars / 1.7 for
    CJK — both directions improve when chars drop.
    """

    before: int
    after: int
    passes: tuple[str, ...]

    @property
    def saved(self) -> int:
        return self.before - self.after

    @property
    def ratio(self) -> float:
        if self.before <= 0:
            return 1.0
        return self.after / self.before


def _strip_html(text: str) -> str:
    """Drop HTML tags but keep visible text. Preserves code/pre."""
    if not _HTML_INDICATOR_RE.search(text):
        return text
    # First nuke <script>/<style> blocks — their bodies are noise.
    cleaned = _HTML_SCRIPT_RE.sub(" ", text)
    # Strip remaining tags. _HTML_TAG_RE caps tag length at 500
    # chars so a malformed tag can't eat the whole string.
    cleaned = _HTML_TAG_RE.sub(" ", cleaned)
    # Decode the most common entities.
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    # Collapse the whitespace explosion HTML stripping leaves behind.
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _shorten_long_urls(text: str) -> str:
    """https://very.long/.../...?a=…&b=… → <very.long/...>"""

    def _replace(m: re.Match[str]) -> str:
        url = m.group(0)
        m2 = re.match(r"https?://([^/]+)/?(.{0,12})", url)
        if not m2:
            return url
        host = m2.group(1)
        head = m2.group(2)
        return f"<{host}/{head}…>" if head else f"<{host}/…>"

    return _LONG_URL_RE.sub(_replace, text)


def _dedup_repeated_lines(text: str) -> str:
    """Collapse runs of 4+ IDENTICAL lines into "<line> ×N".

    Two shapes, both lossless (the collapsed lines are byte-for-byte
    equal to the survivor):
      1. Real newlines (most common — direct stdout)
      2. JSON-escaped \\n (when stdout is wrapped in a JSON field)

    Note: an earlier "similar-prefix run" collapse was removed. Lines
    sharing a prefix (`src/a.py: …`, `src/b.py: …`) are NOT redundant —
    each grep hit is distinct data the model may need, and there's no
    syntactic signal separating "redundant repetition" from "a list of
    distinct results that happen to share a prefix". Only exact
    duplicates can be dropped without guessing.
    """

    def _replace_run(m: re.Match[str]) -> str:
        line = m.group(1)
        # Count line separators (either real \n or escaped \\n).
        sep_count = max(
            m.group(0).count("\n"),
            m.group(0).count("\\n"),
        )
        n = sep_count + 1
        return f"{line}\n  …(× {n} times)"

    out = _DUPLICATE_LINE_RUN_RE.sub(_replace_run, text)
    out = _DUPLICATE_ESCAPED_LINE_RUN_RE.sub(_replace_run, out)
    return out  # noqa: RET504 — keep `out` named for readability


_JSON_ARRAY_RE = re.compile(r"\[(\s*\{.*?\}\s*,?\s*){13,}\]", re.DOTALL)


def _trim_oversized_arrays(text: str) -> str:
    """When JSON output contains a long list of objects, keep first 5
    and last 2 — model rarely needs item #8 of 50."""

    def _replace(m: re.Match[str]) -> str:
        body = m.group(0)
        # Cheap object-boundary split; not a full JSON parser, but
        # tool outputs are usually well-formed.
        items = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", body)
        if len(items) <= 12:
            return body
        head = ", ".join(items[:5])
        tail = ", ".join(items[-2:])
        return f"[{head}, … ({len(items) - 7} more items omitted) …, {tail}]"

    return _JSON_ARRAY_RE.sub(_replace, text)


def _hard_cap(text: str, max_chars: int) -> str:
    """Keep head + tail when over budget. Errors and final results
    usually live in the tail; the head shows what tool ran. Middle
    is most often boilerplate."""
    if len(text) <= max_chars:
        return text
    head_n = max_chars * 2 // 3
    tail_n = max_chars - head_n - 32  # 32 chars for the marker
    head = text[:head_n]
    tail = text[-tail_n:] if tail_n > 0 else ""
    return f"{head}\n\n…(已压缩中段 {len(text) - head_n - tail_n} 字符)…\n\n{tail}"


def juice(
    text: str,
    *,
    max_chars: int = 6000,
    enable_html: bool = True,
    enable_url: bool = True,
    enable_dedup: bool = True,
    enable_array: bool = True,
    enable_cap: bool = True,
) -> tuple[str, JuiceStats]:
    """Apply the compression pipeline. Returns (compressed_text, stats).

    The protected-pattern guard runs *before* compression and is
    re-asserted after: if any sentinel disappeared we revert to the
    pre-compression text for that span. Cheaper than tracking spans
    surgically and is the right safety default — when in doubt,
    don't strip.
    """
    if not text:
        return text, JuiceStats(0, 0, ())
    before = len(text)
    passes: list[str] = []

    # Snapshot the protected substrings so we can verify nothing
    # got eaten. This is a correctness check, not a recovery step —
    # a juicer that ate `(工具失败)` would silently teach the model
    # the wrong thing about retry semantics.
    protected_snapshot = _PROTECTED_RE.findall(text)

    out = text
    if enable_html:
        new = _strip_html(out)
        if new != out:
            passes.append("html")
            out = new
    if enable_url:
        new = _shorten_long_urls(out)
        if new != out:
            passes.append("url")
            out = new
    if enable_array:
        new = _trim_oversized_arrays(out)
        if new != out:
            passes.append("array")
            out = new
    if enable_dedup:
        new = _dedup_repeated_lines(out)
        if new != out:
            passes.append("dedup")
            out = new
    if enable_cap and len(out) > max_chars:
        new = _hard_cap(out, max_chars)
        if new != out:
            passes.append("cap")
            out = new

    # Re-verify protected sentinels. If any were lost (most likely
    # by the hard cap eating the tail), restore the original — we'd
    # rather pay tokens than mislead the loop.
    if protected_snapshot:
        post_snapshot = _PROTECTED_RE.findall(out)
        if len(post_snapshot) < len(protected_snapshot):
            return text, JuiceStats(before, before, ())

    return out, JuiceStats(
        before=before,
        after=len(out),
        passes=tuple(passes),
    )


def is_enabled() -> bool:
    """Feature flag. Default OFF — compression changes what the model
    sees, which is a runtime-behavior change. The sentinel guard only
    fires when a protected pattern is present in the source text, so
    the common high-compression path (a successful fetch/grep with no
    `(工具失败)` / `[1/N]` markers) is unguarded. Until compression is
    validated on real traffic (not just synthetic fixtures), it stays
    opt-in.

    Opt in by setting OCTOPUS_TOKEN_JUICE to "1", "true", "yes", or
    "on". Any other value (including unset) keeps raw observations."""
    raw = os.environ.get("OCTOPUS_TOKEN_JUICE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}
