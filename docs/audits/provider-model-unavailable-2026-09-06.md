# Model unavailable incorrectly retried as HTTP 502

The OpenCode Zen model `deepseek-v4-flash-free` returned HTTP 400 with
“Model is unavailable”, including for an authenticated minimal request.
The Codex Responses bridge replaced every provider failure with HTTP 502,
causing repeated requests and a misleading temporary-error message.

Provider HTTP failures now carry typed status information. The bridge preserves
supported 4xx outcomes and returns bounded Chinese messages without forwarding
provider bodies, credentials or request data. Concurrent duplicate requests
receive the same status and message. Unknown and server-side errors keep their
existing retryable behavior. Codex event translation unwraps the known public
messages for the final error display.

Validation: 94 tests passed in the initial router/proxy/event run. Follow-up
coverage verified Responses error metadata and a real local Codex App Server:
an unavailable model caused exactly one provider call and no retry notification.
The Responses tests passed after correcting their fixture to include user input.
Ruff and whitespace checks passed. The running backend was started after the
code changes; backend and frontend health checks both returned HTTP 200.

The user explicitly approved switching the Eight Sleep patent-research thread
`tVzjQc51k71eLx8xYMQu1j` to `muse-spark-1.3-contributor-free`. A minimal Muse
request returned OK, the UI model selection was updated, and the original
research was continued. The app displayed a research response and a 12-step
process replay. This verifies execution recovery, not the accuracy of the
research's patent or legal conclusions.
