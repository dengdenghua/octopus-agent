const API_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"];
const FRONTEND_BASES = ["http://localhost:3000", "http://127.0.0.1:3000"];
const THREAD_KEY = "octopus.chrome.sidecar.threadId";

const state = {
  apiBase: API_BASES[0],
  ws: null,
  nextId: 1,
  pending: new Map(),
  connected: false,
  streaming: false,
  threadId: localStorage.getItem(THREAD_KEY) || makeThreadId(),
  activeTab: null,
  assistantItems: new Map(),
};

const el = {
  connectionText: document.getElementById("connectionText"),
  relayDot: document.getElementById("relayDot"),
  tabTitle: document.getElementById("tabTitle"),
  tabUrl: document.getElementById("tabUrl"),
  approvalDock: document.getElementById("approvalDock"),
  messages: document.getElementById("messages"),
  composer: document.getElementById("composer"),
  promptInput: document.getElementById("promptInput"),
  sendButton: document.getElementById("sendButton"),
  newThreadButton: document.getElementById("newThreadButton"),
  pageAgentButton: document.getElementById("pageAgentButton"),
  openAppButton: document.getElementById("openAppButton"),
};

localStorage.setItem(THREAD_KEY, state.threadId);
wireUi();
void refreshRelayStatus();
connectRealtime();
setInterval(() => void refreshRelayStatus(), 1500);

function wireUi() {
  el.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    void sendPrompt();
  });
  el.promptInput.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void sendPrompt();
    }
  });
  el.newThreadButton.addEventListener("click", () => {
    state.threadId = makeThreadId();
    state.assistantItems.clear();
    localStorage.setItem(THREAD_KEY, state.threadId);
    el.messages.replaceChildren();
    appendSystem("已开启新的 Chrome Sidecar 对话。");
  });
  el.pageAgentButton.addEventListener("click", async () => {
    const result = await runtimeMessage({ type: "octopus.openPageAgent" });
    if (!result?.ok) {
      appendSystem(`页面轻面板打开失败: ${result?.error || "unknown error"}`, true);
    }
  });
  el.openAppButton.addEventListener("click", () => {
    const url = `${FRONTEND_BASES[0]}/#/workspace/realtime/${encodeURIComponent(
      state.threadId,
    )}`;
    chrome.tabs.create({ url });
  });
}

