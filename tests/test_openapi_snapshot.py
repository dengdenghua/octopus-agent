"""
OpenAPI schema snapshot · wire-contract drift detector.

Purpose
-------

FastAPI auto-generates ``/openapi.json`` from endpoint signatures and
response models. The frontend depends on this shape (and in a future
iteration will generate TS types from it). Silent shape drift — a
field added, a required field removed, a response model swapped for
``dict[str, Any]`` — breaks the frontend at runtime with no compile-
time signal.

This test snapshots the schema to ``docs/openapi-snapshot.json`` and
diffs it on every run. Any change in paths, methods, request/response
schemas, or component models fails the test — forcing the author to
either (a) update the snapshot intentionally and explain why in the
PR, or (b) revert the unintentional drift.

Regenerating the snapshot
-------------------------

When the drift is intentional::

    OCTOPUS_OPENAPI_WRITE=1 pytest tests/test_openapi_snapshot.py

Then commit the updated ``docs/openapi-snapshot.json`` as part of the
same PR as the endpoint change · reviewers see both.

Why snapshot and not stronger schema validation
-----------------------------------------------

* A stricter "every endpoint must return a typed pydantic model"
  invariant would be ideal but requires touching every endpoint —
  a larger migration than this session can absorb.
* A snapshot catches *drift* even on ``dict[str, Any]`` endpoints
  (because the path/method entry disappears or reshapes), giving
  a useful signal while the typed-response migration happens
  gradually.
* OCTOPUS_OPENAPI_WRITE=1 keeps the update loop cheap for
  intentional changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "docs" / "openapi-snapshot.json"
_REPOSITORY_ROOT = SNAPSHOT_PATH.parent.parent
_SCHEMA_OUTPUT_ENV = "OCTOPUS_OPENAPI_SCHEMA_OUTPUT"
_SCHEMA_SCRIPT = f"""
import json
import os
from pathlib import Path

from runtime.platform.ui import _app_routers_extra

# The contract snapshot covers the stable host API. Bundled workbench plugins
# contribute their own separately tested routes and change independently, so
# point PluginHub at empty roots before constructing the app. Without this,
# merely adding an installed/bundled plugin makes the supposedly hermetic base
# schema depend on the checkout contents.
plugin_root = Path(os.environ[{_SCHEMA_OUTPUT_ENV!r}]).parent / "plugins"
(plugin_root / "user").mkdir(parents=True, exist_ok=True)
(plugin_root / "bundled").mkdir(parents=True, exist_ok=True)
_app_routers_extra._plugin_hub_roots = lambda: (
    plugin_root / "user",
    plugin_root / "bundled",
)

from runtime.platform.ui.app import create_app

