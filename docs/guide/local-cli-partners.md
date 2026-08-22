# Local CLI partners

Octopus can register installed third-party coding CLIs as local partners. The
partner still uses its own login, model namespace, subscription, permissions,
and native slash-command behavior; Octopus supplies discovery, readiness
checks, dispatch, diagnostics, and team summaries.

## Supported partner IDs

- `claude-code`
- `codex-cli`
- `trae-cli`
- `qoder-cli`
- `kimi-cli`
- `codebuddy-cli`
- `openclaw` discovery is kept, but prompt-to-stdout dispatch is not enabled.

## Readiness states

Consumers should prefer `effective_status` over the older `status` field.

- `registered` means the partner is registered and currently ready.
- `ready` means installed and ready to connect/register.
- `model_unconfigured` means the CLI is present but has no usable model.
- `launcher_only` means a desktop launcher was found, but no headless CLI is
  available.
- `headless_unsupported` means Octopus cannot safely drive this partner in a
  prompt-to-stdout mode yet.
- `missing` means no safe executable was detected.

The older `status` field remains for compatibility and only describes registry
or detection shape (`registered`, `detected`, `missing`). It is not enough to
decide whether the partner can run now.

## Diagnostic matrix

Each partner exposes `diagnostic_items` for the connect dialog. The matrix keeps
provider-specific facts server-side while the UI renders a consistent shape:

| Label | Meaning |
| --- | --- |
| Model source | Whether the partner supports one-shot `/model` override, uses its own default, or requires native model setup. |
| Account/entitlement | Reminds operators that CLI login, subscription, enterprise authorization, and desktop free entitlements may differ. |
| Headless | Whether the detected command can run prompt-to-stdout tasks or is launcher/manual only. |
| Check command | The copyable command or health check that proves the current CLI can actually run from Octopus. |

## Doctor summary

`GET /api/agents/local-partners/doctor` returns a machine-level readiness
summary without spawning external CLIs. It aggregates the same detection data as
the connect dialog:

- `summary`, `total`, `detected`, `ready`, `registered`, and
  `needs_attention`
- grouped partner status rows such as `ready`, `model_unconfigured`,
  `launcher_only`, `headless_unsupported`, and `missing`
- bounded `next_actions` that explain whether to install a CLI, open the
  native CLI, choose a model, fix PATH, or wait for headless support

The connect dialog surfaces this as **Local CLI Doctor** so operators can see
the whole machine state before expanding individual partner cards.

## Native CLI boundary

The connect dialog exposes both copyable native commands and Octopus-compatible
slash-command hints.

- Desktop apps and CLIs do not always share accounts, subscriptions, enterprise
  network state, or free entitlements. A desktop app being usable is not enough
  evidence that its CLI can run headless from Octopus.
- `/model <model>` is translated to a one-shot model override only for partners
  with stable model flags: Claude Code, Codex CLI, and CodeBuddy CLI.
- `/login`, `/doctor`, `/status`, `/config`, `/clear`, `/compact`, and
  `/resume` are not forwarded through headless dispatch. Use the native CLI
  terminal for those commands.
- `native_launch_command` enters `native_launch_cwd` before launching the CLI,
  so users can paste one command and land in the current project root.

## Codex App Server backend

When a registered `codex-cli` partner is selected, Octopus can keep the public
task, journal, approvals, cancellation, and UI lifecycle in Octopus while an
isolated Codex App Server owns the inner coding turn. The integration uses the
local stdio JSONL transport with `--strict-config`; App Server protocol objects
are translated into Octopus events and are never exposed as the public API.

### Enablement and fail-closed rules

- Single-user/local deployments use App Server by default. Set
  `OCTOPUS_CODEX_APP_SERVER_ENABLED=false` and restart Octopus to opt out, or
  set the selected partner capability `codex_app_server` to `false`.
- `commercial`, `production`, `server`, and `shared` deployment modes always
  enter the App Server security boundary for a Codex partner. They require an
  explicit, non-default `execution.codex_app_server=true` setting (the legacy
  environment source is `OCTOPUS_CODEX_APP_SERVER_ENABLED=true`). A missing or
  false setting is rejected and cannot silently select the legacy CLI path.
