"""PluginHub — pluggable module center manager.

Responsibilites
~~~~~~~~~~~~~~~
- Scan ``~/.octopus/plugins/`` for ``plugin.yaml`` manifests
- Load plugins (parse manifest, import Python module, instantiate ModulePlugin)
- Manage lifecycle: load → start → stop → unload
- Automatically mount webhook routes declared in ``plugin.yaml``
- Persist plugin configuration back to ``plugin.yaml``
- Provide query APIs for the frontend management router

Relationship with ``PluginLoader``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``PluginLoader`` (in ``plugin_loader.py``) manages low-level Python
import and lifecycle for ``OctopusPlugin`` instances.  ``PluginHub``
is a higher-level wrapper that adds SkillRegistry / ChannelManager /
FastAPI integration.  ``PluginHub`` is the entry point for the new
pluggable module architecture; ``PluginLoader`` remains for backwards
compatibility with legacy ``OctopusPlugin``-based plugins.
"""

from __future__ import annotations

import importlib
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from runtime.platform.plugins.plugin_base import ModuleContext, ModulePlugin, ProvidedCapability

try:
    from fastapi import Request as _FastAPIRequest  # noqa: F401 – needed for route annotation resolution
except ImportError:
    _FastAPIRequest = None  # type: ignore[assignment,misc]

_LOG = logging.getLogger("octopus.platform.plugin_hub")

# Default plugin directory
_DEFAULT_PLUGIN_DIR = Path.home() / ".octopus" / "plugins"


