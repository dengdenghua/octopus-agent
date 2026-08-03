"""Final ``messages`` composition for the PHASE 3 assembly.

Leaf of the prompt-assembly split. Takes the assembled system + volatile
parts and composes the initial ``messages`` list (system prefix + volatile
user message + conversation history + profile memories + startup code context
+ the user's request + live-steering protocol). Never imports ``react_loop``.
"""

from __future__ import annotations

from runtime.core.cerebrum._react_prompt_assembly_state import _AssemblyState
from runtime.core.cerebrum.react_context import (
    _build_code_context_prelude,
    _build_user_message_content,
)
from runtime.core.cerebrum.stable_prompt import render_volatile_as_user_message
from runtime.platform.models.llm import Message


def _assemble_messages(state: _AssemblyState) -> None:
    """Compose the initial ``messages`` list from the assembled parts."""
    _volatile_text = "\n\n".join(state.volatile_parts).strip() if state.volatile_parts else ""
    messages: list[Message] = [
        Message(role="system", content="\n\n".join(state.system_parts)),
    ]
    if _volatile_text:
        messages.append(
            Message(
                role="user",
                content=render_volatile_as_user_message(_volatile_text),
            ),
        )
    _uc = state.user_context
    conv_history = _uc.get("conversation_messages")
    if isinstance(conv_history, list) and conv_history:
        profile_mems = _uc.get("profile_memories")
        if isinstance(profile_mems, list) and profile_mems:
            try:
                from runtime.memory.users.profile import render_profile_memories

                mem_block = render_profile_memories(profile_mems)
            except (ImportError, AttributeError, TypeError):
                mem_block = ""
            if mem_block:
                messages.append(Message(role="system", content=mem_block))
        for item in conv_history[:-1]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant", "system"):
                continue
            if (
                isinstance(content, str)
                and content.strip()
                or isinstance(content, list)
                and content
            ):
                messages.append(Message(role=role, content=content))
    _no_startup_code_context_modes = {
        "chat",
        "conversation",
        "inspiration",
        "brainstorm",
        "discuss",
    }
    _startup_code_context_allowed = (
        state.is_code_mode
        and state.mode_value not in _no_startup_code_context_modes
        and state.capability_mode_value not in _no_startup_code_context_modes
    )
    if (
        _startup_code_context_allowed
        and isinstance(state.effective_wp, str)
        and state.effective_wp.strip()
        and state.resume_task_id is None
    ):
        startup_context = _build_code_context_prelude(
            state.effective_wp.strip(),
            str(state.intent.normalized_goal or state.intent.raw or ""),
        )
        if startup_context:
            messages.append(Message(role="user", content=startup_context))
    messages.append(
        Message(
            role="user",
            content=_build_user_message_content(
                state.intent.normalized_goal,
                state.user_context.get("attachments", []),
            ),
        ),
    )
    if state.user_context.get("live_steering"):
        from runtime.core.cerebrum.live_steering import (
            insert_live_steering_protocol,
        )

        insert_live_steering_protocol(messages)
    state.messages = messages
