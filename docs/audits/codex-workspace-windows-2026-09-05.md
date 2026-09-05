# Windows Codex workspace and provider repair — 2026-09-05

The personal-space task `tnwquwTzTuEqf3gj5PD4hm` (调研智能睡眠) originally
failed before model execution with `Codex workspace is outside the host task's
readable scope`. Live retries exposed additional startup and model-route defects.

## Corrections

1. The authenticated realtime host now grants read access to the workspace it
   resolved. Chat/research write permissions still cover their existing output
   directories only. The grant is a server-owned Python Path, cannot be supplied
   through JSON metadata, and remains subject to the parent permission ceiling.
2. Explicit full local access on Windows covers mounted drive roots, including
   workspaces on a different drive from the backend's current directory.
3. Windows Codex state paths use one domain-separated SHA-256 identity component
   instead of a deeply nested hash tree. This avoids SQLite path-length failures
   under packaged LOCALAPPDATA while retaining tenant/thread/task separation,
   private ownership markers and cleanup validation. Existing state is retained.
4. OpenCode Zen's Muse family uses the Responses transport when new versions are
   discovered. Older saved Zen plugin entries also receive the routing correction;
   similarly named models at other provider endpoints are not reclassified.
5. Referenced plugin credentials resolve inside the active request's tenant scope,
   rather than at global router registration time. Request routers do not share
   a user's credentials. Missing credentials fail before any upstream request.
6. Realtime Session metadata now contains both the validated tenant and owner,
   so downstream credential lookup receives a complete trusted principal.
7. Proxy diagnostics record exception class, HTTP status when available, and code
   location. They never log exception bodies, request payloads or credentials.

## Verification

- Workspace/execution/security suites: 85 passing tests.
- Codex startup/security suite: 73 passing tests and 3 POSIX-only skips; the one
  Windows-specific root assertion was corrected and passed separately.
- Model-provider and Responses adapter tests: 12 passed, covering discovered
  model routing, request-bound credentials, streaming, restart, and tenant isolation.
- Proxy tests: 14 passed, including sanitized failures and real local tool loops.
- Custom-model registration and startup tests: 8 passed.
- Final combined realtime/provider/proxy run: 39 passed.
- Ruff checks, formatting checks and whitespace validation passed for edited code.
- A broader app-config run encountered a Windows Python access violation;
  the affected registration/startup tests were then run separately and passed.

Live verification succeeded in the original thread: the selected
`muse-spark-1.3-contributor-free` completed six tool operations and returned the
research response. The UI shows “处理已结束” and “先前尝试失败，后续已恢复”.
The original task, selected model and error history are preserved.

The Responses endpoint was also checked against the provider's
[official Zen endpoint documentation](https://opencode.ai/docs/zen/#endpoints)
and a minimal authenticated request.
