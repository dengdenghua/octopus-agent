"""Optional device tools are supplied by enabled marketplace packages."""
from pathlib import Path


def device_plugin_tools_root(platform: str) -> Path:
    if platform not in {"android", "ios"}:
        raise ValueError("unsupported device platform")
    from runtime.platform.plugins.cloud_catalog import CloudCatalog, REPO
    from runtime.platform.plugins.marketplace_package import verify_marketplace_package_trust

    catalog = CloudCatalog("plugins", use_remote=False)
    plugin_id = f"echo-{platform}"
    # A nonexistent path keeps manifest consumers fail-closed without loading
    # bundled source files when a package is missing, disabled or invalid.
    unavailable = catalog.PLUGIN_INSTALL_ROOT / ".inactive-device-tools" / plugin_id
    if not catalog._marketplace_package_enabled(plugin_id, plugin_kind="codex"):
        return unavailable
    package = catalog.PLUGIN_INSTALL_ROOT / "codex" / plugin_id
    if not package.is_dir():
        package = catalog.CODEX_CACHE_ROOT / plugin_id
    try:
        verify_marketplace_package_trust(
            package, package_kind="codex", plugin_id=plugin_id,
            require_trusted=not (REPO / ".git").exists(),
        )
    except (OSError, ValueError):
        return unavailable
    return package / "tool-manifests"
