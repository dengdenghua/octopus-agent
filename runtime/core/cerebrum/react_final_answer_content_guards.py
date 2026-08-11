"""Final-answer content guards (post-step / pre-Final-Answer gates).

Extracted from ``react_guards.py`` (Wave 3, cluster 4) so the orchestration
module can stay under the size budget. These guards inspect the *proposed
final answer itself* — placeholder prose, fabricated citations, and a
requested-but-undelivered output shape — rather than the trajectory.

Leaf-ish module: depends only on re / react_types — must never import
react_guards.
"""

from __future__ import annotations

import re

from runtime.core.cerebrum.react_types import ReActStep


def _incomplete_final_answer_guard(final_answer: str) -> str | None:
    """Reject placeholder/preparatory prose presented as a terminal answer."""

    raw = str(final_answer or "").strip()
    visible = re.sub(r"</?[a-z_][^>]*>", " ", raw, flags=re.IGNORECASE)
    visible = re.sub(r"\s+", " ", visible).strip()
    if not visible:
        return (
            "The proposed Final Answer is empty or only contains an internal "
            "control marker. Produce the actual user-facing result now."
        )
    preparatory_start = re.match(
        r"^(?:我(?:会|将|先|接下来|这就开始|马上开始|开始)|接下来|下一步|准备|"
        r"let me|i(?:'ll| will| first)|next[,：:]?)",
        visible,
        re.IGNORECASE,
    )
    evidence_action = re.search(
        r"\b(?:grep|read|inspect|check|verify|search|open)\b|"
        r"(?:核对|核实|检查|读取|再读|查看|搜索|检索|调研|打开|确认|探清|定位|查找|明确|梳理|审查|评估|开始|过一遍|逐项过)"
        r"(?:[^。.!！；;\n]{0,16})",
        visible,
        re.IGNORECASE,
    )
    result_signal = re.search(
        r"(?:结论|结果|区别|差异|一致|不同|表明|因此|所以|答案)|"
        r"\b(?:result|conclusion|difference|same|therefore|because|answer)\b",
        visible,
        re.IGNORECASE,
    )
    negated_completion = re.search(
        r"(?:还|尚|仍)?(?:没有|未|没能)(?:给出|得到|形成|完成|确认|核对)?"
        r"[^。.!！；;\n]{0,24}(?:结论|结果|答案|比较|差异)|"
        r"\b(?:not\s+yet|no\s+(?:result|conclusion|answer)\s+yet|"
        r"have\s+not\s+(?:finished|completed|verified|checked))\b",
        visible,
        re.IGNORECASE,
    )
    future_action = re.search(
        r"(?:^|[。.!！；;]\s*)(?:我)?(?:会|将|先|接下来|下一步|准备)|"
        r"(?:我)?先[^。.!！；;\n]{0,32}(?:再读|读取|查看|核对|检查|探清|定位|查找|搜索)|"
        r"\b(?:i(?:'ll| will)|let me|next)\b",
        visible,
        re.IGNORECASE,
    )
    failed_attempt = re.search(
        r"(?:失败|路径不对|未找到|找不到|无法读取|没有读到)|"
        r"\b(?:failed|not found|could not read|unable to read)\b",
        visible,
        re.IGNORECASE,
    )
    # A conclusion that is only *promised* (e.g. "用具体数据支撑结论", "再给出
    # 结论") is not a delivered conclusion. result_signal above would otherwise
    # treat the bare word 结论 as a passed check and let a pure preparatory
    # promise through (regression: trn_514bd9600295430b "我这就开始…支撑结论").
    deferred_conclusion = re.search(
        r"(?:支撑|支持|形成|得出|得到|给出|提炼|汇总|归纳|再给)[^。.!！；;\n]{0,12}结论|"
        r"结论(?:前|之前|就|再|待|尚未|还没|暂未)",
        visible,
        re.IGNORECASE,
    )
    if (
        evidence_action
        and (preparatory_start or future_action)
        and (failed_attempt or negated_completion or deferred_conclusion or not result_signal)
    ):
        return (
            "The proposed Final Answer only announces a future inspection or "
            "search. It is not a completed answer. Execute the stated read/search "
            "action, use its observation, and then answer the user's question "
            "with concrete findings."
        )
    return None


