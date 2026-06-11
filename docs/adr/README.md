# Architecture Decision Records

This directory holds **ADRs** — short docs that capture *why* a
significant architectural decision was made, not just *what* the
code does. Code shows the "what". ADRs preserve the "why", including
the alternatives that were considered and rejected.

## When to write one

Write an ADR when a decision meets any of:

- It took more than one round of rework to land (the decision has
  scar tissue).
- It's load-bearing across many files (rename / invariant / injection
  pattern).
- A reasonable person could pick the opposite default and not know
  which is right without context.
- We know the first version is wrong and want the next contributor to
  know what "wrong" meant without re-deriving.

Don't write one for local refactors, style choices, or anything that
fits in a single-file docstring.

## Format

One file per decision, named `NNN-kebab-case-title.md`. Status values:

- **Proposed** — open for discussion
- **Accepted** — current practice
- **Superseded by ADR-NNN** — kept for history; do not follow
- **Rejected** — captured so we don't re-propose it

Template:

```markdown
# ADR-NNN · Title

Status: Accepted | Date: YYYY-MM-DD

## Context

What's the situation? What forces are at play?

## Decision

What we're doing.

## Alternatives considered

What else we looked at and why we didn't pick it.

## Consequences

What this costs us / what breaks / what we now can't do easily.
```

## Index

- [ADR-001 · Bionic naming + dual-track contracts](001-bionic-naming.md)
- [ADR-002 · Mode-gated write scope](002-mode-gated-scope.md)
- [ADR-003 · Session object replaces scattered ContextVars](003-session-object.md)
- [ADR-004 · OpenAPI → TypeScript type generation pipeline](004-openapi-ts-codegen.md)
- [ADR-005 · Agent capability flags](005-agent-capabilities.md)
- [ADR-006 · Lifecycle hook system](006-lifecycle-hooks.md)
- [ADR-007 · MCP server trust store](007-mcp-trust-store.md)
- [ADR-008 · Constitution enforcement profiles](008-constitution-profiles.md)
