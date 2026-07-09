# CLAUDE.md

Guidance for Claude Code / agents working in this repo. For the architecture,
see [docs/architecture/module-map.md](docs/architecture/module-map.md) (the
organ-name ↔ package map) and the [docs/](docs/) tree; this file is the short
operational cheat-sheet.

## What this is

`octopus-agent` — a Python multi-agent runtime (FastAPI backend in `runtime/`,
React/Vite frontend in `frontend/`). Python `>=3.11`. One of the Octopus family
of repos (agent / mobile / os / enterprise / storage).

## Toolchain (this machine)

Independent toolchains — **not** the system ones:
- Python venv: `.venv/` (created via `uv`). Run Python as `.venv/bin/python`.
- `uv` lives at `~/.local/octopus-tools/uv`; Node/pnpm at `~/.local/node/bin`.
- Frontend uses **pnpm** (`frontend/`).

## Common commands (Makefile)

```bash
make install          # dev deps (uv)
make dev              # backend dev server, config.local.yaml + .env
make dev-full         # backend + frontend together
make test             # pytest + coverage
make test-fast        # pytest, no coverage
make test-unit        # exclude slow + integration
make lint             # invariant checks (active: LINT-02/03/04/05/09) + ruff
make fix              # ruff --fix + format
make security         # bandit + pip-audit
make frontend-build   # build frontend/dist for FastAPI /ui
make openapi-snapshot # regenerate docs/openapi-snapshot.json
make frontend-types   # regenerate TS types FROM the openapi snapshot
```

Run the backend directly (matches `.claude/launch.json`):
```bash
.venv/bin/python -m runtime serve --config config.local.yaml --port 8000
```
CLI entrypoints: `octopus` / `octopus-agent` → `runtime.cli:main`.

Frontend (in `frontend/`): `pnpm dev` (port 3000), `pnpm build`, `pnpm test`
(vitest), `pnpm lint` (eslint), typecheck via `make frontend-typecheck`.

## Conventions

- **ruff**: line-length 100, double quotes. `E501` is ignored (formatter owns
  wrapping). Custom exceptions like `InvariantViolation` intentionally skip the
  `Error` suffix (`N818` ignored).
- **Invariant lint** (`make lint-invariants`, `octopus-lint`) enforces the
  active project rules (LINT-02/03/04/05/09; 01 and 10 retired with their
  target packages, 06/07/08 unimplemented) — run it, not just ruff, before
  assuming lint is green.
- **pytest**: `testpaths=tests`, strict markers/config, 60s timeout. Markers:
  `slow`, `integration`.
- Two generated artifacts drift easily — regenerate, don't hand-edit:
  `docs/openapi-snapshot.json` (`make openapi-snapshot`) and the frontend
  OpenAPI types (`make frontend-types`).

## Gotchas

- `openapi-types` and `ruff format` versions have drifted from baseline before —
  verify a diff is yours vs. a tooling regeneration before committing.
- Agents live under `agents/<name>/` (profile.jsonc, agent-core/, visuals/).
- Don't commit broad pathspecs while concurrent sessions are running in this repo.