# ── Research / chat citation grounding ────────────────────────
# Non-code turns otherwise reach Final Answer with only the security
# cluster gating them. The check that pays off with the fewest false
# positives is a fabricated citation: if the turn actually fetched
# external content and the answer presents a markdown link ``[t](url)``
# whose URL never appeared in any observation, the model is citing a
# source it never consulted — a real, serious research failure.
# Deliberately narrow: only markdown-link citations (not bare URL
# mentions), only when a fetch/search/browser tool actually ran (so there
# is ground truth), and the nudge offers a clean escape (drop the link) so
# a rare false positive can't wedge the loop.
_MD_CITATION_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_FETCH_TOOL_HINTS = (
    "search",
    "fetch",
    "browse",
    "browser",
    "web",
    "retrieve",
    "scrape",
    "wiki",
    "crawl",
)


def _turn_fetched_external_content(steps: list[ReActStep]) -> tuple[bool, str]:
    """Return ``(a fetch/search/browser tool ran, all observation text)``."""
    fetched = False
    blobs: list[str] = []
    for step in steps:
        names = list(step.actions) if step.actions else ([step.action] if step.action else [])
        for res in step.action_results:
            tool = res.get("tool_name")
            if isinstance(tool, str):
                names.append(tool)
            obs = res.get("observation")
            if isinstance(obs, str):
                blobs.append(obs)
        for name in names:
            if any(hint in str(name).lower() for hint in _FETCH_TOOL_HINTS):
                fetched = True
        if step.observation:
            blobs.append(step.observation)
    return fetched, "\n".join(blobs)


def _fabricated_citation_guard(steps: list[ReActStep], final_answer: str) -> str | None:
    """Reject a research/chat final that cites source links it never fetched."""
    cited = _MD_CITATION_RE.findall(final_answer or "")
    if not cited:
        return None
    fetched, observations = _turn_fetched_external_content(steps)
    if not fetched:
        # No research happened this turn — any links are the model's own
        # knowledge, not sources claimed from this turn. Don't police them.
        return None
    seen = observations.lower()
    fabricated = [u for u in cited if u.rstrip("/").lower() not in seen and u.lower() not in seen]
    if not fabricated:
        return None
    return (
        f"Your answer cites {len(fabricated)} source link(s) that never "
        f"appeared in this turn's tool results (e.g. {fabricated[0]}). Do not "
        "present a URL as a source unless you actually fetched it. Either "
        "fetch/verify the link now, cite only URLs that appear in your "
        "search/fetch observations, or drop the link and state the point as "
        "your own reasoning."
    )


# ── External-fact grounding (non-code turns) ────────────────────────────
# The citation guard above catches fabricated *links*; this one catches
# fabricated *numbers*. When a turn actually fetched content, a currency
# amount / percentage / version / dated fact asserted in the answer is
# treated as a claim sourced from that content — if its digits never appear
# in any observation, the claim is ungrounded. Repair-tier (not hard): the
# model can cite the observation it came from or soften to an approximation.
# Deliberately narrow to keep false positives near zero, mirroring the
# citation guard's boundary: fires only on research turns (fetched=True),
# only for external-fact-shaped numbers (never bare integers / single-dot
# decimals), and the numeric core is matched as a substring of the
# observation digit-stream so any overlapping evidence clears it.
#
# The one way a number legitimately misses the observation digit-stream is
# when it is NOT presented as a source echo — the model's own approximation,
# synthesis, or conversion. So a number is skipped when its immediate context
# carries a hedge / own-understanding marker (约 / 据我了解 / approximately /
# i believe) or an aggregation marker (总价 / 合计 / total / sum). This makes
# the guard's advertised escape real (softening actually clears it) and keeps
# honest synthesis / currency conversion out of the false-positive zone —
# a guard that flags its own escape hatch wedges the loop.
_EXTERNAL_FACT_RE = re.compile(
    r"(?:[¥$€£]\s*)\d{1,3}(?:,\d{3})*(?:\.\d+)?"  # currency-prefixed ¥1,200 / $0.80
    r"|\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:元|美元|人民币)"  # currency-suffixed 1,200元
    r"|\d+(?:\.\d+)?\s*%"  # percentage
    r"|\b\d+\.\d+\.\d+(?:[-.]\w+)*\b"  # version N.N.N
    r"|\b(?:19|20)\d{2}[-年]\d{1,2}(?:[-月]\d{1,2}日?)?\b"  # dated fact YYYY-M(-D)
)
_HEDGE_OR_OWN_MARKERS = (
    "约",
    "大约",
    "大概",
    "左右",
    "近",
    "差不多",
    "粗略",
    "估计",
    "可能",
    "据我了解",
    "我判断",
    "我的估计",
    "我推测",
    "我估算",
    "我的了解",
    "我记得",
    "approximately",
    "about",
    "around",
    "roughly",
    "approx",
    "~",
    "i believe",
    "my estimate",
    "best guess",
    "as far as i know",
)
_AGGREGATE_MARKERS = (
    "总计",
    "合计",
    "总价",
    "总额",
    "加总",
    "相加",
    "求和",
    "共计",
    "total",
    "sum",
    "combined",
    "aggregate",
)
_NUMBER_CONTEXT_BEFORE = 18
_NUMBER_CONTEXT_AFTER = 4


