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
from contextlib import suppress
from pathlib import Path
from typing import Any

from runtime.platform.plugins.plugin_base import ModuleContext, ModulePlugin
from runtime.platform.plugins.workbench_activation import WorkbenchActivationStore

try:
    from fastapi import Request as _FastAPIRequest  # noqa: F401 – route annotation
    from fastapi import WebSocket as _FastAPIWebSocket  # noqa: F401 – route annotation
    from starlette.websockets import (  # noqa: F401
        WebSocketDisconnect as _FastAPIWebSocketDisconnect,
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
        activation_root: str | Path | None = None,
        data_root: str | Path | None = None,
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
        self._activation_store = WorkbenchActivationStore(
            root=activation_root,
            data_root=data_root,
            factory_root=self._bundled_dir or _DEFAULT_BUNDLED_PLUGIN_DIR,
        )

        # Loaded plugin instances: name -> ModulePlugin
        self._plugins: dict[str, ModulePlugin] = {}
        # Runtime contexts: name -> ModuleContext
        self._contexts: dict[str, ModuleContext] = {}
        # Mounted webhook routers: name -> APIRouter
        self._routers: dict[str, Any] = {}
        # Exact FastAPI route objects registered while each plugin loaded.
        # Removing by identity avoids touching routes owned by the host app.
        self._plugin_routes: dict[str, list[Any]] = {}
        # Plugins whose on_start hook completed.
        self._started: set[str] = set()
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
                if bundled and self._activation_store.is_factory(pname):
                    activation = self._activation_store.state(pname)
                else:
                    activation = {
                        "installed": True,
                        "enabled": True,
                        "source": "bundled" if bundled else "external",
                        "activation_path": None,
                        "data_path": None,
                        "recoveries": [],
                        "error": None,
                    }
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
                        "started": pname in self._started,
                        "installed": bool(activation["installed"]),
                        "enabled": bool(activation["enabled"]),
                        "source": activation["source"],
                        "activation_path": activation.get("activation_path"),
                        "data_path": activation.get("data_path"),
                        "recoveries": activation.get("recoveries", []),
                        "activation_error": activation.get("error"),
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

            candidate = next((item for item in self.discover() if item["id"] == name), None)
            if candidate is None:
                _LOG.warning("Plugin directory not found: %s", name)
                return None
            if not candidate["installed"]:
                _LOG.warning("Plugin %s is not installed", name)
                return None
            if not candidate["enabled"]:
                _LOG.warning("Plugin %s is disabled", name)
                return None
            plugin_dir = Path(candidate["dir"])
            if not plugin_dir.is_dir():
                _LOG.warning("Plugin directory not found: %s", plugin_dir)
                return None

            # 1. Parse manifest
            manifest_data = self._read_manifest_file(plugin_dir)
            if manifest_data is None:
                _LOG.warning("No plugin.yaml found in %s", plugin_dir)
                return None

            # 2. Import module. Bundled plugins live inside the canonical
            # ``runtime.platform.plugins.bundled`` package, which matters in a
            # frozen desktop build: PyInstaller keeps Python modules in its
            # PYZ archive while materialising plugin.yaml/page assets on disk.
            # Requiring a physical __init__.py or importing the plugin as a
            # top-level package therefore makes a discoverable bundled plugin
            # impossible to load after packaging. Third-party plugin folders
            # keep the legacy file-based import path.
            init_file = plugin_dir / "__init__.py"
            try:
                bundled = bool(
                    self._bundled_dir is not None
                    and plugin_dir.resolve().parent == self._bundled_dir.resolve()
                )
                canonical_name = f"runtime.platform.plugins.bundled.{name}"
                try:
                    canonical_spec = importlib.util.find_spec(canonical_name) if bundled else None
                except (ImportError, ModuleNotFoundError, ValueError):
                    canonical_spec = None

                if canonical_spec is not None:
                    mod = importlib.import_module(canonical_name)
                else:
                    if not init_file.exists():
                        _LOG.warning("Plugin %s missing __init__.py", name)
                        return None
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

            # 5. Call on_load (which triggers register_skills/channels/routes).
            # Snapshot routes first because a plugin may call include_router
            # directly rather than returning a router to the hub.
            route_snapshot = self._route_snapshot()
            try:
                instance.on_load(ctx)
                # 5.5 Composition layer: bind the plugin's provided services
                # so later consumers can resolve them through the ServiceBus.
                if self._service_bus is not None:
                    for service in block_manifest.provides:
                        self._service_bus.register(service, name, instance=instance)

                # 6. Auto-mount webhook routes from manifest
                self._mount_webhooks(name, manifest_data, plugin_dir)

                # 7. Surface manifest/capability drift without rejecting load.
                self._validate_manifest_provides(name, instance, manifest)
            except Exception as exc:
                _LOG.error("Plugin %s load failed: %s", name, exc, exc_info=True)
                self._rollback_failed_load(name, instance, ctx, route_snapshot)
                return None

            with self._lock_internal:
                self._plugins[name] = instance
                self._contexts[name] = ctx
                self._plugin_routes[name] = self._routes_added_since(route_snapshot)
                if self._plugin_routes[name]:
                    self._invalidate_openapi_schema()

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
                if not item["installed"] or not item["enabled"]:
                    continue
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

        discovered = [
            item
            for item in self.discover()
            if item["installed"] and item["enabled"]
        ]
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
            if name in self._started:
                self.stop(name)
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
                unload_route_snapshot = self._route_snapshot()
                try:
                    instance.on_unload(ctx)
                except Exception as exc:
                    _LOG.warning("Plugin %s on_unload error: %s", name, exc)
                finally:
                    self._plugin_routes.setdefault(name, []).extend(
                        self._routes_added_since(unload_route_snapshot)
                    )

                # Clean up skill/channel registrations so the plugin can be reloaded
                try:
                    ctx.cleanup_registrations()
                except Exception as exc:
                    _LOG.debug("Plugin %s cleanup_registrations error: %s", name, exc)

            self._routers.pop(name, None)
            self._remove_plugin_routes(name)
            self._started.discard(name)

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
        with self._lock_internal:
            if name in self._started:
                return True
            instance = self._plugins.get(name)
            ctx = self._contexts.get(name)
            if instance is None or ctx is None:
                _LOG.warning("Cannot start plugin %s: not loaded", name)
                return False
            route_snapshot = self._route_snapshot()
            try:
                instance.on_start(ctx)
                self._plugin_routes.setdefault(name, []).extend(
                    self._routes_added_since(route_snapshot)
                )
                self._invalidate_openapi_schema()
                self._started.add(name)
                _LOG.info("Plugin started: %s", name)
                return True
            except Exception as exc:
                self._remove_route_objects(self._routes_added_since(route_snapshot))
                _LOG.error("Plugin %s on_start failed: %s", name, exc, exc_info=True)
                return False

    def start_all(self) -> list[str]:
        started: list[str] = []
        for name in list(self._plugins):
            if self.start(name):
                started.append(name)
        return started

    def stop(self, name: str) -> bool:
        """Stop a started plugin (calls on_stop)."""
        with self._lock_internal:
            if name not in self._started:
                return name in self._plugins
            instance = self._plugins.get(name)
            ctx = self._contexts.get(name)
            if instance is None or ctx is None:
                self._started.discard(name)
                _LOG.warning("Cannot stop plugin %s: not loaded", name)
                return False
            route_snapshot = self._route_snapshot()
            try:
                instance.on_stop(ctx)
                _LOG.info("Plugin stopped: %s", name)
                return True
            except Exception as exc:
                _LOG.error("Plugin %s on_stop failed: %s", name, exc)
                return False
            finally:
                self._plugin_routes.setdefault(name, []).extend(
                    self._routes_added_since(route_snapshot)
                )
                self._started.discard(name)

    def stop_all(self) -> list[str]:
        stopped: list[str] = []
        for name in list(self._plugins):
            if self.stop(name):
                stopped.append(name)
        return stopped

    # ── Persistent install / enable lifecycle ─────────────────

    def install_plugin(
        self,
        name: str,
        *,
        enabled: bool = True,
        restore_data: bool = False,
        recovery_id: str | None = None,
    ) -> dict[str, Any]:
        """Activate a factory seed and, when enabled, load it immediately."""

        with self._lock_internal:
            self._require_factory_plugin(name)
            previous = self._activation_store.state(name)
            result = self._activation_store.install(
                name,
                enabled=enabled,
                restore_data=restore_data,
                recovery_id=recovery_id,
            )
            try:
                if enabled:
                    self._activate_runtime(name)
            except Exception:
                self.unload(name)
                self._activation_store.restore_state(name, previous)
                raise
            return self._lifecycle_result(name, result)

    def enable_plugin(self, name: str) -> dict[str, Any]:
        """Persist enablement and make the plugin live without a restart."""

        with self._lock_internal:
            self._require_factory_plugin(name)
            previous = self._activation_store.state(name)
            result = self._activation_store.enable(name)
            try:
                self._activate_runtime(name)
            except Exception:
                self.unload(name)
                self._activation_store.restore_state(name, previous)
                raise
            return self._lifecycle_result(name, result)

    def disable_plugin(self, name: str) -> dict[str, Any]:
        """Stop/unload a plugin and persist its disabled state."""

        with self._lock_internal:
            self._require_factory_plugin(name)
            state = self._activation_store.state(name)
            if not state["installed"]:
                raise ValueError(f"workbench is not installed: {name}")
            was_loaded = name in self._plugins
            was_started = name in self._started
            if was_loaded:
                self.unload(name)
            try:
                result = self._activation_store.disable(name)
            except Exception:
                if was_loaded:
                    self.load(name)
                    if was_started:
                        self.start(name)
                raise
            return self._lifecycle_result(name, result)

    def uninstall_plugin(
        self,
        name: str,
        *,
        data_policy: str = "keep",
        confirm_data_move: bool = False,
    ) -> dict[str, Any]:
        """Deactivate a factory seed; keep works unless trash is explicit."""

        with self._lock_internal:
            self._require_factory_plugin(name)
            state = self._activation_store.state(name)
            if not state["installed"]:
                raise ValueError(f"workbench is not installed: {name}")
            was_loaded = name in self._plugins
            was_started = name in self._started
            if was_loaded:
                self.unload(name)
            try:
                result = self._activation_store.uninstall(
                    name,
                    data_policy=data_policy,
                    confirm_data_move=confirm_data_move,
                )
            except Exception:
                if was_loaded:
                    self.load(name)
                    if was_started:
                        self.start(name)
                raise
            return self._lifecycle_result(name, result)

    def _activate_runtime(self, name: str) -> None:
        if self.load(name) is None:
            raise RuntimeError(f"failed to load plugin: {name}")
        if not self.start(name):
            raise RuntimeError(f"failed to start plugin: {name}")

    def _require_factory_plugin(self, name: str) -> None:
        if not self._activation_store.is_factory(name):
            raise KeyError(f"plugin does not support persistent lifecycle: {name}")
        candidate = next((item for item in self.discover() if item["id"] == name), None)
        if candidate is None or not candidate.get("bundled"):
            raise KeyError(f"factory plugin is unavailable: {name}")

    def _lifecycle_result(self, name: str, result: dict[str, Any]) -> dict[str, Any]:
        state = self._activation_store.state(name)
        return {
            **result,
            "ok": True,
            "plugin_id": name,
            "installed": state["installed"],
            "enabled": state["enabled"],
            "loaded": name in self._plugins,
            "started": name in self._started,
            "source": "factory",
            "activation_path": state["activation_path"],
            "recoveries": state["recoveries"],
            "restart_required": False,
        }

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
        """Return discovered plugins, including unloaded lifecycle state."""
        result: list[dict[str, Any]] = []
        for discovered in self.discover():
            pname = discovered["id"]
            instance = self._plugins.get(pname)
            ctx = self._contexts.get(pname)
            caps = []
            if instance is not None:
                for c in instance.capabilities:
                    caps.append({"type": c.type, "name": c.name, "description": c.description})
            if not discovered["installed"]:
                lifecycle_state = "uninstalled"
            elif not discovered["enabled"]:
                lifecycle_state = "disabled"
            elif instance is None:
                lifecycle_state = "installed"
            else:
                lifecycle_state = "active"
            result.append(
                {
                    **discovered,
                    "id": pname,
                    "name": (
                        (getattr(instance, "display_name", "") if instance else "")
                        or discovered["name"]
                    ),
                    "display_name": (
                        (getattr(instance, "display_name", "") if instance else "")
                        or discovered["display_name"]
                    ),
                    "version": (
                        getattr(instance, "version", discovered["version"])
                        if instance
                        else discovered["version"]
                    ),
                    "description": (
                        getattr(instance, "description", discovered["description"])
                        if instance
                        else discovered["description"]
                    ),
                    "author": (
                        getattr(instance, "author", discovered["author"])
                        if instance
                        else discovered["author"]
                    ),
                    "capabilities": caps,
                    "config_schema": (
                        ctx.manifest.config_schema
                        if ctx
                        else (
                            self._read_manifest_file(Path(discovered["dir"])) or {}
                        ).get("config_schema", {})
                    ),
                    "config_ui": instance.config_ui_component if instance else None,
                    "loaded": instance is not None,
                    "started": pname in self._started,
                    "error": discovered.get("activation_error"),
                    "dir": ctx.plugin_dir if ctx else discovered["dir"],
                    "dependencies": getattr(instance, "dependencies", []) if instance else [],
                    "state": lifecycle_state,
                }
            )
        return result

    def get_plugin_detail(self, name: str) -> dict[str, Any] | None:
        return next((item for item in self.list_plugins() if item["id"] == name), None)

    # ── Internal helpers ───────────────────────────────────────

    def _route_snapshot(self) -> tuple[Any, ...]:
        if self._fastapi_app is None:
            return ()
        router = getattr(self._fastapi_app, "router", None)
        routes = getattr(router, "routes", None)
        return tuple(routes or ())

    def _routes_added_since(self, snapshot: tuple[Any, ...]) -> list[Any]:
        if self._fastapi_app is None:
            return []
        before = {id(route) for route in snapshot}
        return [route for route in self._route_snapshot() if id(route) not in before]

    def _remove_route_objects(self, routes: list[Any]) -> None:
        if self._fastapi_app is None or not routes:
            return
        router = getattr(self._fastapi_app, "router", None)
        current = getattr(router, "routes", None)
        if current is None:
            return
        remove_ids = {id(route) for route in routes}
        current[:] = [route for route in current if id(route) not in remove_ids]
        self._invalidate_openapi_schema()

    def _invalidate_openapi_schema(self) -> None:
        if self._fastapi_app is not None and hasattr(self._fastapi_app, "openapi_schema"):
            self._fastapi_app.openapi_schema = None

    def _remove_plugin_routes(self, name: str) -> None:
        self._remove_route_objects(self._plugin_routes.pop(name, []))

    def _rollback_failed_load(
        self,
        name: str,
        instance: ModulePlugin,
        ctx: ModuleContext,
        route_snapshot: tuple[Any, ...],
    ) -> None:
        if self._service_bus is not None:
            with suppress(Exception):
                self._service_bus.unbind(name)
        with suppress(Exception):
            instance.on_unload(ctx)
        with suppress(Exception):
            ctx.cleanup_registrations()
        self._remove_route_objects(self._routes_added_since(route_snapshot))
        self._routers.pop(name, None)
        self._plugin_routes.pop(name, None)
        self._contexts.pop(name, None)
        self._plugins.pop(name, None)
        self._started.discard(name)

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
                            with suppress(Exception):  # noqa: BLE001 – best-effort close
                                await websocket.close(code=1011)

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
            raise


def get_plugin_hub() -> PluginHub:
    """Get the global PluginHub singleton."""
    return PluginHub.get()


__all__ = [
    "PluginHub",
    "get_plugin_hub",
]
