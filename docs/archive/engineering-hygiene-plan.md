# Engineering Hygiene Plan

This plan covers issues that directly affect safe agent edits, rollback,
collaboration, release confidence, and long-running self-improvement.

## Current High-Risk Items

| Issue | Observation | Risk |
|---|---|---|
| Broken Git state | The repository contains `.git.broken` and no usable `.git` | No reliable diff, rollback, branch, commit, or audit trail |
| Encoding ambiguity | Windows shell output can make UTF-8 docs look like mojibake | Onboarding and automated doc checks become guesswork |
| Runtime artifacts in tree | Guarded by `.gitignore` plus repository hygiene tests | Agents get a stable source/runtime boundary |
| Frontend package-manager drift | Resolved to pnpm with a single `pnpm-lock.yaml` policy | CI and local dependency resolution stay aligned |
| Stub and real paths mixed | `stub_router.py` supplies many compatibility APIs | Product readiness can be overestimated |
| Chinese docs drift | Core Chinese content has no encoding regression guard | Chinese onboarding can silently degrade |

## P0 Remediation

1. Recover Git auditability.

   Goals:

   - restore or reinitialize `.git`;
   - make the current tree inspectable;
   - clean generated artifacts before the first clean baseline commit;
   - require future agent changes to be reviewable with diff.

   Acceptance:

   ```bash
   git status --short
   git diff --stat
   ```

2. Keep source separate from runtime data.

   Goals:

   - keep source, sample config, docs, and tests tracked;
   - keep `data/`, logs, build outputs, local workspace state, and caches ignored;
   - allow only intentional placeholders such as `agents/*/sessions/.gitkeep`.

   Acceptance:

   - `git ls-files` contains no runtime `.jsonl`, `.db`, `.sqlite`, logs, or build outputs;
   - source tree may contain session directories only via `.gitkeep`;
   - repository hygiene tests prevent regressions.

3. Guard core documentation encoding.

   Priority files:

   - `README.md`
   - `QUICKSTART.md`
   - `docs/architecture.md`
   - `docs/architecture/core-path.md`
   - `mkdocs.yml`

   Acceptance:

   - files decode as UTF-8 in git;
   - no common UTF-8 mojibake markers in core docs;
   - mkdocs navigation is readable;
   - README setup commands match the actual package manager.

4. Keep one frontend package manager.

   Goals:

   - keep `frontend/pnpm-lock.yaml` as the only frontend lockfile;
   - keep `frontend/package.json`, README, CI, and local scripts on pnpm;
   - prevent `frontend/package-lock.json` or `yarn.lock` from returning.

5. Mark stub boundaries.

   Goals:

   - stubs are allowed in development;
   - production or real-verification mode warns on or disables stubs;
   - frontend shows `_stub: true` as simulated data.

## P1 Remediation

| Item | Goal |
|---|---|
| Golden scenarios | Add one end-to-end task each for code, browser, MCP, memory, and permissions |
| OpenAPI/TS sync | Verify `docs/openapi-snapshot.json` and frontend type generation |
| Local data directory | Route runtime data through `app_paths()` instead of source directories |
| CI layering | Split minimal checks, backend unit tests, frontend typecheck, and e2e |
| Docs navigation | Link main path, evolution loop, and hygiene docs from the docs index and mkdocs nav |

## P2 Remediation

| Item | Goal |
|---|---|
| Release packaging | Keep Electron/package artifacts outside source state |
| Examples | Generate minimal examples from golden scenarios |
| Docs lint | Check broken links, encoding, and command drift |
| Dependency audit | Scan backend/frontend dependencies and licenses |

## Recommended Order

```text
Backup current tree
  -> Recover git
  -> Commit imported baseline
  -> Guard generated/runtime artifacts
  -> Guard docs encoding
  -> Normalize package manager
  -> Add golden scenarios
  -> Start product-path implementation
```

## Do Not Prioritize Yet

| Defer | Reason |
|---|---|
| Large biomimetic module rename | It creates huge unrelated diffs |
| Full frontend rewrite | Main path is not fixed yet |
| Deleting stub router | It may break current frontend paths; mark and gate first |
| Complex monorepo tooling | Restore auditability and verification first |
