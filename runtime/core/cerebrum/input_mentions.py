"""Parse @plugin/@skill/@agent mention tokens from user prompts.

The chat input box's mention autocomplete (frontend/src/components/
workspace/mention-autocomplete.tsx) inserts tokens like::

    @plugin:web-search
    @skill:deep-research
    @agent:researcher_v1

These survive the wire round-trip into ReAct's user goal text. Rather
than relying on the model to pick them up by accident, this module
extracts them up front so the runtime can:

1.  Boost the matching skill / capability into the priority list.
2.  Pre-resolve the agent for delegation tools.
3.  Pre-load the plugin if it's not yet active.

The parser is deliberately permissive: malformed tokens are ignored,
and the original text is preserved for the model so it still sees the
human-readable phrasing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Token shape: @<type>:<id>  where id may contain letters, digits,
# hyphens, underscores, slashes, dots. The trailing boundary is any
# whitespace, punctuation, or end-of-string.
_MENTION_RE = re.compile(
    r"@(?P<type>plugin|skill|agent|pack):(?P<id>[A-Za-z0-9][A-Za-z0-9._/\-]*)",
)

_VALID_TYPES = ("plugin", "skill", "agent", "pack")


@dataclass(frozen=True)
class InputMention:
    """A single @-mention extracted from user input."""

    type: str  # one of "plugin" | "skill" | "agent" | "pack"
    id: str
    raw: str  # the matched token, e.g. "@skill:deep-research"
    span: tuple[int, int]  # (start, end) char offsets in the source text


@dataclass(frozen=True)
class InputMentions:
    """Container holding the mentions found in a single prompt."""

    plugins: tuple[str, ...]
    skills: tuple[str, ...]
    agents: tuple[str, ...]
    packs: tuple[str, ...]
    raw_mentions: tuple[InputMention, ...]

    @property
    def has_any(self) -> bool:
        return bool(
            self.plugins or self.skills or self.agents or self.packs,
        )

    def render_hint(self) -> str:
        """Render a system-prompt fragment describing the mentions.

        The fragment is wrapped in a sentinel tag so the model can
        recognize it as a routing hint, not free-form chat.
        """
        if not self.has_any:
            return ""
        lines: list[str] = ["<input-mentions>"]
        if self.skills:
            lines.append(
                "User pinned these skills via @skill: "
                + ", ".join(f"`{name}`" for name in self.skills)
                + ". Prefer them when they match the next concrete action.",
            )
        if self.packs:
            lines.append(
                "User pinned these skill packs via @pack: "
                + ", ".join(f"`{name}`" for name in self.packs)
                + ". Treat them as a bundle — when the next step needs any "
                "of the pack's contents, prefer that pack as a whole.",
            )
        if self.plugins:
            lines.append(
                "User pinned these plugins via @plugin: "
                + ", ".join(f"`{name}`" for name in self.plugins)
                + ". Use `use_capability` / `query_capability` to invoke them.",
            )
        if self.agents:
            lines.append(
                "User pinned these teammates via @agent: "
                + ", ".join(f"`{name}`" for name in self.agents)
                + ". When delegation is appropriate, route to these "
                "agents via `call_agent` / `call_agent_parallel` first.",
            )
        lines.append(
            "These pins are routing hints, not literal commands — "
            "still confirm the action makes sense before acting.",
        )
        lines.append("</input-mentions>")
        return "\n".join(lines)


def parse_input_mentions(text: str) -> InputMentions:
    """Extract @plugin/@skill/@agent/@pack mentions from a prompt string.

    Duplicates within a single bucket are removed while preserving
    first-seen order. Mentions in code fences or inline code spans are
    NOT excluded — those formatting rules belong to markdown, not user
    intent. If a user pastes ``@skill:foo`` inside backticks they
    probably still want it to count.

    Returns an empty `InputMentions` when no mentions are found.
    """
    if not text:
        return InputMentions((), (), (), (), ())

    raw: list[InputMention] = []
    plugins: list[str] = []
    skills: list[str] = []
    agents: list[str] = []
    packs: list[str] = []
    seen_per_bucket: dict[str, set[str]] = {
        "plugin": set(),
        "skill": set(),
        "agent": set(),
        "pack": set(),
    }

    for match in _MENTION_RE.finditer(text):
        kind = match.group("type")
        ident = match.group("id")
        if kind not in _VALID_TYPES:
            continue
        if not ident or ident in seen_per_bucket[kind]:
            continue
        seen_per_bucket[kind].add(ident)
        raw.append(
            InputMention(
                type=kind,
                id=ident,
                raw=match.group(0),
                span=(match.start(), match.end()),
            ),
        )
        if kind == "plugin":
            plugins.append(ident)
        elif kind == "skill":
            skills.append(ident)
        elif kind == "pack":
            packs.append(ident)
        else:
            agents.append(ident)

    return InputMentions(
        plugins=tuple(plugins),
        skills=tuple(skills),
        agents=tuple(agents),
        packs=tuple(packs),
        raw_mentions=tuple(raw),
    )


__all__ = [
    "InputMention",
    "InputMentions",
    "parse_input_mentions",
]
