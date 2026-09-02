# Domain Skill Packs (SKILL.md templates)

The `skills/public/` directory is the writable, registry-managed prompt-skill
catalog. A clean checkout deliberately tracks only its metadata plus the root
`skills.lock.json`; startup materializes missing locked skills from the
registry.

The Python wheel also ships `runtime/execution/all_skills/` as a deterministic
offline fallback. This fallback is intentional: a registry outage, an
unwritable resource directory, or an empty `skills/public/` must never leave a
clean wheel or container with zero prompt/market skills.

## Distribution model

Prompt skills have two distribution tiers:

1. **Local external catalog** — `skills.lock.json` names the desired registry
   skills. In local development, startup may sync missing entries into
   `/app/resources/skills/public`. The current slug-only lock is not a signed,
   content-addressed release lock and is therefore never trusted by shared,
   commercial, server, or production deployments.
2. **Bundled fallback catalog** — `runtime/execution/all_skills/` is package
   data inside the wheel and works without the repository, current working
   directory, or network.

Registry-managed skill directories under `skills/public/*/` remain ignored by
git and the Docker build context. Do not rely on a developer machine's
materialized cache when validating a release; build from a clean git archive.

## How discovery works

At runtime, `runtime.execution.all_skills.register_all()` delegates prompt
distribution to `register_prompt_market_skills()`, which:

In local mode it reads `skills.lock.json`, performs a bounded best-effort sync,
registers usable external entries, and fills missing names from the bundled
fallback. In `shared`, `commercial`, `server`, and `production` modes it does
not read or refresh mutable external skills at all: only the catalog embedded
in the wheel/image is registered, and startup fails closed if that catalog is
missing or empty. Production prompt changes therefore require a new reviewed
and signed release artifact.

Bootstrap exceptions and per-skill sync failures are logged. A failed sync is
therefore visible while the bundled fallback keeps the runtime usable.

## Adding a new skill pack

```bash
cd skills/public
mkdir my-new-skill
cat > my-new-skill/SKILL.md <<'EOF'
---
name: my-new-skill
description: Brief one-liner
group: market
aliases: [alt-name]
---

# Skill Prompt

{user_input}
EOF
```

The loader auto-discovers it on next runtime startup. No `__init__.py` edit needed.

## Skill pack structure

```
skills/public/
├── my-skill/
│   ├── SKILL.md           # Required: frontmatter + prompt template
│   ├── README.md          # Optional: user-facing docs
│   ├── _meta.json         # Optional: version / author / changelog
│   ├── references/        # Optional: markdown reference materials
│   │   └── api-docs.md
│   ├── scripts/           # Optional: Python helpers (entry points)
│   │   └── process.py
│   └── requirements.txt   # Optional: extra pip deps for this skill
```

Only `SKILL.md` is required. The rest is opt-in.

## MANIFEST.in strategy

```
# Required deterministic fallback
recursive-include runtime/execution/all_skills *
```

The wheel is intentionally larger than a code-only build because the fallback
catalog is part of the runtime availability contract. Packaging regression
tests build from tracked files and assert that representative `SKILL.md`
resources are present in the wheel.
