"""Root hygiene: prevent foreign Electron-app scaffolds from invading.

On 2026-06-05 we found 5 ByteDance Coze-related files (bootstrap.js,
index.html, main.js, etc.) in repo root that had no history and no
obvious origin. They looked like an accidental npm init or IDE scaffold.

This linter enforces a repo-root whitelist: only files that belong to
the Octopus project are allowed in the top level. Anything else is
presumed to be accidental pollution and must either:
  1. Be added to the whitelist (with an explanatory comment), or
  2. Be removed.

Run::

    python tools/lint/root_hygiene_check.py            # report violations
    python tools/lint/root_hygiene_check.py --strict   # exit 1 on violations
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ── Root-level whitelist ───────────────────────────────────────────
#
# Only these names are allowed at repo root. Keep alphabetized.
# Add entries with a comment explaining why they're needed.
#
# Rationale: uncontrolled root growth (bootstrap.js, main.js,
# package.json clones from random IDE scaffolds) is a symptom of
# accidentally running `npm init` or dropping in a different project's
# boilerplate. This list forces conscious decisions.

ALLOWED_ROOT_NAMES = frozenset({
    ".claude",               # Claude Code session state
    ".codex",                # Codex CLI session state
    ".coverage",             # pytest-cov coverage data
    ".dockerignore",         # Docker build ignore patterns
    ".editorconfig",         # Editor config (indent style, etc.)
    ".env",                  # Local env vars (gitignored)
    ".env.example",          # Example env template
    ".git",                  # git metadata
    ".gitattributes",        # git attributes (line endings, merge drivers)
    ".github",               # GitHub Actions workflows + issue templates
    ".gitignore",            # git ignore rules
    ".octopus",              # Octopus CLI state
    ".playwright-cli",       # Playwright cache (frontend e2e tests)
    ".pre-commit-config.yaml",  # pre-commit hooks
    ".python-version",       # pyenv / asdf Python version pin
    ".qoder",                # Qoder CLI session state
    ".ruff_cache",           # Ruff linter cache (ephemeral but OK)
    "agents",                # Agent profile definitions
    "benchmarks",            # Performance benchmarks
    "biome.json",            # Biome formatter config (frontend)
    "build",                 # Build artifacts (ephemeral)
    "CHANGELOG.md",          # Project changelog
    "config.example.yaml",   # Example runtime config
    "config.local.yaml",     # Local runtime config (gitignored)
    "CONTRIBUTING.md",       # Contributor guide
    "demos",                 # Demo scripts / videos
    "deploy",                # Deployment configs
    "dist",                  # Python build output (ephemeral)
    "docker-compose.yaml",   # Docker Compose orchestration
    "docker-compose.yml",    # Docker Compose (alternate extension)
    "docker-compose.full.yml",  # Full-stack Docker Compose
    "Dockerfile",            # Container build spec
    "Dockerfile.dev",        # Dev container build spec
    "docs",                  # Documentation markdown files
    "evidence",              # Evidence / test artifacts
    "examples",              # Standalone runnable examples (PoCs)
    "experiments",           # Experimental code / prototypes
    "extensions",            # Browser extension / IDE extension code
    "extras",                # Extra resources / assets
    "frontend",              # React/TS frontend
    "htmlcov",               # Coverage HTML report (gitignored)
    "LICENSE",               # Project license
    "local-test.db",         # SQLite test DB (gitignored)
    "main.py",               # Python entrypoint for production runtime
    "Makefile",              # Make build automation
    "MANIFEST.in",           # Python wheel manifest
    "memory",                # Long-term memory / journal storage
    "meta_skills",           # Meta-skills for agent self-improvement
    "mkdocs.yml",            # MkDocs documentation config
    "package-lock.json",     # npm lockfile (frontend)
    "package.json",          # npm manifest (frontend)
    "packaging",             # Packaging scripts / specs
    "permissions.example.json",  # Example permissions config
    "playwright-report",     # Playwright test report (ephemeral)
    "postcss.config.cjs",    # PostCSS for frontend
    "prompts",               # Prompt templates / library
    "protocols",             # Protocol spec markdown
    "pyproject.toml",        # Python build config + ruff + pytest
    "pyrightconfig.json",    # Pyright type checker config
    "pytest.ini",            # Pytest config (can coexist with pyproject.toml)
    "QUICKSTART.md",         # Quickstart guide
    "README.en.md",          # English README
    "README.md",             # Project README
    "ROOT_LAYOUT.md",        # Root directory structure doc
    "runtime",               # Python runtime src
    "scripts",               # Dev / ops scripts
    "skills",                # Skill definitions
    "SOUL.md",               # Project soul / identity doc
    "tailwind.config.ts",    # Tailwind CSS config (frontend)
    "teams",                 # Team collaboration configs / state
    "test-results",          # Playwright test results (ephemeral)
    "tests",                 # Pytest test suite
    "tools",                 # Lint + dev scripts
    "tsconfig.json",         # TypeScript config (frontend)
    "tsconfig.node.json",    # TypeScript Node config (frontend)
    "uv.lock",               # uv package manager lockfile
    "vite.config.mts",       # Vite bundler config (frontend)
})

# Subdirs in root that are ephemeral / gitignored but expected.
# We don't check their contents, just allow their presence.
ALLOWED_EPHEMERAL_DIRS = frozenset({
    ".claude",
    ".codex-artifacts",      # Codex artifacts cache
    ".codex-logs",           # Codex logs
    ".git",
    ".git.broken",           # Transient git state from repair ops
    ".ruff_cache",
    ".venv",                 # Python virtualenv (gitignored)
    "_external",             # External dependencies / vendored code
    "build",
    "data",                  # Runtime data dir (gitignored)
    "dist",
    "htmlcov",
    "logs",                  # Application logs
    "memory",
    "node_modules",          # npm dependencies (gitignored)
    "output",                # CLI output / artifacts
    "playwright-report",
    "test-results",
    "tmp",                   # Temporary test fixtures
    "ura-artifacts",         # URA artifact cache
    "__pycache__",           # Python bytecode cache
    ".pytest_cache",         # Pytest cache
    "octopus_agent.egg-info",  # Python build metadata
})

# Filename suffixes that are always ephemeral and may appear at root.
# Use sparingly — adding a suffix here weakens the whitelist.
ALLOWED_SUFFIXES = (
    ".log",                  # Backend / dev logs (gitignored)
)

# Filename prefixes (with suffix) for time-stamped backup directories.
# These appear when scripts produce dated snapshots.
ALLOWED_NAME_PATTERNS = (
    "skills_backup_",        # Skill backup dirs from migration scripts
)


def scan_root() -> list[Path]:
    """Return paths in repo root that are NOT on the whitelist."""
    violations: list[Path] = []
    for item in REPO_ROOT.iterdir():
        name = item.name
        if name in ALLOWED_ROOT_NAMES:
            continue
        # Ephemeral dirs are allowed but we don't recurse into them.
        if item.is_dir() and name in ALLOWED_EPHEMERAL_DIRS:
            continue
        # Suffix-based ephemeral (e.g., *.log).
        if any(name.endswith(suffix) for suffix in ALLOWED_SUFFIXES):
            continue
        # Name pattern match (e.g., skills_backup_20260601_...).
        if any(name.startswith(prefix) for prefix in ALLOWED_NAME_PATTERNS):
            continue
        violations.append(item)
    return sorted(violations)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="exit 1 on violations")
    args = parser.parse_args()

    violations = scan_root()
    if not violations:
        print("OK · repo root clean (all entries whitelisted).")
        return 0

    print(f"{len(violations)} foreign file(s) in repo root:")
    for path in violations:
        rel = path.relative_to(REPO_ROOT)
        print(f"  - {rel}")
    print(
        "\nFix one of:\n"
        "  1. Remove the file (if accidental / scaffold pollution).\n"
        "  2. Add it to ALLOWED_ROOT_NAMES in tools/lint/root_hygiene_check.py\n"
        "     with a comment explaining why it's needed.\n"
        "\nContext: on 2026-06-05 we found foreign Electron-app scaffolds "
        "(bootstrap.js,\nindex.html, main.js) with no history. This linter "
        "prevents a recurrence."
    )

    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
