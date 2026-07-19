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

## Native CLI boundary

The connect dialog exposes both copyable native commands and Octopus-compatible
slash-command hints.

- `/model <model>` is translated to a one-shot model override only for partners
  with stable model flags: Claude Code, Codex CLI, and CodeBuddy CLI.
- `/login`, `/doctor`, `/status`, `/config`, `/clear`, `/compact`, and
  `/resume` are not forwarded through headless dispatch. Use the native CLI
  terminal for those commands.
- `native_launch_command` enters `native_launch_cwd` before launching the CLI,
  so users can paste one command and land in the current project root.

## Failure recovery

Health checks and CLI-team runs surface structured failures:

- `failure_kind`
- `failure_title`
- `fix_hint`
- `raw_error`

CLI team summaries surface one or more deduplicated repair hints, so a mixed
failure such as "Codex not logged in" plus "Trae model not configured" does not
collapse into a single misleading next step.

## Merge-check commands

Run this focused set before merging local CLI partner work:

```bash
.venv/bin/pytest -q tests/test_agents_router.py::TestLocalPartners tests/test_agents_router_local_partner_security.py tests/test_local_partner_bridge.py tests/test_cli_team.py
npm --prefix frontend run test -- src/components/workspace/agents/local-agent-status.test.ts
npm --prefix frontend run typecheck
.venv/bin/pytest -q tests/test_evolution_modules.py tests/test_evolution_router.py
```
