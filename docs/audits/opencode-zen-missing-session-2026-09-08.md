# OpenCode Zen inference rejected with MissingSessionID

## Confirmed result

On 2026-09-08, minimal authenticated requests sent directly to the configured
`https://opencode.ai/zen/v1` endpoint reproduced the application's failure,
without the Echo frontend, agent prompt, tools, or Codex execution bridge.
The existing credential was resolved from the affected local user's encrypted
connector store in memory. No credential was printed or copied into this report.

| Request | Result |
| --- | --- |
| GET /models | HTTP 200; includes both tested models |
| POST /chat/completions, big-pickle, short text only | HTTP 400, error.type = MissingSessionID |
| POST /responses, muse-spark-1.3-contributor-free, short text only | HTTP 400, error.type = MissingSessionID |

Both inference errors contain:
`Error from provider (Console): OpenCode's free tier can only be used in OpenCode`.

The immediate failure is the upstream free-tier session validation. It is not
explained by one unavailable model, prompt size, tool schema, frontend rendering,
or the Codex bridge. A successful model-list request does not establish inference
authorization or even prove that the list endpoint validates the key.

## Local task timeline

Thread: `t5m4_s_I_8Q3bpl0dhEnjU`. Times below are Asia/Shanghai, September 8.

| Time | Actual selected model | Result |
| --- | --- | --- |
| 14:01, 14:02 | big-pickle | Local router: current user has not connected model plugin |
| 14:03:26 | big-pickle | Upstream free-tier-only error |
| 14:03:43 | muse-spark-1.2-contributor-free | Responses error rendered as generic HTTP 400 |
| 14:09:25 | mimo-v2.5-free | Upstream free-tier-only error |

Selections were decoded with the repository's `custom_model_selection_id` function,
not inferred from the currently displayed model picker. The task used the native
Octopus engine. The first two credential failures are distinct from the later
inference rejection; current credential resolution succeeds.

## Integration findings

- `runtime/platform/models/model_provider_plugin.py` validates the connection
  through GET /models and intersects the catalog with configured/discovered free
  model IDs. It does not perform an inference availability check.
- The configured OpenCode entry has no `default_headers`. The Chat Completions
  router builds ordinary JSON, User-Agent, and Bearer authorization headers;
  the Responses router likewise has no Zen-specific session metadata here.
- OpenCode's public Zen handler reads `x-opencode-session`, request, client, and
  project headers and forwards relevant metadata to newer inference providers.
  It also prefixes upstream error messages with the provider display name,
  consistent with the observed `(Console)` response.
- The public handler does not itself expose the exact downstream
  `MissingSessionID` enforcement branch. No header-spoofing experiment was run;
  this investigation does not establish that adding one header is a supported
  or sufficient integration fix.

## Earlier success and limits

`docs/audits/provider-model-unavailable-2026-09-06.md` records a successful minimal
Muse 1.3 request and continuation of the Eight Sleep task. Its event log records
a completed turn at 2026-09-06 00:34:27 +08:00. The same Muse version now fails
the direct probe above. This supports a change in upstream handling since that
successful run, but the exact deployment time and policy change are unverified.

The earlier advice to reconnect or switch to Muse was insufficient: both models
remain listed, and Muse 1.3 currently receives the same session rejection.
The September 6 error-display changes explain differences in displayed messages;
they cannot explain a failure reproduced directly against the upstream endpoint.

## Follow-up direction

Separate catalog discovery, credential state, and inference readiness in the
adapter UI. Preserve the bounded `MissingSessionID` classification so the user
gets an actionable explanation. Confirm the provider's supported third-party
integration before changing session metadata; otherwise use an authorized model
route. No model settings, credentials, running task, or runtime source were
changed by this investigation.

## Sources

- Local event log: `.codex-run/octopus/data/threads/t5m4_s_I_8Q3bpl0dhEnjU.jsonl`
- Local backend log: `.codex-run/backend.err.log`
- Local connection configuration: `.codex-run/octopus/data/custom_models.json`
- Public source: https://github.com/anomalyco/opencode/blob/dev/packages/console/app/src/routes/zen/util/handler.ts
- Provider documentation: https://opencode.ai/docs/zen/

Public sources were inspected on 2026-09-08 and may change independently of the
deployed service.

## User-requested session-header comparison

A subsequent user-requested test compared three minimal `big-pickle` requests
using the same stored credential and prompt. A fresh Echo diagnostic session
identifier was reused across the two header-bearing cases.

| Case | Result |
| --- | --- |
| No session header | HTTP 400, MissingSessionID |
| `x-opencode-session` only | HTTP 429, FreeUsageLimitError |
| Same session plus Echo request ID, `x-opencode-client: echo`, and `User-Agent: Echo/diagnostic` | HTTP 429, FreeUsageLimitError |

This demonstrates a change from session rejection to a free-usage limiter response.
No successful inference was obtained. It does not prove that all later validation
would pass, nor whether the limit is scoped to the account, IP, model, or another
bucket. No further requests were made after the comparison, no alternate identity
was used to evade the limit, and the application configuration remains unchanged.
The earlier statement that no header experiment was run describes the initial
investigation; this section records the later explicitly requested experiment.

