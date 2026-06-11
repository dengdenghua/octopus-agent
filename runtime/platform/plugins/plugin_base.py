"""Plugin base classes for the pluggable module (PluginHub) architecture.

A plugin is a directory under ``~/.octopus/plugins/<name>/`` with a
``plugin.yaml`` manifest and a ``ModulePlugin`` subclass in ``__init__.py``.

Three progressive registration layers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Layer 1 (minimal)
    Register skill(s) via ``register_skills()`` → ``SkillRegistry``.
    Suitable for pure tool/utility plugins.

Layer 2 (standard)
    Layer 1 + register channel(s) via ``register_channels()`` → ``ChannelManager``.
    Suitable for business plugins with message channels.

Layer 3 (complete)
    Layer 2 + register API routes via ``register_routes()`` → FastAPI app
    + optional frontend config UI component (``config_ui_component``).
    Suitable for plugins with their own management panel.

Naming convention
~~~~~~~~~~~~~~~~~
- Skill name: ``<plugin_name>.<skill_name>`` (e.g. ``openproject.list_projects``)
- Channel ID: ``<plugin_name>_<channel_name>`` (e.g. ``openproject_notifications``)
- API route: ``/api/plugins/<plugin_name>/...``
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any

# ── Capability declaration ─────────────────────────────────────


@dataclass
class ProvidedCapability:
    """A capability the plugin provides, shown on the frontend plugin page."""

    type: str  # "skill" | "channel" | "api" | "config_ui"
    name: str
    description: str = ""


# ── Plugin runtime context ─────────────────────────────────────


@dataclass
class ModuleContext:
    """Runtime context injected into a plugin when it is loaded.

    Provides access to external services (SkillRegistry, ChannelManager,
    FastAPI app, event bus) and the plugin's own persisted config.
    """

    plugin_name: str
    plugin_dir: str
    manifest: Any  # PluginManifest from plugin_loader
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger(__name__))

    # Injected external services (set by PluginHub before on_load)
    skill_registry: Any = None       # runtime.execution.suckers.registry.SkillRegistry
    channel_manager: Any = None      # runtime.adapters.channels.manager.ChannelManager
    fastapi_app: Any = None          # FastAPI application
    event_bus: Any = None            # runtime.platform.process.eventbus.EventBus

    # Plugin's own persisted config (from plugin.yaml ``config`` field)
    config: dict[str, Any] = field(default_factory=dict)

    # Tracking for cleanup on unload
    _registered_skill_names: list[str] = field(default_factory=list)
    _registered_channel_ids: list[str] = field(default_factory=list)

    def register_skill(self, skill: Any) -> None:
        """Register a Skill with the SkillRegistry."""
        if self.skill_registry is not None:
            self.skill_registry.register(skill, verify_tests=False)
            self._registered_skill_names.append(skill.name)

    def register_channel(self, channel: Any) -> None:
        """Register a Channel with the ChannelManager."""
        if self.channel_manager is not None:
            self.channel_manager.register(channel)
            self._registered_channel_ids.append(channel.channel_id)

    def cleanup_registrations(self) -> None:
        """Unregister all skills and channels registered via this context."""
        if self.skill_registry is not None:
            for skill_name in self._registered_skill_names:
                try:
                    self.skill_registry.unregister(skill_name)
                except Exception:  # noqa: BLE001 — best-effort plugin teardown; one bad skill shouldn't block the rest
                    pass
            self._registered_skill_names.clear()

        if self.channel_manager is not None:
            for ch_id in self._registered_channel_ids:
                try:
                    self.channel_manager._channels.pop(ch_id, None)
                except Exception:  # noqa: BLE001 — best-effort channel removal during teardown
                    pass
            self._registered_channel_ids.clear()


# ── Plugin base class ──────────────────────────────────────────


class ModulePlugin(ABC):
    """Base class for a pluggable module plugin.

    Subclasses **must** provide ``name`` and override ``register_skills()``.
    Optionally override ``register_channels()``, ``register_routes()``,
    ``on_load()``, ``on_start()``, ``on_stop()``, ``on_unload()``,
    and set ``config_ui_component``.

    Lifecycle (driven by PluginHub)::

        on_load(ctx)   → register_skills / register_channels / register_routes
        on_start(ctx)  → start background tasks, open connections
        on_stop(ctx)   → stop background tasks, close connections
        on_unload(ctx) → cleanup
    """

    # ── Metadata (class-level defaults, overridden by plugin.yaml) ──
    name: str = "unnamed-module"
    version: str = "0.1.0"
    description: str = ""
    author: str = ""

    def __init__(self) -> None:
        self.ctx: ModuleContext | None = None

    # ── Lifecycle hooks ─────────────────────────────────────────

    def on_load(self, ctx: ModuleContext) -> None:
        """Called after the plugin is loaded and context is injected.

        The default implementation calls ``register_skills()``,
        ``register_channels()``, and ``register_routes()``.
        Override to customise the registration order or add logic.
        """
        self.ctx = ctx
        self.register_skills()
        self.register_channels()
        self.register_routes()

    def on_start(self, ctx: ModuleContext) -> None:
        """Called when the plugin is started (after all loading).

        Suitable for establishing connections, starting background tasks.
        """

    def on_stop(self, ctx: ModuleContext) -> None:
        """Called when the plugin is stopped.

        Suitable for closing connections, stopping background tasks.
        """

    def on_unload(self, ctx: ModuleContext) -> None:
        """Called when the plugin is unloaded.

        Suitable for final cleanup.
        """

    # ── Registration hooks (subclasses override) ────────────────

    def register_skills(self) -> None:
        """Register the skills this plugin provides.

        Use ``self.ctx.register_skill(skill)`` to register each skill.
        Skill names should follow the ``<plugin_name>.<name>`` convention.
        """

    def register_channels(self) -> None:
        """Register the channels this plugin provides.

        Use ``self.ctx.register_channel(channel)`` to register each channel.
        Channel IDs should follow the ``<plugin_name>_<name>`` convention.
        """

    def register_routes(self) -> None:
        """Register FastAPI routes for this plugin.

        Access the FastAPI app via ``self.ctx.fastapi_app``.
        Routes should be mounted under ``/api/plugins/<plugin_name>/...``.
        """

    # ── Frontend configuration UI ───────────────────────────────

    @property
    def config_ui_component(self) -> str | None:
        """Return the relative path to a frontend config UI component.

        The path is relative to the plugin directory.
        Return ``None`` to let the frontend render a generic schema-based form.
        """
        return None

    # ── Introspection ───────────────────────────────────────────

    @property
    def capabilities(self) -> list[ProvidedCapability]:
        """Auto-detect which capabilities this plugin provides."""
        caps: list[ProvidedCapability] = []
        if self.__class__.register_skills is not ModulePlugin.register_skills:
            caps.append(ProvidedCapability(
                type="skill",
                name=f"{self.name}.skills",
                description="Registered skills",
            ))
        if self.__class__.register_channels is not ModulePlugin.register_channels:
            caps.append(ProvidedCapability(
                type="channel",
                name=f"{self.name}.channel",
                description="Registered channels",
            ))
        if self.__class__.register_routes is not ModulePlugin.register_routes:
            caps.append(ProvidedCapability(
                type="api",
                name=f"{self.name}.api",
                description="Custom API routes",
            ))
        if self.config_ui_component is not None:
            caps.append(ProvidedCapability(
                type="config_ui",
                name=f"{self.name}.config_ui",
                description="Custom configuration UI",
            ))
        return caps


__all__ = [
    "ModuleContext",
    "ModulePlugin",
    "ProvidedCapability",
]
