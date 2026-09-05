# Local CLI partners (removed)

Octopus no longer scans the machine for Claude Code, Codex CLI, Trae,
CodeBuddy, Kimi, Qoder, or OpenCode executables and no longer creates Agent
cards from whatever happens to be present in `PATH`.

The previous discovery model mixed three different concerns—account login,
model access, and Agent execution—and produced misleading “connected” states
when a desktop launcher existed but a reliable headless engine did not. It
also made startup behavior depend on unrelated software installed on the host.

## Current execution choices

- **Kane / Coder** uses the built-in Codex App Server integration. Octopus
  owns the Agent identity, tools, memory, approvals, task lifecycle, and audit
  trail; Codex is the inner coding engine.
- **OpenCode Zen** is available only through the explicitly installed
  [OpenCode Zen model adapter](opencode-zen-model-adapter.md). It calls Zen's
  API and does not install, launch, or detect the OpenCode CLI.
- A future third-party CLI integration must arrive as an explicitly installed
  and permission-reviewed plugin with a declarative invocation contract. Bare
  executable presence is never enough to activate one.

## Compatibility boundary

Some low-level declarative argument-expansion code remains so reviewed plugins
can provide their own adapter without shell interpolation. There are no
built-in LocalPartner specifications, no automatic registration, and no
hard-coded OpenCode fallback. If a plugin does not provide an invocation
template, the bridge fails closed.

Existing project files may still contain a legacy `backend: codex-cli` (or
another removed CLI id). The value remains parseable so old configuration can
be diagnosed, but dispatch returns a structured unsupported-backend error; it
does not silently switch engines.