function makeThreadId() {
  return `chrome-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function runtimeMessage(message) {
  return chrome.runtime.sendMessage(message).catch((error) => ({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
  }));
}

async function refreshRelayStatus() {
  const status = await runtimeMessage({ type: "octopus.status" });
  if (!status?.ok) {
    setConnectionText("Relay offline");
    el.relayDot.className = "status-dot error";
    return;
  }
  state.apiBase = status.base_url || state.apiBase;
  state.activeTab = status.active_tab || status.relay?.active_tab || null;
  const relayConnected = status.relay?.connected === true;
  el.relayDot.className = `status-dot ${relayConnected ? "connected" : ""}`;
  el.tabTitle.textContent = state.activeTab?.title || "No active tab";
  el.tabUrl.textContent = state.activeTab?.url || "Waiting for Chrome relay";
  setConnectionText(
    state.connected
      ? relayConnected
        ? "Realtime + Chrome connected"
        : "Realtime connected · relay waiting"
      : relayConnected
        ? "Chrome connected · realtime waiting"
        : "Connecting",
  );
}

function setConnectionText(text) {
  el.connectionText.textContent = text;
  el.sendButton.disabled = !state.connected || state.streaming;
}

function connectRealtime() {
  if (
    state.ws &&
    (state.ws.readyState === WebSocket.OPEN ||
      state.ws.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }
  const wsUrl = `${state.apiBase.replace(/^http/, "ws")}/api/realtime`;
  const ws = new WebSocket(wsUrl);
  state.ws = ws;
  ws.onopen = () => {
    state.connected = true;
    setConnectionText("Realtime connected");
    appendSystem("Realtime 已连接。");
  };
  ws.onmessage = (event) => handleRealtimeMessage(String(event.data || ""));
  ws.onerror = () => {
    state.connected = false;
    setConnectionText("Realtime error");
  };
  ws.onclose = () => {
    state.connected = false;
    failPending("realtime websocket closed");
    state.streaming = false;
    setConnectionText("Realtime reconnecting");
    window.setTimeout(() => {
      state.apiBase =
        state.apiBase === API_BASES[0] ? API_BASES[1] : API_BASES[0];
      connectRealtime();
    }, 900);
  };
}

function failPending(message) {
  for (const pending of state.pending.values()) {
    pending.reject(new Error(message));
  }
  state.pending.clear();
}

function rpc(method, params = {}) {
  connectRealtime();
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    return Promise.reject(new Error("realtime websocket is not connected"));
  }
  const id = state.nextId++;
  const payload = { jsonrpc: "2.0", id, method, params };
  state.ws.send(JSON.stringify(payload));
  return new Promise((resolve, reject) => {
    state.pending.set(id, { resolve, reject });
  });
}

function handleRealtimeMessage(raw) {
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    return;
  }
  if (payload.id !== undefined && (payload.result || payload.error)) {
    const pending = state.pending.get(payload.id);
    if (!pending) return;
    state.pending.delete(payload.id);
    if (payload.error) pending.reject(new Error(payload.error.message));
    else pending.resolve(payload.result);
    return;
  }
  if (payload.id !== undefined && payload.method) {
    showApprovalRequest(payload);
    return;
  }
  if (!payload.method) return;
  handleNotification(payload.method, payload.params || {});
}

function handleNotification(method, params) {
  if (method === "item/agentMessage/delta") {
    appendAssistantDelta(params.itemId, String(params.delta || ""));
    return;
  }
  if (method === "item/started") {
    const item = params.item || {};
    if (item.type === "commandExecution") {
      appendEvent(`工具开始: ${item.command || item.id || "command"}`);
    }
    return;
  }
  if (method === "item/completed") {
    const item = params.item || {};
    if (item.type === "agentMessage" && item.text) {
      replaceAssistantText(item.id, String(item.text));
    } else if (item.type === "commandExecution") {
      appendEvent(`工具完成: ${item.command || item.id || "command"}`);
    }
    return;
  }
  if (method === "turn/completed" || method === "turn/interrupted") {
    state.streaming = false;
    setConnectionText("Realtime connected");
    return;
  }
  if (method === "error") {
    state.streaming = false;
    setConnectionText("Realtime connected");
    appendSystem(params.error?.message || "Agent turn failed", true);
  }
}

async function sendPrompt() {
  const text = el.promptInput.value.trim();
  if (!text || state.streaming) return;
  appendUser(text);
  el.promptInput.value = "";
  state.streaming = true;
  setConnectionText("Agent working");
  const prompt = text.toLowerCase().startsWith("@chrome")
    ? text
    : `@Chrome\n${text}`;
  try {
    await rpc("turn/start", {
      threadId: state.threadId,
      input: [
        {
          type: "text",
          text: prompt,
          metadata: {
            context: {
              mode: "chrome",
              capability_mode: "browser",
              runtime_surfaces: ["chrome"],
              tool_surface: "chrome",
              browser_operation_mode: true,
              chrome_operation_mode: true,
              browser_surface: "chrome",
              browser_session_policy: "thread_native_external_chrome",
              browser_track_preference: "extension",
              browser_permission_policy: "site_policy_required",
              browser_active_tab: state.activeTab,
            },
          },
        },
      ],
      approvalPolicy: "on-request",
    });
  } catch (error) {
    state.streaming = false;
    setConnectionText("Realtime connected");
    appendSystem(error instanceof Error ? error.message : String(error), true);
  }
}

function showApprovalRequest(request) {
  el.approvalDock.hidden = false;
  const card = document.createElement("article");
  card.className = "approval-card";
  const title = document.createElement("h2");
  title.textContent = "需要确认";
  const body = document.createElement("pre");
  body.textContent = JSON.stringify(
    {
      method: request.method,
      params: request.params,
    },
    null,
    2,
  );
  const actions = document.createElement("div");
  actions.className = "approval-actions";
  const accept = document.createElement("button");
  accept.className = "primary";
  accept.type = "button";
  accept.textContent = "允许";
  const decline = document.createElement("button");
  decline.className = "secondary";
  decline.type = "button";
  decline.textContent = "拒绝";
  actions.append(accept, decline);
  card.append(title, body, actions);
  el.approvalDock.replaceChildren(card);
  accept.addEventListener("click", () => {
    reply(request.id, { action: "accept" });
    clearApproval();
  });
  decline.addEventListener("click", () => {
    reply(request.id, { action: "decline" });
    clearApproval();
  });
}

function reply(id, result) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  state.ws.send(JSON.stringify({ jsonrpc: "2.0", id, result }));
}

function clearApproval() {
  el.approvalDock.hidden = true;
  el.approvalDock.replaceChildren();
}

function appendSystem(text, danger = false) {
  const node = document.createElement("article");
  node.className = `message system${danger ? " danger" : ""}`;
  node.textContent = text;
  el.messages.append(node);
  scrollMessages();
}

function appendUser(text) {
  appendMessage("user", "你", text);
}

function appendAssistantDelta(itemId, delta) {
  let node = state.assistantItems.get(itemId);
  if (!node) {
    node = appendMessage("assistant", "Agent", "");
    state.assistantItems.set(itemId, node);
  }
  const textNode = node.querySelector(".text");
  textNode.textContent += delta;
  scrollMessages();
}

function replaceAssistantText(itemId, text) {
  let node = state.assistantItems.get(itemId);
  if (!node) {
    node = appendMessage("assistant", "Agent", "");
    state.assistantItems.set(itemId, node);
  }
  node.querySelector(".text").textContent = text;
  scrollMessages();
}

function appendMessage(role, label, text) {
  const node = document.createElement("article");
  node.className = `message ${role}`;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = label;
  const body = document.createElement("div");
  body.className = "text";
  body.textContent = text;
  node.append(meta, body);
  el.messages.append(node);
  scrollMessages();
  return node;
}

function appendEvent(text) {
  const node = document.createElement("div");
  node.className = "event-row";
  node.textContent = text;
  el.messages.append(node);
  scrollMessages();
}

function scrollMessages() {
  el.messages.scrollTop = el.messages.scrollHeight;
}
