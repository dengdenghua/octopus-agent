# Octopus-Agent v0.2.0 Beta

Octopus-Agent is an Agent OS. It runs agents with planning, tool execution,
memory, reflection, safety governance, browser/workspace access, and
self-improvement loops.

The IDE, browser, desktop app, and extension are product surfaces. The core
product is the Python runtime in `runtime/`.

Start here:

- [10-minute golden path](docs/GOLDEN_PATH.md)
- [quick start](QUICKSTART.md)
- [concept map](docs/CONCEPTS.md)
- [root layout](ROOT_LAYOUT.md)
- [architecture](docs/guide/architecture.md)

Chinese readers: [README.md](README.md)

## Quick Start

```bash
# Minimal deterministic backend demo. No LLM key required.
pip install -e ".[minimal]"
python -m runtime bugfix-demo

# Development setup with tests, FastAPI UI, and web skills.
pip install -e ".[dev,serve,web]"
python -m runtime quickstart --non-interactive
python -m runtime status
python -m runtime ui --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Frontend development:

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

Common checks:

```bash
python -m pytest -q
python -m ruff check runtime tests tools
cd frontend && pnpm typecheck
```

## What It Is

Octopus-Agent turns a user request into an observable, governed agent execution:

```text
user request
  -> Siphon HTTP/SSE/API boundary
  -> SpinalCord reflex/rule shortcut
  -> Cerebrum planning or ReAct loop
  -> Ganglia TaskGraph execution
  -> Beak tool execution
  -> Immunity / Budget / Journal governance
  -> streamed frontend updates and persisted events
```

It is not just a chat wrapper or a thin SDK integration. The runtime is designed
to make planning, execution, permissions, cost, memory, audit, recovery, and
evolution explicit engineering surfaces.

## Repository Layout

Primary code:

| Path | Purpose |
|---|---|
| `runtime/` | Python Agent OS runtime: planning, execution, memory, safety, UI APIs |
| `frontend/` | React/Vite/Electron workspace |
| `tests/` | Backend unit and integration tests |

Product surfaces:

| Path | Purpose |
|---|---|
| `agents/` | Agent definitions, presets, roles, and metadata |
| `skills/` | Callable skills and skill metadata |
| `protocols/` | MCP, A2A, OpenAI-compatible, and related protocol assets |
| `prompts/` | Prompt templates, variants, and evaluation assets |
| `tools/` | Developer utilities |
| `scripts/` | Project automation |

Docs and deployment:

| Path | Purpose |
|---|---|
| `docs/` | Architecture, ADRs, onboarding, OpenAPI snapshots, references |
| `demos/` | Small runnable examples |
| `benchmarks/` | Reproducible benchmarks and reports |
| `deploy/` | Deployment manifests |
| `Dockerfile` / `docker-compose*.yml` | Container entry points |

See [ROOT_LAYOUT.md](ROOT_LAYOUT.md) for the root hygiene rules.

## Runtime Map

`runtime/` is organized into seven semantic groups:

| Group | Responsibility |
|---|---|
| `runtime/core/` | Planner, task graph runtime, reflex router, heartbeat/coordinator |
| `runtime/execution/` | Agents, arms, tool executor, skills, parallel/swarm execution |
| `runtime/sensing/` | HTTP/SSE/API, model routers, browser, sandbox/mantle |
| `runtime/memory/` | Journal, checkpoints, knowledge graph, thread memory |
| `runtime/safety/` | Immunity, budget breakers, regeneration, camouflage, constitution |
| `runtime/adapters/` | MCP, channels, scheduler, instrumentation, integrations |
| `runtime/platform/` | Config, shared models, UI factory, i18n, setup/doctor |

The biomimetic names are design vocabulary, not hard numeric constraints. See
[docs/architecture/module-map.md](docs/architecture/module-map.md).

## CLI

| Command | Purpose |
|---|---|
| `python -m runtime status` | Show local capabilities and optional integrations |
| `python -m runtime demo` | Built-in list/read/count end-to-end demo |
| `python -m runtime bugfix-demo` | Deterministic bugfix demo: read files, run tests, edit code, commit |
| `python -m runtime run "<goal>"` | Run a custom goal |
| `python -m runtime reflect --from-journal <path>` | Run reflection producers from a journal |
| `python -m runtime quickstart --non-interactive` | Generate a local static config and run doctor checks |
| `python -m runtime ui --port 8000` | Start the FastAPI dashboard |
| `python -m runtime serve --config config.local.yaml --port 8000` | Long-running service entry point |

Editable installs also provide:

```bash
octopus-agent status
octopus-agent bugfix-demo
```

## Configuration

Useful files:

- `config.example.yaml`: commit-safe example configuration
- `config.local.yaml`: local real provider configuration; do not commit secrets
- `.env.example`: environment variable example
- `.env`: local secrets; do not commit

Typical service startup:

```bash
python -m runtime quickstart --non-interactive
python -m runtime quickstart --non-interactive --serve
```

## Frontend And Desktop

The frontend lives in `frontend/` and uses React, Vite, TanStack Query, Radix UI,
CodeMirror, and Electron.

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
pnpm typecheck
pnpm test
pnpm electron:dev
```

Production builds:

```bash
cd frontend
pnpm build
pnpm electron:build:win
```

## Quality Gates

Backend:

```bash
python -m pytest -q
python -m ruff check runtime tests tools
python -m ruff format --check runtime tests tools
```

Frontend:

```bash
cd frontend
pnpm typecheck
pnpm test
pnpm build
```

OpenAPI / TypeScript contract:

```bash
make openapi-snapshot
make frontend-types
```

## Reflection closure

`python -m runtime reflect --from-journal <path>` drives the reflection
producers over a journal file: it clusters traces, extracts durable
lessons, and proposes skill-catalog tweaks. The `runtime/safety/regeneration/`
scheduler runs the same loop in the background when a stack is live. This
closes the execute → reflect → regenerate loop without requiring a
separate controller.

Model routing is provider-agnostic — OpenAI, Anthropic, and any
OpenAI-compatible endpoint plug in through `runtime/sensing/eyes/`. See
`runtime/platform/models/` for the portable types.

## Docker

```bash
cp .env.example .env
cp config.example.yaml config.yaml
docker compose up -d
docker compose logs -f octopus-agent
```

Default service:

```text
http://127.0.0.1:8000
```

## License

Apache-2.0. See [LICENSE](LICENSE).
