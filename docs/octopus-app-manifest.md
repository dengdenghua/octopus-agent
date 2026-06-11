# Octopus App Manifest

`octopus-app.jsonc` is the first-class application manifest for Octopus ability
packs and plugins. It describes user-facing app entries, their category, local
entry point, permissions, and agent-callable actions.

Octopus still reads legacy `.app.json` files for Codex plugin compatibility, but
new packs should prefer `octopus-app.jsonc`.

## Location

Place the manifest at the plugin or ability-pack root:

```text
my-plugin/
  .codex-plugin/plugin.json
  octopus-app.jsonc
  apps/
    research-console/
      index.html
```

Apps may also live under `apps/<app-id>/octopus-app.jsonc` when a plugin carries
multiple independently versioned apps.

## Shape

```jsonc
{
  "$schema": "./schemas/octopus-app.schema.json",
  "schema_version": "1",
  "apps": {
    "research-console": {
      "title": "Research Console",
      "description": "Review sourced briefs and saved pages",
      "category": "research",
      "icon": "./assets/research-console.png",
      "route": "/workspace/apps/research-console",
      "entry": "./apps/research-console/index.html",
      "permissions": ["workspace.read"],
      "actions": [
        {
          "name": "open_brief",
          "description": "Open a saved research brief",
          "input_schema": {
            "type": "object",
            "properties": {
              "brief_id": { "type": "string" }
            },
            "required": ["brief_id"]
          },
          "requires_confirmation": false
        }
      ]
    }
  }
}
```

## Fields

- `schema_version`: manifest format version. Use `"1"` for the current shape.
- `apps`: object keyed by the stable Octopus app id.
- `title`: human-readable app name.
- `description`: short one-line purpose.
- `category`: display bucket for the front-end app directory. Recommended values:
  `ai`, `creative`, `developer`, `research`, `productivity`, `finance`,
  `ops`, `connector`, or `other`.
- `icon`: optional relative path or URL.
- `route`: optional Octopus route used when the app is natively mounted.
- `entry`: optional relative web entry point for packaged web apps.
- `permissions`: optional list of capability strings requested by the app.
- `actions`: optional list or map of agent-callable actions.
- `actions[].input_schema`: JSON Schema object for action input.
- `actions[].requires_confirmation`: set true for write, spend, publish, or
  external side-effect actions.

## Legacy Compatibility

Legacy `.app.json` may contain:

```json
{
  "apps": {
    "github": {
      "id": "connector_..."
    }
  }
}
```

Octopus treats the object key (`github`) as the app id and preserves the legacy
connector id as `connector_id` in the API response.
