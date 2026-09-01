# OpenCode Zen model adapter

Octopus connects to OpenCode Zen as a model gateway, not as a local CLI agent.
The adapter uses Zen's OpenAI-compatible API at
`https://opencode.ai/zen/v1`; it never installs, launches, or scans for an
`opencode` executable.

## Lifecycle

1. Install **OpenCode Zen 模型适配器** from the plugin market.
2. Open the official Zen dashboard, create an API key, and paste it into the
   plugin connection dialog.
3. Octopus validates the key against Zen's `/models` endpoint, keeps only the
   free model ids declared by the adapter that are currently available, and
   saves the key in the encrypted connector credential store.
4. A secret-free `opencode-zen` entry is hot-registered in the normal model
   dispatcher. Streaming, tool calls, context budgeting, memory, approvals,
   and conversation state continue to be owned by Octopus.
5. Disabling, disconnecting, or uninstalling the plugin removes its live model
   routes. Disconnecting and uninstalling also remove the stored credential.

The API key is never written to `custom_models.json` or returned to the
browser. That file contains only an opaque connector credential reference.

## Free-model and privacy boundary

The checked-in free list is reconciled with the models returned for the user's
account at connection time. Kimi models are not treated as free. Some Zen free
endpoints may log requests or use submitted data for service/model improvement;
the connection dialog shows the provider-specific privacy warning before the
key is saved. Do not route secrets or confidential source code through a free
endpoint whose data policy is unsuitable for the workspace.