class PluginHub:
    """Singleton plugin hub — manages plugin discovery, loading, and lifecycle."""

    _instance: PluginHub | None = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> PluginHub:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.stop_all()
                cls._instance.unload_all()
            cls._instance = None

    def __init__(
        self,
        plugin_dir: str | Path | None = None,
        *,
        skill_registry: Any = None,
        channel_manager: Any = None,
        fastapi_app: Any = None,
        event_bus: Any = None,
    ) -> None:
        self._dir = Path(plugin_dir) if plugin_dir else _DEFAULT_PLUGIN_DIR
        self._skill_registry = skill_registry
        self._channel_manager = channel_manager
        self._fastapi_app = fastapi_app
        self._event_bus = event_bus

        # Loaded plugin instances: name -> ModulePlugin
        self._plugins: dict[str, ModulePlugin] = {}
        # Runtime contexts: name -> ModuleContext
        self._contexts: dict[str, ModuleContext] = {}
        # Mounted webhook routers: name -> APIRouter
        self._routers: dict[str, Any] = {}
        # Internal lock for thread safety
        self._lock_internal = threading.RLock()

    # ── Discovery ──────────────────────────────────────────────

    def discover(self) -> list[dict[str, Any]]:
        """Scan the plugin directory and return metadata for all manifests.

        This only reads ``plugin.yaml`` files — it does not load any code.
        """
        results: list[dict[str, Any]] = []
        if not self._dir.exists():
            return results

        for item in sorted(self._dir.iterdir()):
            if not item.is_dir():
                continue
            manifest_data = self._read_manifest_file(item)
            if manifest_data is None:
                continue
            pname = manifest_data.get("name", item.name)
            results.append({
                "id": pname,
                "name": pname,
                "version": manifest_data.get("version", "0.1.0"),
                "description": manifest_data.get("description", ""),
                "author": manifest_data.get("author", ""),
                "tags": manifest_data.get("tags", []),
                "dir": str(item),
                "loaded": pname in self._plugins,
            })
        return results

    # ── Load ───────────────────────────────────────────────────

    def load(self, name: str) -> ModulePlugin | None:
        """Load a single plugin by name.

        1. Parse ``plugin.yaml``
        2. Import ``__init__.py`` and find ``ModulePlugin`` subclass
        3. Instantiate, build ``ModuleContext``, call ``on_load()``
        """
        with self._lock_internal:
            if name in self._plugins:
                return self._plugins[name]

            plugin_dir = self._dir / name
            if not plugin_dir.is_dir():
                _LOG.warning("Plugin directory not found: %s", plugin_dir)
                return None

            # 1. Parse manifest
            manifest_data = self._read_manifest_file(plugin_dir)
            if manifest_data is None:
                _LOG.warning("No plugin.yaml found in %s", plugin_dir)
                return None

            # 2. Import module
            init_file = plugin_dir / "__init__.py"
            if not init_file.exists():
                _LOG.warning("Plugin %s missing __init__.py", name)
                return None

            try:
                if str(self._dir) not in sys.path:
                    sys.path.insert(0, str(self._dir))
                mod = importlib.import_module(name)
            except Exception as exc:
                _LOG.error("Failed to import plugin %s: %s", name, exc)
                return None

            # 3. Find ModulePlugin subclass
            plugin_cls = self._find_plugin_class(mod)
            if plugin_cls is None:
                _LOG.warning(
                    "No ModulePlugin subclass found in %s "
                    "(expected a class inheriting from ModulePlugin)",
                    name,
                )
                return None

            # 4. Build context
            instance = plugin_cls()

            # Merge manifest config with class defaults
            effective_config = dict(manifest_data.get("config", {}))

            # Build PluginManifest from manifest_data
            from runtime.platform.plugins.plugin_loader import PluginManifest

            manifest = PluginManifest(
                name=manifest_data.get("name", name),
                version=manifest_data.get("version", instance.version),
                description=manifest_data.get("description", instance.description),
                author=manifest_data.get("author", instance.author),
                config_schema=manifest_data.get("config_schema", {}),
                subscribes=manifest_data.get("subscribes", []),
                provides=manifest_data.get("provides", []),
            )

            ctx = ModuleContext(
                plugin_name=name,
                plugin_dir=str(plugin_dir),
                manifest=manifest,
                logger=_LOG.getChild(name),
                skill_registry=self._skill_registry,
                channel_manager=self._channel_manager,
                fastapi_app=self._fastapi_app,
                event_bus=self._event_bus,
                config=effective_config,
            )

            # 5. Call on_load (which triggers register_skills/channels/routes)
            try:
                instance.on_load(ctx)
            except Exception as exc:
                _LOG.error("Plugin %s on_load failed: %s", name, exc, exc_info=True)
                return None

            # 6. Auto-mount webhook routes from manifest
            self._mount_webhooks(name, manifest_data, plugin_dir)

            with self._lock_internal:
                self._plugins[name] = instance
                self._contexts[name] = ctx

            _LOG.info(
                "Plugin loaded: %s v%s (%d capabilities)",
                name,
                manifest.version,
                len(instance.capabilities),
            )
            return instance

    def load_all(self) -> list[str]:
        """Discover and load all plugins in the plugin directory."""
        loaded: list[str] = []
        for item in self.discover():
            pname = item["id"]
            if self.load(pname):
                loaded.append(pname)
        return loaded

    def unload(self, name: str) -> bool:
        """Unload a plugin — calls on_unload and removes it."""
        with self._lock_internal:
            instance = self._plugins.pop(name, None)
            ctx = self._contexts.pop(name, None)
            if instance is None:
                return False

            if ctx:
                try:
                    instance.on_unload(ctx)
                except Exception as exc:
                    _LOG.warning("Plugin %s on_unload error: %s", name, exc)

                # Clean up skill/channel registrations so the plugin can be reloaded
                try:
                    ctx.cleanup_registrations()
                except Exception as exc:
                    _LOG.debug("Plugin %s cleanup_registrations error: %s", name, exc)

            # Webhook routers can't be removed from FastAPI at runtime
            router = self._routers.pop(name, None)
            if router:
                _LOG.info("Router for %s would require app restart to fully remove", name)

        _LOG.info("Plugin unloaded: %s", name)
        return True

    def unload_all(self) -> list[str]:
        unloaded: list[str] = []
        for name in list(self._plugins):
            if self.unload(name):
                unloaded.append(name)
        return unloaded

    # ── Start / Stop ───────────────────────────────────────────

    def start(self, name: str) -> bool:
        """Start a loaded plugin (calls on_start)."""
        instance = self._plugins.get(name)
        ctx = self._contexts.get(name)
        if instance is None or ctx is None:
            _LOG.warning("Cannot start plugin %s: not loaded", name)
            return False
        try:
            instance.on_start(ctx)
            _LOG.info("Plugin started: %s", name)
            return True
        except Exception as exc:
            _LOG.error("Plugin %s on_start failed: %s", name, exc, exc_info=True)
            return False

    def start_all(self) -> list[str]:
        started: list[str] = []
        for name in self._plugins:
            if self.start(name):
                started.append(name)
        return started

    def stop(self, name: str) -> bool:
        """Stop a started plugin (calls on_stop)."""
        instance = self._plugins.get(name)
        ctx = self._contexts.get(name)
        if instance is None or ctx is None:
            _LOG.warning("Cannot stop plugin %s: not loaded", name)
            return False
        try:
            instance.on_stop(ctx)
            _LOG.info("Plugin stopped: %s", name)
            return True
        except Exception as exc:
            _LOG.error("Plugin %s on_stop failed: %s", name, exc)
            return False

    def stop_all(self) -> list[str]:
        stopped: list[str] = []
        for name in self._plugins:
            if self.stop(name):
                stopped.append(name)
        return stopped

    # ── Config management ──────────────────────────────────────

    def get_plugin_config(self, name: str) -> dict[str, Any]:
        """Return the current config for a loaded plugin."""
        ctx = self._contexts.get(name)
        if ctx is None:
            return {}
        return dict(ctx.config)

    def update_plugin_config(self, name: str, config: dict[str, Any]) -> bool:
        """Update plugin config and persist to plugin.yaml."""
        ctx = self._contexts.get(name)
        if ctx is None:
            return False
        ctx.config.update(config)

        # Persist to plugin.yaml
        plugin_dir = self._dir / name
        manifest_path = plugin_dir / "plugin.yaml"
        if manifest_path.exists():
            try:
                import yaml

                raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    raw["config"] = ctx.config
                    manifest_path.write_text(
                        yaml.dump(raw, default_flow_style=False, allow_unicode=True),
                        encoding="utf-8",
                    )
            except Exception as exc:
                _LOG.warning("Failed to persist config for %s: %s", name, exc)

        _LOG.info("Config updated for plugin %s", name)
        return True

    # ── Query ──────────────────────────────────────────────────

    def get_plugin(self, name: str) -> ModulePlugin | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """Return metadata for all loaded plugins, including capabilities."""
        result: list[dict[str, Any]] = []
        for pname, instance in self._plugins.items():
            ctx = self._contexts.get(pname)
            caps = []
            for c in instance.capabilities:
                caps.append({"type": c.type, "name": c.name, "description": c.description})
            result.append({
                "id": pname,
                "name": getattr(instance, "name", pname),
                "version": getattr(instance, "version", "0.1.0"),
                "description": getattr(instance, "description", ""),
                "author": getattr(instance, "author", ""),
                "capabilities": caps,
                "config_schema": ctx.manifest.config_schema if ctx else {},
                "config_ui": instance.config_ui_component,
                "loaded": True,
                "enabled": True,
                "error": None,
                "dir": ctx.plugin_dir if ctx else "",
                "dependencies": getattr(instance, "dependencies", []),
                "state": "active",
            })
        return result

    # ── Internal helpers ───────────────────────────────────────

    def _read_manifest_file(self, plugin_dir: Path) -> dict[str, Any] | None:
        """Read plugin.yaml or plugin.json from the plugin directory."""
        for filename in ("plugin.yaml", "plugin.json"):
            path = plugin_dir / filename
            if path.exists():
                try:
                    raw = path.read_text(encoding="utf-8")
                    if filename.endswith(".yaml"):
                        import yaml
                        data = yaml.safe_load(raw)
                    else:
                        data = json.loads(raw)
                    if isinstance(data, dict):
                        return data
                except Exception as exc:
                    _LOG.debug("Failed to parse %s: %s", path, exc)
        return None

    def _find_plugin_class(self, mod: Any) -> type[ModulePlugin] | None:
        """Find a ModulePlugin subclass in the imported module."""
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, ModulePlugin)
                and attr is not ModulePlugin
            ):
                return attr
        return None

    def _mount_webhooks(
        self,
        name: str,
        manifest_data: dict[str, Any],
        plugin_dir: Path,
    ) -> None:
        """Automatically mount webhook routes declared in the manifest."""
        webhooks = manifest_data.get("webhooks", [])
        if not webhooks or self._fastapi_app is None:
            return

        try:
            from fastapi import APIRouter

            route_prefix = f"/api/plugins/webhooks/{name}"
            router = APIRouter(prefix=route_prefix, tags=[f"webhook:{name}"])

            for wh in webhooks:
                path = wh.get("path", "/")
                method = wh.get("method", "POST").lower()
                handler_name = wh.get("handler", "handle_webhook")

                # Use a factory function with default args to capture loop variables
                def _build_webhook_handler(
                    _name: str = name,
                    _handler_name: str = handler_name,
                ):
                    async def _handler(request: _FastAPIRequest):  # type: ignore[valid-type]
                        body = await request.body()
                        headers = dict(request.headers)
                        instance = self._plugins.get(_name)
                        if instance and hasattr(instance, _handler_name):
                            try:
                                result = getattr(instance, _handler_name)(body, headers)
                                import inspect
                                if inspect.iscoroutine(result):
                                    result = await result
                                return result
                            except Exception as exc:
                                _LOG.error(
                                    "Webhook handler %s/%s failed: %s",
                                    _name, _handler_name, exc,
                                )
                                return {"error": str(exc)}
                        return {"error": f"handler {_handler_name} not found"}
                    return _handler

                handler = _build_webhook_handler()

                if method == "post":
                    router.add_api_route(path, handler, methods=["POST"])
                elif method == "get":
                    router.add_api_route(path, handler, methods=["GET"])
                else:
                    router.add_api_route(path, handler, methods=[method.upper()])

                _LOG.info(
                    "Mounted webhook: %s%s [%s] -> %s.%s",
                    route_prefix, path, method.upper(), name, handler_name,
                )

            self._fastapi_app.include_router(router)
            self._routers[name] = router

        except ImportError:
            _LOG.debug("FastAPI not available, skipping webhook mounting")
        except Exception as exc:
            _LOG.warning("Failed to mount webhooks for %s: %s", name, exc)


def get_plugin_hub() -> PluginHub:
    """Get the global PluginHub singleton."""
    return PluginHub.get()


__all__ = [
    "PluginHub",
    "get_plugin_hub",
]
