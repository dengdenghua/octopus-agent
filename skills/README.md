# Domain Skill Packs (SKILL.md templates)

The `skills/public/` directory contains **file-backed SKILL.md packages** — domain-specific prompt templates and execution scripts. These are discovered at runtime by the skill loader and are **not** shipped in the Python wheel.

## Why keep them outside the wheel?

Before this split, `runtime/execution/all_skills/` contained 175 SKILL.md directories, bloating the wheel from ~3.5 MB to ~24 MB. File-backed skill packs (markdown prompts + reference docs + optional Python scripts) are better distributed via:

1. **Git clone** (developer use — they're already here)
2. **Separate skill pack releases** (production use — download only what you need)
3. **Remote MCP servers** (the `/api/agent-market/` endpoints already fetch from remotes)

The Python wheel now contains only:
- `runtime/execution/all_skills/__init__.py` (skill catalog and loader)
- `runtime/execution/all_skills/*.json` (config)
- Python `scripts/*.py` helpers (packaged via setuptools `runtime*`)

## How discovery works

At import time, `runtime.execution.all_skills._add_file_backed_skill_catalog()` iterates:

1. `runtime/execution/all_skills/<name>/SKILL.md` (in wheel — now empty after MANIFEST.in change)
2. `project_root() / "skills" / "public"` (outside wheel — this directory)

So in **development** (git clone), both paths are populated and the loader sees 175+ skills. In **production** (pip install), only `skills/public/` matters.

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
# Old (bloated wheel)
recursive-include runtime/execution/all_skills *

# New (lean wheel)
include runtime/execution/all_skills/__init__.py
include runtime/execution/all_skills/*.json
```

This keeps the wheel <5 MB while preserving full dev-mode functionality (all 175 skills still load from the git clone).