## Official CLI verification: successful

In a later recovery experiment on September 8, the official Windows x64 portable
OpenCode v1.18.29 release was downloaded into `.codex-run/opencode-diagnostic`.
Its archive SHA-256 matched the digest published by GitHub Releases:
`b32618aa3d1415f6e4f473aec248edef25759203fb707d7d968359d86d4a35ee`.

The executable ran in a diagnostic workspace with isolated XDG directories,
external plugins disabled, all tool permissions denied, and sharing disabled.
The same affected user's existing Zen credential was supplied in the child
process environment, referenced by inline provider configuration, without an
auth-login operation or copying it into the report. Both the main and small
model were explicitly set to `opencode/big-pickle`.

Command shape: `opencode run --pure --format json --model opencode/big-pickle`.
Prompt: `Reply with OK only. Do not use any tools.`

Result:

- CLI exit code: 0.
- Text event: `OK`.
- Final step reason: `stop`.
- Reported tokens: 1,900 input, 22 output, 1,922 total.
- Reported cost: 0.
- Captured stderr: empty.
- Credential-redacted evidence: `.codex-run/opencode-diagnostic/cli-result.json`.

This proves that the current account and model can complete a real request via
the official CLI. It does not establish which precise difference from the
earlier header-only calls caused the earlier 429: time, provider routing, client
metadata, or other factors were not isolated. No claim of unlimited availability
is made. The existing Echo model adapter and NAS conversation were not modified
or recovered by this isolated successful test.

## HTTP service verification: successful

A later check of the new task `tlgn2dAlgt17A9RKwos-td` confirmed a Codex turn
failed with the public provider HTTP 400 message. A direct minimal `big-pickle`
call using explicitly Echo-labelled session metadata still returned HTTP 429,
`FreeUsageLimitError`, without a Retry-After header.

The official v1.18.29 executable was then started with `opencode serve` on a
temporary loopback port protected by a random HTTP Basic password. It used the
same Zen account and existing diagnostic configuration/data directories as the
successful CLI experiment. No new account or external client identity was used.

Via the local HTTP API, GET /global/health returned 200; POST /session created a
diagnostic session; POST /session/{id}/message with explicit
`providerID=opencode`, `modelID=big-pickle` returned HTTP 200, text `OK`, no error,
finish `stop`, and reported cost 0 (1,899 input / 21 output tokens).
The temporary server was stopped after the test. Redacted results are saved in
`.codex-run/opencode-diagnostic/serve-result.json` and `direct-recheck.json`.

This verifies the official HTTP service as a working integration path in this
environment. It does not establish that the existing native/Codex model-proxy
path is repaired, or that a plain model-API wrapper around the full agent engine
would preserve the same execution semantics. Echo has not yet been connected
to the OpenCode service.

## Request comparison with the official v1.18.29 engine

The official CLI was configured to send its model request through a temporary
loopback diagnostic relay. The relay verified that Authorization matched the
affected account's saved Zen credential in memory, then forwarded the request
with Python httpx to the canonical Zen endpoint. Only selected non-secret
metadata was retained; the credential and full prompt/body were not recorded.

The official request, forwarded without changing its client metadata, returned
HTTP 200 and `OK`. Observed characteristics:

- Same saved credential as Echo: confirmed by an in-memory equality check.
- Endpoint: `/v1/chat/completions`; model: `big-pickle`.
- Streaming enabled; zero advertised tools in this tool-denied diagnostic.
- Headers include User-Agent plus `x-opencode-session`, `x-opencode-request`,
  `x-opencode-project`, and `x-opencode-client`.
- No additional signature header, cookie, or second authorization field was
  observed on this particular request.
- Body fields: model, max_tokens, messages, stream, stream_options.
- The messages included an 8,900-character system context and a 43-character
  user prompt. Full message content was not captured in the report.

An additional official-engine request was forwarded while changing only the
two client-identification header values to explicitly identify Echo
(`x-opencode-client: echo`, `User-Agent: Echo/diagnostic`). Its genuine engine
session/project/request metadata and body were preserved. This returned HTTP
429, FreeUsageLimitError, and no answer. Further retries were stopped.

These results rule out a different saved key and show that a CLI-specific TLS
stack or a direct socket from the binary is unnecessary for the successful
request. They make client-identification-dependent handling plausible. However,
the requests were sequential, not identical immutable samples, and the service's
quota/routing state is not observable. This is not proof that either header alone
is decisive, that 429 always means client rejection, or that spoofing those
headers will restore general API access. No production spoofing patch was made.

Evidence:
- `.codex-run/opencode-diagnostic/official-request-metadata.json`
- `.codex-run/opencode-diagnostic/echo-labelled-official-request.json`
- Version-matched request construction:
  https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/session/llm/request.ts#L177
- Version-matched identifier implementation:
  https://github.com/anomalyco/opencode/blob/v1.18.29/packages/opencode/src/id/id.ts

The public ID implementation constructs prefixed identifiers locally; the
observed client fields are not themselves proof of a cryptographic attestation.
Downstream enforcement is still not established from the public gateway source.