- Production-like modes also require a verified, **full-enforcement** outer
  process sandbox and a successful launch transformation. This preview accepts
  Bubblewrap (`bwrap`) for that boundary; the current Seatbelt and Landlock
  backends report partial enforcement and are rejected for production Codex
  sidecars. Use `OCTOPUS_PROCESS_SANDBOX=strict` (or `bwrap`) and install the
  Codex executable below `/usr` (for example `/usr/local/bin/codex`) so it is
  present in Bubblewrap's read-only system mounts. A missing backend, partial
  backend, transform failure, or inaccessible executable rejects the turn.
  See [the sandbox risk boundary](../security/sandbox-risk-boundary.md).
- On macOS, Seatbelt cannot be nested: an App Server already wrapped by
  `sandbox-exec` cannot apply the second Seatbelt profile required by Codex's
  built-in shell and patch tools. In local/development mode, when a hard outer
  sandbox is not required and auto-selection returns Seatbelt, Octopus leaves
  only the App Server process unwrapped and records
  `outer_sandbox=none_due_to_nested_incompatibility`; the validated standalone
  `octopus-sidecar` permission profile grants only Codex's minimal platform
  runtime, the authoritative workspace, and turn scratch. It does not inherit
  Codex's built-in `:workspace`/`:read-only` profiles because both make the host
  filesystem readable. The `on-request` broker still constrains every generated
  tool. Production/shared and explicit strict postures reject
  this combination before process start instead of taking that compatibility
  path. Octopus does not select Codex's `external-sandbox` mode because the
  outer App Server needs inference network access while generated tools must
  remain network-denied.
- Production credentials must be provisioned for the correct tenant/principal
  before enabling the feature. This preview accepts one explicit source home
  per Octopus process, so multi-tenant operators must use tenant-dedicated
  instances or keep the feature disabled; never share a personal Codex login.

### Runtime settings

| Setting | Operational contract |
| --- | --- |
| `OCTOPUS_DEPLOYMENT_MODE` | `local` by default. `commercial`, `production`, `server`, and `shared` activate production-like fail-closed rules. |
| `OCTOPUS_CODEX_APP_SERVER_ENABLED` | Local opt-out with `false`; production-like deployments require an explicit `true`. The runtime feature name is `execution.codex_app_server`. |
| `OCTOPUS_CODEX_STATE_DIR` | Optional absolute state root. It must not overlap the workspace. The default is the Octopus data directory under `codex_backend`, with `~/.octopus/codex_backend` as a non-overlapping fallback. |
| `OCTOPUS_CODEX_SOURCE_HOME` | Optional absolute source Codex home. Local mode defaults to `~/.codex`; production-like modes have no default and require explicit credential provisioning. Only a validated `auth.json` is copied—host Codex config is not inherited. |
| `OCTOPUS_CODEX_APP_SERVER_TIMEOUT` | Turn deadline in seconds. Default `1800`; values are clamped to `30..14400`; invalid values use the default and emit a warning. |
| `OCTOPUS_CODEX_REALM` | Optional stable realm partition for persisted inner-thread bindings. Changing it creates a different resume namespace. |

The state root is private and partitioned by opaque realm, tenant/principal,
and outer-thread identifiers. The isolated `CODEX_HOME` and thread binding are
kept so later outer turns can resume the same inner thread; task HOME, temp,
and scratch trees are fresh per turn and removed when the sidecar closes.
`OCTOPUS_CODEX_SOURCE_HOME/auth.json` must be a current-owner, private, regular
non-symlink file, no larger than 1 MiB, containing a JSON object. Missing local
credentials are not borrowed from ambient environment variables.

### Approval and isolation boundary

- The server-resolved absolute `cwd` is the only workspace authority. Client
  `workspace_path` values are ignored, and requested full access is capped at
  `workspace-write` (or `read-only` when the outer task is read-only).
- App Server receives an allow-listed environment and isolated HOME/temp/XDG
  paths. Network access, MCP servers, plugins, apps, hooks, memories,
  multi-agent features, and other ambient extensions are disabled. Generated
  commands receive Codex's `:minimal` platform-runtime reads plus exact access
  to the workspace and the turn's marked scratch root; arbitrary host-home,
  neighboring workspace, and tenant-state reads are not granted. The workspace
  is writable only for workspace-write tasks, while private turn scratch remains
  writable so built-in tools can operate. Global temp aliases and the sidecar
  state parent remain explicitly denied.