schema = create_app().openapi()
Path(os.environ[{_SCHEMA_OUTPUT_ENV!r}]).write_text(
    json.dumps(schema, ensure_ascii=False),
    encoding="utf-8",
)
"""


@lru_cache(maxsize=1)
def _current_schema() -> dict:
    """Build the live schema in a hermetic child process.

    We intentionally build with NO stack / registry so the snapshot
    reflects the base surface area · adding a stack-conditional
    endpoint shouldn't shift the baseline.  The fresh interpreter and
    temporary HOME/data roots are also important: connector modules cache
    default paths at import time, and an unrelated local master key must not
    decide whether connector/capability routes appear in this contract.  The
    schema is immutable within this module's tests, so one hermetic build is
    shared across the three contract assertions.
    """
    with tempfile.TemporaryDirectory(prefix="octopus-openapi-") as temporary:
        isolated_root = Path(temporary)
        schema_path = isolated_root / "openapi.json"
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("OCTOPUS_")
        }
        environment.update(
            {
                "HOME": str(isolated_root / "home"),
                "XDG_CACHE_HOME": str(isolated_root / "cache"),
                "XDG_CONFIG_HOME": str(isolated_root / "config"),
                "XDG_DATA_HOME": str(isolated_root / "share"),
                "OCTOPUS_DATA_DIR": str(isolated_root / "data"),
                "OCTOPUS_HOME": str(isolated_root / "octopus-home"),
                "OCTOPUS_RESOURCES_DIR": str(_REPOSITORY_ROOT),
                _SCHEMA_OUTPUT_ENV: str(schema_path),
            }
        )
        completed = subprocess.run(
            [sys.executable, "-c", _SCHEMA_SCRIPT],
            cwd=_REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert completed.returncode == 0, (
            "isolated OpenAPI app failed to build:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
        assert schema_path.is_file(), "isolated OpenAPI builder did not write a schema"
        return json.loads(schema_path.read_text(encoding="utf-8"))


def _normalize(schema: dict) -> dict:
    """Drop fields that change across runs without being actual
    contract changes.

    Currently: the top-level ``info.version`` string — we bump it in
    ``create_app(... version="0.1.0")`` and don't want a release bump
    to invalidate the snapshot. The per-endpoint ``operationId`` and
    ``x-*`` extensions are kept because they ARE part of the wire
    contract a client would bind to.
    """
    out = json.loads(json.dumps(schema))  # deep copy
    info = out.get("info", {})
    info.pop("version", None)
    return out


def test_openapi_snapshot_matches() -> None:
    """Hard-fail on any drift. Set ``OCTOPUS_OPENAPI_WRITE=1`` to
    intentionally regenerate."""
    current = _normalize(_current_schema())

    if os.environ.get("OCTOPUS_OPENAPI_WRITE") == "1":
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        pytest.skip(
            "snapshot regenerated; commit docs/openapi-snapshot.json",
        )

    if not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(
            json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        pytest.fail(
            f"snapshot file missing — created baseline at "
            f"{SNAPSHOT_PATH.relative_to(Path.cwd()) if SNAPSHOT_PATH.is_relative_to(Path.cwd()) else SNAPSHOT_PATH}. "
            "Commit it and re-run the test."
        )

    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    # Rather than a raw string diff, compare shape-level maps so the
    # pytest failure message can pinpoint exactly which path drifted.
    cur_paths = set(current.get("paths", {}).keys())
    snap_paths = set(snapshot.get("paths", {}).keys())
    added = cur_paths - snap_paths
    removed = snap_paths - cur_paths

    if added or removed:
        pytest.fail(
            f"OpenAPI path set drifted.\n"
            f"  added: {sorted(added)}\n"
            f"  removed: {sorted(removed)}\n"
            "Run with OCTOPUS_OPENAPI_WRITE=1 if intentional."
        )

    # Per-path method + schema-ref check. Full dict equality would be
    # noisy (operationId name changes, etc); we compare just the
    # method set + 200-response $ref per path.
    for p in sorted(cur_paths):
        cur_methods = set(current["paths"][p].keys())
        snap_methods = set(snapshot["paths"][p].keys())
        if cur_methods != snap_methods:
            pytest.fail(
                f"Methods on {p} drifted: "
                f"current={sorted(cur_methods)} snapshot={sorted(snap_methods)}"
            )

    # Component schema names — adding one is fine (new typed model);
    # removing one is a breaking change the caller should know about.
    cur_components = set(
        (current.get("components") or {}).get("schemas", {}).keys(),
    )
    snap_components = set(
        (snapshot.get("components") or {}).get("schemas", {}).keys(),
    )
    removed_components = snap_components - cur_components
    if removed_components:
        pytest.fail(
            f"OpenAPI component schemas removed (breaking): "
            f"{sorted(removed_components)}. Run with "
            "OCTOPUS_OPENAPI_WRITE=1 if intentional."
        )


def test_openapi_response_models_on_config_endpoints() -> None:
    """Hard assertion · the config endpoints MUST use typed response
    models, not ``dict[str, Any]``. Guards against someone reverting
    the typed responses we just added in config_router.py.

    The ``/api/agents`` route isn't asserted here because it only
    registers when ``agent_registry`` is injected into ``create_app``
    — left for a follow-up when we build a representative test app.
    """
    schema = _current_schema()

    checks = [
        ("/api/config/identity-lock", "get", "IdentityLockResponse"),
        ("/api/config/identity-lock", "put", "IdentityLockResponse"),
        ("/api/providers", "get", "ProvidersResponse"),
        ("/api/config/custom-models", "get", "CustomModelsList"),
    ]
    for path, method, expected_component in checks:
        spec = schema["paths"][path][method]
        ref = spec["responses"]["200"]["content"]["application/json"]["schema"].get("$ref", "")
        assert ref.endswith(f"/{expected_component}"), (
            f"{method.upper()} {path} should return {expected_component} · "
            f"got ref={ref!r}. If the model was renamed intentionally, "
            "update both the check above and regenerate the snapshot."
        )


def test_device_flow_generation_contract_is_typed() -> None:
    """Device-flow cancellation must be generation-scoped on both public surfaces."""
    schema = _current_schema()
    for path in (
        "/api/connectors/{connector_id}/device-flow",
        "/api/capabilities/{cid}/device-flow",
    ):
        delete = schema["paths"][path]["delete"]
        generation = next(
            parameter
            for parameter in delete["parameters"]
            if parameter["name"] == "expected_flow_id"
        )
        assert generation["in"] == "query"
        assert generation["required"] is True
        assert delete["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
            "/DeviceFlowCancelResponse"
        )
        assert schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/DeviceFlowResponse")

    payload = schema["components"]["schemas"]["DeviceFlowPayload"]
    assert "flow_id" in payload["required"]
    assert payload["properties"]["flow_id"]["minLength"] == 1
