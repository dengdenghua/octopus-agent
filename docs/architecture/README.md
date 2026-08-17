# Architecture Docs

This folder contains the current architecture map for Octopus-Agent.

## Start here

1. `core-path.md`
2. `module-map.md`
3. `high-res-map.md`
4. `organ-tiering.md`

## Current notes

- `chat-modes.md` explains the remaining workspace modes and their boundaries.
- `blocks-commit-checklist.md` is the landed 13-commit record of the composition layer.
- `user-work-commit-plan.md` is a read-only suggested grouping of the worktree's uncommitted work.
- `blocks.md` defines the composition layer (BlockManifest + ServiceBus + lifecycle + event conventions) — the "building blocks" contract.
- Historical snapshots have moved to `../archive/`.
- The root organ `README.md` files are compatibility notes, not the primary
  source of truth.

## Source of truth

- Runtime behavior lives in `runtime/`.
- Product-facing docs live in `docs/`.
- Historical notes live in `docs/archive/`.
