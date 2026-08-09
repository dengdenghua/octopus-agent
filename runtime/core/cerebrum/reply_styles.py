"""Reply-style registry: user-facing response decoration is a selectable
dimension, mirroring WorkBuddy's ``style/`` template set (professional /
friendly / socratic / ...). The content here is behaviour guidance injected
into the system prompt as a ``<reply-style>`` section — separate from the
core capability guidance so a style change never touches what the agent can
do, only how it speaks.

The ``default`` style preserves the long-standing Claude-style emoji
decoration exactly (behaviour unchanged for existing turns). Other styles
are opt-in via ``user_context.reply_style``.
"""

from __future__ import annotations

from typing import Final

# Style name -> <reply-style> section body (without the wrapper tags).
_REPLY_STYLES: Final[dict[str, str]] = {
    "default": (
        "回复排版使用轻量 emoji 装饰（Claude 风格，前端支持彩色渲染）：\n"
        "- 完成/成功用 ✅，关键结论/重点用 📌 或 🎯，警告用 ⚠️，修复用 🔧，"
        "数据/统计用 📊，下一步建议用 🚀\n"
        "- 小节标题前可加一个相关 emoji（如 📋 摘要、🛠 实施、✅ 验证）\n"
        "- 列表项可用 emoji 作装饰（如 \"- ✅ 已修复 …\"）\n"
        "- 适度：一段话最多 1-2 个 emoji，不堆砌；代码块、命令输出、路径内不插入 emoji"
    ),
    "professional": (
        "回复风格：专业克制，正式、客观、结构清晰。\n"
        "- 少用 emoji，仅在强调关键状态时用 ✅ / ⚠️\n"
        "- 优先用标题、编号列表、表格呈现结构化信息\n"
        "- 措辞严谨，避免口语化与夸张表达"
    ),
    "friendly": (
        "回复风格：亲和友好，像一位耐心的同事。\n"
        "- 适度使用 😊 ✅ 👍 传递温度，但保持专业\n"
        "- 多用第二人称（你可以…/建议你先…），主动给出下一步\n"
        "- 解释从简单到复杂，避免术语堆砌"
    ),
    "concise": (
        "回复风格：极简直接。\n"
        "- 不寒暄、不铺垫，直接给结论和依据\n"
        "- 每条信息尽量一行以内，用短句\n"
        "- 不重复用户已知内容，聚焦增量信息"
    ),
    "socratic": (
        "回复风格：苏格拉底式引导。\n"
        "- 用提问引导用户思考，而非直接给答案\n"
        "- 先确认用户已掌握的前提，再递进\n"
        "- 关键结论仍要明确给出，不故弄玄虚"
    ),
}

#: Public list of selectable style names (default included).
REPLY_STYLE_NAMES: Final[tuple[str, ...]] = tuple(_REPLY_STYLES.keys())

#: The style used when nothing is configured.
DEFAULT_REPLY_STYLE: Final[str] = "default"


def reply_style_prompt(style: str | None) -> str | None:
    """Return the ``<reply-style>`` section for ``style``, or ``None`` when
    the style is unset/unknown (the assembly layer then injects nothing).

    ``None`` / unknown style falls back to ``default`` so existing turns
    keep the current emoji decoration behaviour.
    """
    body = _REPLY_STYLES.get(style or DEFAULT_REPLY_STYLE)
    if body is None:
        body = _REPLY_STYLES[DEFAULT_REPLY_STYLE]
    return f"\n<reply-style>\n{body}\n</reply-style>"


def is_reply_style(name: str) -> bool:
    """True when ``name`` is a registered style."""
    return name in _REPLY_STYLES