- The outer App Server process itself retains network access only so it can
  call the model service. The independently validated inner named-permission
  profile still denies network to model-generated tools. When an outer hard
  sandbox is active, it mounts only the exact isolated Codex home, task root,
  and scratch root; it does not make their state-root parent or a neighboring
  tenant directory writable. The macOS local compatibility path above relies
  on the same validated inner profile for those generated-tool boundaries.
- Octopus is the approval broker. Codex runs with `on-request` approval and a
  user reviewer; command and file-change requests are scoped to the exact
  outer and inner turn. Approval timeouts, broker errors, or interruption
  decline the request. Permission-expansion requests are always declined, and
  any granted root must remain inside the authoritative workspace.
- Closing or cancelling the task interrupts the inner turn and then terminates
  the complete App Server process tree after a short grace period.

### Compatibility fallback

In local/single-user mode, the hardened one-shot `codex exec` adapter is used
only when App Server cannot start or a required versioned API is unsupported
**before** `turn/start` is attempted. Production-like modes never downgrade to
the legacy adapter. Security, credential, effective-config, workspace,
approval, and thread-binding failures never downgrade to `exec`. Once the
`turn/start` boundary is crossed, a lost response or protocol failure is
terminal and is never retried through another executor; this prevents
duplicate model/tool execution.

### Versioning and verification

OpenAI documents Codex App Server as an experimental interface and currently
does not support it for production workloads. Treat Octopus production-like
enablement as a controlled preview: pin the exact Codex binary version, do not
auto-upgrade it independently of Octopus, and regenerate/diff the versioned
App Server schemas before an upgrade. See the
[official Codex App Server documentation](https://developers.openai.com/codex/app-server/).

For an upgrade, record `codex --version`, generate both schema forms, review
the diff, then run the focused contract suite and a tenant-isolated canary:

```bash
codex app-server generate-ts --out ./schemas
codex app-server generate-json-schema --out ./schemas
.venv/bin/pytest -q tests/test_codex_appserver_client.py tests/test_codex_execution_backend.py tests/test_codex_backend_approvals.py tests/test_codex_backend_events.py tests/runtime/execution/codex_backend/test_security.py tests/test_drive_codex_app_server.py
```

## Failure recovery

Health checks and CLI-team runs surface structured failures:

- `failure_kind`
- `failure_title`
- `fix_hint`
- `raw_error`

Failure kinds should map to user actions instead of leaking raw stderr first:

| `failure_kind` | User-facing recovery |
| --- | --- |
| `missing_binary` | Install the official CLI and restore the command in `PATH`. |
| `auth` | Open the native CLI and complete login or token authorization. |
| `entitlement` | Confirm the CLI account has subscription, enterprise, or model access; desktop entitlements may not apply. |
| `model` | Pick/configure a model in the native CLI or partner model selector. |
| `permission` | Trust the workspace or adjust the CLI's permission mode. |
| `network` | Fix proxy, DNS, Kerberos, VPN, or enterprise network access in the native CLI first. |
| `quota` | Check billing, rate limits, or switch to an available model/account. |
| `version` | Upgrade the CLI or confirm the documented headless/print flags are supported by `--help`. |
| `empty_output` | Confirm the CLI has a real prompt-to-stdout mode instead of launching an interactive TUI. |

CLI team summaries surface one or more deduplicated repair hints, so a mixed
failure such as "Codex not logged in" plus "Trae model not configured" does not
collapse into a single misleading next step.

CLI team runs also return `recovery_groups`: failed members are grouped by
`failure_kind` with a short label, member list, and deduplicated `fix_hints`.
Team task metadata preserves those groups so the UI can show "auth failures",
"model setup failures", or "entitlement failures" separately instead of making
the operator parse raw stderr.

## Merge-check commands

Run this focused set before merging local CLI partner work:

```bash
.venv/bin/pytest -q tests/test_agents_router.py::TestLocalPartners tests/test_agents_router_local_partner_security.py tests/test_local_partner_bridge.py tests/test_cli_team.py
npm --prefix frontend run test -- src/components/workspace/agents/local-agent-status.test.ts
npm --prefix frontend run typecheck
.venv/bin/pytest -q tests/test_evolution_modules.py tests/test_evolution_router.py
```
