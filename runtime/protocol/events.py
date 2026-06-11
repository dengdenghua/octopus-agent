"""Method names — the verbs of the realtime protocol.

Centralizing these as a closed set avoids string typos and makes the
contract grep-friendly. Adding a method means adding a constant here
*and* a handler/emitter elsewhere; one without the other is a bug.
"""

from __future__ import annotations

from enum import StrEnum


class ClientMethod(StrEnum):
    """Methods clients invoke on the server.

    Each value is the JSON-RPC ``method`` string sent over the wire.
    """

    # Thread lifecycle
    THREAD_START = "thread/start"
    THREAD_RESUME = "thread/resume"
    THREAD_READ = "thread/read"
    THREAD_LIST = "thread/list"
    THREAD_ARCHIVE = "thread/archive"

    # Turn control
    TURN_START = "turn/start"
    TURN_STEER = "turn/steer"
    TURN_INTERRUPT = "turn/interrupt"

    # Apply-patch hunk-level decisions (client-initiated accept/reject
    # on a single hunk after the FileChange item has completed).
    FILE_CHANGE_HUNK_DECIDE = "item/fileChange/hunkDecide"

    # Skills / models / config
    SKILLS_LIST = "skills/list"
    MODEL_LIST = "model/list"
    CONFIG_READ = "config/read"

    # MCP integration
    MCP_SERVER_LIST = "mcpServer/list"
    MCP_TOOL_CALL = "mcpServer/tool/call"


class ServerMethod(StrEnum):
    """Methods the server pushes to the client.

    Notifications are stateless event broadcasts. Requests demand a
    client-side reply (used for human-in-the-loop checks).
    """

    # ── Notifications (no reply expected) ────────────────────

    # Thread lifecycle
    THREAD_STARTED = "thread/started"
    THREAD_STATUS_CHANGED = "thread/status/changed"
    THREAD_TOKEN_USAGE_UPDATED = "thread/tokenUsage/updated"

    # Turn lifecycle
    TURN_STARTED = "turn/started"
    TURN_COMPLETED = "turn/completed"
    # Cancellation: the active turn was interrupted (user-initiated or
    # safety-triggered). Reducer handles this to stop the current
    # streaming spinner and mark the turn as cancelled.
    TURN_INTERRUPTED = "turn/interrupted"
    TURN_DIFF_UPDATED = "turn/diff/updated"
    # ``TURN_PLAN_UPDATED`` is reserved but not currently emitted —
    # plan state is derived client-side from ``todo_write`` tool-use
    # events. Wire emission together with ``ITEM_PLAN_DELTA`` if /
    # when the agent's plan needs to live as a first-class
    # streaming item rather than being inferred from tool input.
    TURN_PLAN_UPDATED = "turn/plan/updated"
    # Versioned current-frame payload for the right-side workbench. This
    # keeps realtime and replay rendering on one source of truth instead
    # of rebuilding "current state" from the full historical item stack.
    WORKBENCH_SNAPSHOT = "workbench/snapshot"
    # Lightweight keepalive for long-running swarm/cluster roles.
    # Emitted every 15s by TeamRunner's heartbeat thread so the
    # frontend's pong-timeout (70s) never kills the WS during
    # roles that don't produce text deltas.
    TURN_HEARTBEAT = "turn/heartbeat"
    # Soft hand-off hint: when the user's prompt strongly matches
    # a 能力包 / Meta-Skill (via ``match_meta_skill``), the runtime
    # emits this BEFORE ReAct kicks in. The frontend renders a
    # dismissible chip that links to /workspace/meta-skills?q=…;
    # the ReAct loop continues normally so the user gets an answer
    # even if they don't follow the link. No execution rewire —
    # this is informational only until the graph runtime is wired
    # through realtime gateway.
    TURN_META_SKILL_HINT = "turn/metaSkill/hint"

    # Generic item lifecycle
    ITEM_STARTED = "item/started"
    ITEM_COMPLETED = "item/completed"

    # Item content streams
    ITEM_AGENT_MESSAGE_DELTA = "item/agentMessage/delta"
    ITEM_REASONING_TEXT_DELTA = "item/reasoning/textDelta"
    # ``ITEM_PLAN_DELTA`` is reserved but not currently emitted —
    # see ``TURN_PLAN_UPDATED`` above. Reducer side already has a
    # handler so wiring emission only requires a backend change.
    ITEM_PLAN_DELTA = "item/plan/delta"
    ITEM_COMMAND_OUTPUT_DELTA = "item/commandExecution/outputDelta"
    # ``ITEM_FILE_CHANGE_OUTPUT_DELTA`` and
    # ``ITEM_FILE_CHANGE_HUNK_DELTA`` are reserved but not currently
    # emitted — file-edit streaming sees only the final FileChangeItem
    # today. Wiring would unlock the streaming hunks UX.
    ITEM_FILE_CHANGE_OUTPUT_DELTA = "item/fileChange/outputDelta"
    ITEM_FILE_CHANGE_HUNK_DELTA = "item/fileChange/hunkDelta"
    ITEM_FILE_CHANGE_HUNK_DECISION = "item/fileChange/hunkDecision"
    # ``ITEM_MCP_TOOL_CALL_PROGRESS`` is reserved but not currently
    # emitted — MCP long-running tools surface a static spinner.
    ITEM_MCP_TOOL_CALL_PROGRESS = "item/mcpToolCall/progress"

    # Errors / model events
    ERROR = "error"
    MODEL_REROUTED = "model/rerouted"

    # ── Server-initiated requests (client must reply) ────────

    REQ_COMMAND_APPROVAL = "item/commandExecution/requestApproval"
    REQ_FILE_APPROVAL = "item/fileChange/requestApproval"
    REQ_PERMISSIONS_APPROVAL = "item/permissions/requestApproval"
    REQ_USER_INPUT = "item/tool/requestUserInput"
    REQ_MCP_ELICITATION = "mcpServer/elicitation/request"
    PLAN_MODE_EXIT_REQUEST = "item/planMode/exitRequest"