def _ungrounded_external_fact_guard(steps: list[ReActStep], final_answer: str) -> str | None:
    """Reject a research/chat final that asserts external facts it never fetched."""
    fetched, observations = _turn_fetched_external_content(steps)
    if not fetched:
        # No research happened this turn — any number is the model's own
        # knowledge or reasoning, not a fact claimed from this turn.
        return None
    obs_digits = re.sub(r"\D", "", observations)
    answer = final_answer or ""
    suppress = _HEDGE_OR_OWN_MARKERS + _AGGREGATE_MARKERS
    ungrounded: list[str] = []
    for match in _EXTERNAL_FACT_RE.finditer(answer):
        fact = match.group(0).strip()
        core = re.sub(r"\D", "", fact)
        if not core or core in obs_digits:
            continue
        window_start = max(0, match.start() - _NUMBER_CONTEXT_BEFORE)
        window_end = match.end() + _NUMBER_CONTEXT_AFTER
        context = answer[window_start:window_end].lower()
        if any(marker in context for marker in suppress):
            # Hedged / own-understanding / synthesized number — the model
            # isn't presenting it as a source echo, so don't police it.
            continue
        ungrounded.append(fact)
    if not ungrounded:
        return None
    shown = ", ".join(dict.fromkeys(ungrounded))
    return (
        f"Your answer asserts external fact(s) — {shown} — that never "
        "appeared in this turn's search/fetch results. Presenting a number "
        "as a sourced fact it wasn't sourced from is fabrication. Either "
        "cite the observation the figure actually came from, or soften to "
        'an approximation / your own understanding (e.g. "约 ¥…" / '
        '"据我了解…" / "approximately …").'
    )


_CHINESE_COUNT_WORDS = {
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _requested_answer_item_count(goal: str) -> int | None:
    text = str(goal or "")
    chinese = re.search(
        r"(?:最后|最终|请|用|给出|总结|归纳|回答)?[^。；;\n]{0,16}"
        r"([二两三四五六七八九十])\s*(?:点|条|项)"
        r"(?:结论|建议|要点|发现|回答|说明)?",
        text,
    )
    if chinese:
        return _CHINESE_COUNT_WORDS.get(chinese.group(1))
    arabic_cn = re.search(
        r"(?:最后|最终|请|用|给出|总结|归纳|回答)?[^。；;\n]{0,16}"
        r"([2-9]|10)\s*(?:点|条|项)"
        r"(?:结论|建议|要点|发现|回答|说明)?",
        text,
    )
    if arabic_cn:
        return int(arabic_cn.group(1))
    english = re.search(
        r"\b(?:give|provide|return|summari[sz]e(?:\s+in)?|with|in)?\s*"
        r"([2-9]|10)\s+(?:points?|findings?|conclusions?|recommendations?|items?)\b",
        text,
        re.IGNORECASE,
    )
    return int(english.group(1)) if english else None


def _answer_item_count(answer: str) -> int:
    text = str(answer or "")
    numbered = re.findall(r"(?m)^\s*(?:\d+|[一二三四五六七八九十])[.)、．]\s+", text)
    bullets = re.findall(r"(?m)^\s*[-*+]\s+\S", text)
    ordinals = re.findall(
        r"(?:^|\n)\s*(?:第[一二三四五六七八九十\d]+[点条项]|"
        r"(?:第一|第二|第三|第四|第五|第六|第七|第八|第九|第十)[：:,，、])",
        text,
    )
    return max(len(numbered), len(bullets), len(ordinals))


def _answer_item_count_guard(goal: str, final_answer: str) -> str | None:
    requested = _requested_answer_item_count(goal)
    if requested is None:
        return None
    delivered = _answer_item_count(final_answer)
    if delivered >= requested:
        return None
    return (
        "The final answer does not satisfy the user's explicit output shape: "
        f"they requested {requested} distinct points, but only {delivered} "
        "recognizable list item(s) were delivered. Rewrite the answer as a "
        f"numbered list with exactly {requested} substantive items grounded in "
        "the available evidence; do not call more tools merely to fix formatting."
    )


__all__ = [
    "_answer_item_count",
    "_answer_item_count_guard",
    "_fabricated_citation_guard",
    "_incomplete_final_answer_guard",
    "_requested_answer_item_count",
    "_turn_fetched_external_content",
]
