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

from runtime.platform.plugins.plugin_base import ModuleContext, ModulePlugin

try:
    from fastapi import (
        Request as _FastAPIRequest,  # noqa: F401 – needed for route annotation resolution
        WebSocket as _FastAPIWebSocket,  # noqa: F401 – websocket route annotation
    )
    from starlette.websockets import (
        WebSocketDisconnect as _FastAPIWebSocketDisconnect,  # noqa: F401
    )
except ImportError:
    _FastAPIRequest = None  # type: ignore[assignment,misc]
    _FastAPIWebSocket = None  # type: ignore[assignment,misc]
    _FastAPIWebSocketDisconnect = None  # type: ignore[assignment,misc]

_LOG = logging.getLogger("octopus.platform.plugin_hub")

# Default plugin directory
_DEFAULT_PLUGIN_DIR = Path.home() / ".octopus" / "plugins"
_DEFAULT_BUNDLED_PLUGIN_DIR = Path(__file__).resolve().parent / "bundled"


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
        bundled_plugin_dir: str | Path | None = None,
        skill_registry: Any = None,
        channel_manager: Any = None,
        fastapi_app: Any = None,
        event_bus: Any = None,
        service_bus: Any = None,
    ) -> None:
        """Create the hub.

        ``service_bus`` (a :class:`~runtime.platform.process.service_bus.ServiceBus`)
        is the composition-layer socket. When provided, ``load_all`` resolves a
        topological load order from each plugin's ``provides``/``consumes`` and
        every loaded plugin's provided services become queryable through the
        bus. When omitted (the default), the hub keeps today's behaviour
        exactly — existing plugins are unaffected.
        """
        self._dir = Path(plugin_dir) if plugin_dir else _DEFAULT_PLUGIN_DIR
        self._bundled_dir = (
            Path(bundled_plugin_dir)
            if bundled_plugin_dir is not None
            else (_DEFAULT_BUNDLED_PLUGIN_DIR if plugin_dir is None else None)
        )
        self._skill_registry = skill_registry
        self._channel_manager = channel_manager
        self._fastapi_app = fastapi_app
        self._event_bus = event_bus
        self._service_bus = service_bus

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
        seen: set[str] = set()
        for base, bundled in self._plugin_roots():
            if not base.exists():
                continue
            for item in sorted(base.iterdir()):
                if not item.is_dir():
                    continue
                manifest_data = self._read_manifest_file(item)
                if manifest_data is None:
                    continue
                pname = manifest_data.get("name", item.name)
                if pname in seen:
                    continue
                seen.add(pname)
                # ``display_name``(可选,中文/本地化名)折进 ``name`` 供前端展示;
                # ``id`` 永远是 ASCII 模块名(import 与生命周期 API 用它)。
                display = str(manifest_data.get("display_name") or "").strip()
                results.append(
                    {
                        "id": pname,
                        "name": display or pname,
                        "display_name": display,
                        "version": manifest_data.get("version", "0.1.0"),
                        "description": manifest_data.get("description", ""),
                        "author": manifest_data.get("author", ""),
                        "tags": manifest_data.get("tags", []),
                        "dir": str(item),
                        "bundled": bundled,
                        "loaded": pname in self._plugins,
                    }
                )
        return results

    # ── Load ───────────────────────────────────────────────────

    def load(self, name: str) -> ModulePlugin | None:
        """Load a single plugin by name.

        1. Parse ``plugin.yaml``
        2. Import ``__init__.py`` and find ``ModulePlugin`` subclass
        3. Instantiate, build ``ModuleContext``, call ``on_load()``
        """
        with self._lock_internal:
            # PluginHub imports arbitrary third-party Python into the API
            # process and gives it SkillRegistry, ChannelManager, FastAPI and
            # EventBus handles.  There is no worker boundary today, so a
            # shared/commercial deployment must fail closed instead of
            # treating operator-only lifecycle routes as process isolation.
            from runtime.safety.sandboxing.sandbox import commercial_execution_mode

            if commercial_execution_mode():
                _LOG.error(
                    "Plugin %s rejected: in-process plugin loading is disabled "
                    "in shared/commercial mode until an isolated worker runtime "
                    "is configured",
                    name,
                )
                return None

            if name in self._plugins:
                return self._plugins[name]

            plugin_dir = self._resolve_plugin_dir(name)
            if plugin_dir is None:
                _LOG.warning("Plugin directory not found: %s", name)
                return None
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
                import_root = str(plugin_dir.parent)
                if import_root not in sys.path:
                    sys.path.insert(0, import_root)
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
                # Composition layer: a plugin may declare the services it
                # consumes. ``consumes`` is the canonical new key; legacy
                # ``requires`` is accepted for compatibility.
                requires=manifest_data.get("consumes", manifest_data.get("requires", [])),
            )

            # Composition layer pre-check: a block whose consumes are not yet
            # satisfiable is blocked (warn + skip), never fatal. Mirrors the
            # "degrade, don't crash" contract of extensions.py.
            if self._service_bus is not None:
                from runtime.platform.process.block_manifest import BlockManifest

                block_manifest = BlockManifest.from_plugin_manifest(manifest)
                ok, missing = self._service_bus.can_bind(block_manifest)
                if not ok:
                    _LOG.warning(
                        "Plugin %s blocked: missing services %s (declared consumes)",
                        name,
                        sorted(missing),
                    )
                    return None

            ctx = ModuleContext(
                plugin_name=name,
                plugin_dir=str(plugin_dir),
                manifest=manifest,
                logger=_LOG.getChild(name),
                skill_registry=self._skill_registry,
                channel_manager=self._channel_manager,
                fastapi_app=self._fastapi_app,
                event_bus=self._event_bus,
                service_bus=self._service_bus,
                config=effective_config,
            )

            # 5. Call on_load (which triggers register_skills/channels/routes)
            try:
                instance.on_load(ctx)
            except Exception as exc:
                _LOG.error("Plugin %s on_load failed: %s", name, exc, exc_info=True)
                return None

            # 5.5 Composition layer: bind the plugin's provided services so
            # later consumers can resolve them through the ServiceBus.
            if self._service_bus is not None:
                for service in block_manifest.provides:
                    self._service_bus.register(service, name, instance=instance)

            # 6. Auto-mount webhook routes from manifest
            self._mount_webhooks(name, manifest_data, plugin_dir)

            # 7. Diagnostic: warn if manifest.provides diverges from the
            # capabilities the code actually registered (auto-detected
            # capabilities remain the source of truth — this only surfaces
            # drift at load time instead of letting it pass silently).
            self._validate_manifest_provides(name, instance, manifest)

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

    @staticmethod
    def _validate_manifest_provides(
        name: str,
        instance: Any,
        manifest: Any,
    ) -> None:
        """Warn when ``manifest.provides`` doesn't match the instance's actual
        registered capabilities. An empty ``provides`` is fine (auto-detection
        is the design intent) and is skipped."""
        declared = {str(p) for p in (getattr(manifest, "provides", None) or [])}
        if not declared:
            return
        actual = {
            str(getattr(c, "name", c)) for c in (getattr(instance, "capabilities", None) or [])
        }
        missing = declared - actual
        extra = actual - declared
        if missing or extra:
            parts = []
            if missing:
                parts.append(f"declared but not provided: {sorted(missing)}")
            if extra:
                parts.append(f"provided but not declared: {sorted(extra)}")
            _LOG.warning(
                "Plugin %s manifest.provides mismatch — %s",
                name,
                "; ".join(parts),
            )

    def load_all(self) -> list[str]:
        """Discover and load all plugins in the plugin directory.

        With a ServiceBus injected, load order follows each plugin's declared
        ``provides``/``consumes`` (topological); plugins whose dependencies are
        missing are logged as blocked and skipped, and a dependency cycle is a
        logged error — neither crashes the hub. Without a ServiceBus this is
        exactly the legacy discovery-order load.
        """
        if self._service_bus is None:
            loaded: list[str] = []
            for item in self.discover():
                pname = item["id"]
                if self.load(pname):
                    loaded.append(pname)
            return loaded

        from runtime.platform.plugins.plugin_loader import PluginManifest
        from runtime.platform.process.block_manifest import BlockManifest
        from runtime.platform.process.service_bus import (
            BlockDependencyCycleError,
            resolve_load_order,
        )

        discovered = self.discover()
        manifests: list[BlockManifest] = []
        for item in discovered:
            manifest_data = self._read_manifest_file(Path(item["dir"]))
            if not manifest_data:
                continue
            pm = PluginManifest(
                name=manifest_data.get("name", item["id"]),
                version=manifest_data.get("version", "0.1.0"),
                description=manifest_data.get("description", ""),
                author=manifest_data.get("author", ""),
                config_schema=manifest_data.get("config_schema", {}),
                subscribes=manifest_data.get("subscribes", []),
                provides=manifest_data.get("provides", []),
                requires=manifest_data.get("consumes", manifest_data.get("requires", [])),
            )
            try:
                manifests.append(
                    BlockManifest.from_plugin_manifest(pm, kind=manifest_data.get("kind"))
                )
            except ValueError as exc:
                _LOG.warning("Plugin %s skipped (invalid manifest): %s", item["id"], exc)

        try:
            ordered, blocked = resolve_load_order(
                manifests,
                available_services=self._service_bus.provided_services(),
            )
        except BlockDependencyCycleError as exc:
            _LOG.error("Plugin dependency cycle — skipping affected plugins: %s", exc)
            return []

        for manifest in blocked:
            missing = sorted(set(manifest.consumes))
            _LOG.warning(
                "Plugin %s blocked: missing services %s (declared consumes)",
                manifest.name,
                missing,
            )

        # Load in topological order, not discovery order: a consumer must
        # load only after every service it consumes is bound.
        loaded = []
        for manifest in ordered:
            if self.load(manifest.name):
                loaded.append(manifest.name)
        return loaded

    def unload(self, name: str) -> bool:
        """Unload a plugin — calls on_unload and removes it."""
        with self._lock_internal:
            instance = self._plugins.pop(name, None)
            ctx = self._contexts.pop(name, None)
            if instance is None:
                return False

            # Composition layer: remove every service this block provided,
            # so a reload binds them fresh and no consumer keeps a stale ref.
            if self._service_bus is not None:
                try:
                    self._service_bus.unbind(name)
                except Exception as exc:  # noqa: BLE001 — teardown is best-effort
                    _LOG.debug("Plugin %s service unbind error: %s", name, exc)

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
        from runtime.safety.sandboxing.sandbox import commercial_execution_mode

        if commercial_execution_mode():
            _LOG.error(
                "Plugin %s rejected: in-process plugin start is disabled in shared/commercial mode",
                name,
            )
            return False
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
        if self._bundled_dir is not None:
            try:
                Path(ctx.plugin_dir).relative_to(self._bundled_dir)
            except ValueError:  # noqa: BLE001 — expected when plugin is outside bundled directory
                pass
            else:
                _LOG.warning("Bundled plugin config is read-only: %s", name)
                return False
        ctx.config.update(config)

        # Persist to plugin.yaml
        plugin_dir = Path(ctx.plugin_dir)
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
            result.append(
                {
                    "id": pname,
                    "name": (
                        getattr(instance, "display_name", "") or getattr(instance, "name", pname)
                    ),
                    "display_name": getattr(instance, "display_name", "") or "",
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
                }
            )
        return result

    # ── Internal helpers ───────────────────────────────────────

    def _plugin_roots(self) -> list[tuple[Path, bool]]:
        roots: list[tuple[Path, bool]] = []
        if self._bundled_dir is not None:
            roots.append((self._bundled_dir, True))
        roots.append((self._dir, False))
        return roots

    def _resolve_plugin_dir(self, name: str) -> Path | None:
        for item in self.discover():
            if item["id"] == name:
                return Path(item["dir"])
        return None

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
        """Automatically mount routes declared in the manifest.

        ``webhooks`` items mount HTTP routes (path/method/handler); each
        handler receives ``(body: bytes, headers: dict)`` and may return a
        sync value or a coroutine. ``websockets`` items mount WebSocket
        routes (path/handler) for realtime streams — voice, co-editing,
        shared terminals. The websocket handler is a plugin coroutine
        receiving the ``WebSocket``; it owns accept/close (the hub closes
        with 4404 when the handler is missing, 1011 on handler error).
        """
        if self._fastapi_app is None:
            return

        webhooks = manifest_data.get("webhooks", [])
        websockets = manifest_data.get("websockets", [])
        if not webhooks and not websockets:
            return

        try:
            from fastapi import APIRouter

            route_prefix = f"/api/plugins/webhooks/{name}"
            router = APIRouter(prefix=route_prefix, tags=[f"webhook:{name}"])

            for wh in webhooks or []:
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
                                    _name,
                                    _handler_name,
                                    exc,
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
                    route_prefix,
                    path,
                    method.upper(),
                    name,
                    handler_name,
                )

            # WebSocket routes: realtime streams (voice / co-editing / …).
            # Manifest shape: ``websockets: [{path: "/ws/voice", handler: "…"}]``.
            for ws_item in websockets or []:
                path = str(ws_item.get("path", "/"))
                handler_name = ws_item.get("handler", "handle_websocket")

                def _build_ws_handler(
                    _name: str = name,
                    _handler_name: str = handler_name,
                ):
                    async def _handler(websocket: _FastAPIWebSocket):  # type: ignore[valid-type]
                        instance = self._plugins.get(_name)
                        if instance is None or not hasattr(instance, _handler_name):
                            await websocket.close(code=4404)
                            return
                        try:
                            fn = getattr(instance, _handler_name)
                            result = fn(websocket)
                            import inspect

                            if inspect.iscoroutine(result):
                                await result
                        except _FastAPIWebSocketDisconnect:
                            # Client disconnected — normal WebSocket teardown,
                            # not a handler failure. Propagate so the ASGI
                            # framework finalizes the connection cleanly.
                            raise
                        except Exception as exc:  # noqa: BLE001 — surface, never crash
                            _LOG.error(
                                "WebSocket handler %s/%s failed: %s",
                                _name,
                                _handler_name,
                                exc,
                            )
                            try:
                                await websocket.close(code=1011)
                            except Exception:  # noqa: BLE001 — close is best-effort
                                pass

                    return _handler

                router.add_websocket_route(path, _build_ws_handler())
                _LOG.info(
                    "Mounted websocket: %s%s -> %s.%s",
                    route_prefix,
                    path,
                    name,
                    handler_name,
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
