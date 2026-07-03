# permission-review-fixture

A deliberately minimal, committed plugin whose manifest declares an MCP
server **without** an explicit `permissions` list. Codex-plugin discovery
therefore infers `mcp:execute:review_required`, which feeds
`build_plugin_permission_rule_drafts` exactly one draft.

Why this exists: `octopus.permission_sandbox_quality.v1` requires at least
one *verified* plugin permission rule draft. Real marketplace plugins live
only on developer machines (untracked), so a fresh checkout — CI included —
had zero drafts and the readiness gate failed there while passing locally.
This fixture keeps the certification honest and reproducible everywhere.

The declared server command is `true` (a no-op); Octopus never auto-starts
plugin MCP servers, so the fixture is inert at runtime.
