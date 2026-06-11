from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandSpec:
    name: str
    handler: Callable[..., int]
    help_text: str = ""
    add_arguments: Callable[[argparse.ArgumentParser], None] | None = None
    aliases: list[str] = field(default_factory=list)


_REGISTRY: dict[str, CommandSpec] = []


def _get_registry() -> list[CommandSpec]:
    global _REGISTRY
    return _REGISTRY


def cli_command(
    name: str,
    *,
    help_text: str = "",
    aliases: list[str] | None = None,
) -> Callable:
    def decorator(fn: Callable[..., int]) -> Callable[..., int]:
        spec = CommandSpec(
            name=name,
            handler=fn,
            help_text=help_text,
            aliases=aliases or [],
        )
        _get_registry().append(spec)
        return fn
    return decorator


def register_all_commands(
    subparsers: argparse._SubParsersAction,
) -> dict[str, CommandSpec]:
    specs = {}
    for spec in _get_registry():
        p = subparsers.add_parser(spec.name, help=spec.help_text, aliases=spec.aliases)
        if spec.add_arguments is not None:
            spec.add_arguments(p)
        specs[spec.name] = spec
        for alias in spec.aliases:
            specs[alias] = spec
    return specs


def dispatch(
    command: str,
    args: argparse.Namespace,
    specs: dict[str, CommandSpec],
    **kwargs: Any,
) -> int:
    spec = specs.get(command)
    if spec is None:
        return 2
    return spec.handler(args, **kwargs)


__all__ = ["cli_command", "register_all_commands", "dispatch", "CommandSpec"]
