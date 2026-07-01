const API_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"];
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const READ_ONLY_ACTIONS = new Set(["extract", "aria", "screenshot", "wait"]);
const runningCommands = new Set();
const recentHumanActivityByTab = new Map();
let lastWorkingBase = API_BASES[0];
let activeLease = null;

async function activeTabInfo() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tab = tabs[0];
  if (!tab) return null;
  return {
    id: tab.id,
    url: tab.url || "",
    title: tab.title || "",
  };
}

async function apiFetch(path, init) {
  const bases = [lastWorkingBase, ...API_BASES.filter((base) => base !== lastWorkingBase)];
  for (const base of bases) {
    try {
      const res = await fetch(`${base}${path}`, init);
      if (res.ok) {
        lastWorkingBase = base;
        return res;
      }
    } catch {
      // Try the next localhost spelling.
    }
  }
  return null;
}

async function apiJson(path, init) {
  const res = await apiFetch(path, init);
  if (!res) return null;
  return res.json().catch(() => null);
}

function nowSeconds() {
  return Date.now() / 1000;
}

function comparableUrl(url) {
  return String(url || "").trim();
}

function leaseTabId(lease) {
  const tab = lease?.tab && typeof lease.tab === "object" ? lease.tab : null;
  return tab?.id === undefined || tab?.id === null ? "" : String(tab.id);
}

function leaseTabUrl(lease) {
  const tab = lease?.tab && typeof lease.tab === "object" ? lease.tab : null;
  return comparableUrl(tab?.url);
}

function commandInterruptedError(reason, detail = {}) {
  const error = new Error(`browser relay control interrupted: ${reason}`);
  error.code = "browser_relay_control_interrupted";
  error.reason = reason;
  error.detail = detail;
  return error;
}

function recordHumanActivity(tabId, activity = {}) {
  if (tabId === undefined || tabId === null) return;
  const event = {
    kind: String(activity.kind || "user_activity"),
    at: Number(activity.at || nowSeconds()),
    url: comparableUrl(activity.url),
    title: String(activity.title || ""),
    tabId,
  };
  recentHumanActivityByTab.set(String(tabId), event);
  if (activeLease && String(tabId) === leaseTabId(activeLease)) {
    void reportControlEvent({
      type: "human_interrupt",
      reason: event.kind,
      source: "chrome_content_script",
      activity: event,
      lease: activeLease,
    });
  }
}

async function reportControlEvent(event) {
  await apiFetch("/api/browser/relay/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      extension_version: EXTENSION_VERSION,
      active_tab: await activeTabInfo(),
      control_event: event,
    }),
  });
}

async function relayControl(action, reason = "") {
  return apiJson("/api/browser/relay/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action,
      reason,
      source: "chrome_side_panel",
    }),
  });
}

function waitForTabComplete(tabId, timeoutMs = 10000) {
  return new Promise((resolve) => {
    const timer = setTimeout(done, timeoutMs);
    function done() {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }
    function listener(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        done();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function currentTab() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tab = tabs[0];
  if (!tab?.id) throw new Error("No active browser tab");
  return tab;
}

async function runInTab(tabId, fn, args = []) {
  const [result] = await chrome.scripting.executeScript({
    target: { tabId },
    func: fn,
    args,
  });
  return result?.result;
}

function runDomAction(action, params) {
  const selector = String(params.selector || "");
  const text = String(params.text || "");
  const key = String(params.key || "Enter");
  const y = Number(params.y ?? params.deltaY ?? 700);
  const timeout = Number(params.timeout || 10000);

  function findElement(css) {
    if (!css) throw new Error("selector is required");
    const el = document.querySelector(css);
    if (!el) throw new Error(`selector not found: ${css}`);
    return el;
  }

  function pageAgentSnapshot() {
    if (window.__octopusPageAgent?.snapshot) {
      return window.__octopusPageAgent.snapshot();
    }
    return null;
  }

  async function runPageAgent(payload) {
    if (!window.__octopusPageAgent?.run) {
      throw new Error("page agent bridge is not available on this page");
    }
    return window.__octopusPageAgent.run(payload);
  }

  function visibleText() {
    return (document.body?.innerText || document.documentElement?.innerText || "").trim();
  }

  if (action === "pageAction") {
    return runPageAgent({
      type: "click",
      id: String(params.id || ""),
      confirm: params.confirm === true,
    });
  }
  if (action === "pageInput") {
    return runPageAgent({
      type: "input",
      id: String(params.id || ""),
      text,
      clear: params.clear !== false,
    });
  }
  if (action === "pageCapability") {
    return runPageAgent({
      type: "capability",
      id: String(params.id || ""),
      input: params.input && typeof params.input === "object" ? params.input : {},
      confirm: params.confirm === true,
    });
  }
  if (action === "click") {
    findElement(selector).click();
    return { ok: true };
  }
  if (action === "type") {
    const el = findElement(selector);
    el.focus();
    if ("value" in el) {
      el.value = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      el.textContent = text;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    }
    return { ok: true };
  }
  if (action === "hover") {
    const el = findElement(selector);
    el.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
    return { ok: true };
  }
  if (action === "scroll") {
    if (selector) findElement(selector).scrollIntoView({ block: "center", behavior: "instant" });
    else window.scrollBy({ top: y, left: 0, behavior: "instant" });
    return { ok: true };
  }
  if (action === "press") {
    const target = document.activeElement || document.body;
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
    target.dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true }));
    return { ok: true };
  }
  if (action === "wait") {
    const started = Date.now();
    return new Promise((resolve, reject) => {
      const check = () => {
        if (!selector || document.querySelector(selector)) resolve({ ok: true });
        else if (Date.now() - started > timeout) reject(new Error(`selector not found: ${selector}`));
        else setTimeout(check, 150);
      };
      check();
    });
  }
  if (action === "extract" || action === "aria") {
    const fullText = visibleText();
    const pageAgent = pageAgentSnapshot();
    return {
      ok: true,
      url: location.href,
      title: document.title,
      text: fullText.slice(0, 20000),
      textLength: fullText.length,
      truncated: fullText.length > 20000,
      pageAgent,
      nodes: {
        role: "document",
        name: document.title,
        url: location.href,
        text: fullText.slice(0, 5000),
        pageAgent,
        truncated: fullText.length > 5000,
      },
    };
  }
  throw new Error(`unsupported DOM action: ${action}`);
}

async function validateCommandLease(command) {
  const lease = command.lease && typeof command.lease === "object" ? command.lease : null;
  if (!lease) return null;
  const tab = await currentTab();
  const tabId = String(tab.id);
  const expectedTabId = leaseTabId(lease);
  if (lease.require_same_tab !== false && expectedTabId && tabId !== expectedTabId) {
    await reportControlEvent({
      type: "human_interrupt",
      reason: "active_tab_changed",
      source: "chrome_extension",
      lease,
      activity: {
        kind: "active_tab_changed",
        at: nowSeconds(),
        expectedTabId,
        actualTabId: tabId,
      },
    });
    throw commandInterruptedError("active_tab_changed", {
      expectedTabId,
      actualTabId: tabId,
    });
  }
  const expectedUrl = leaseTabUrl(lease);
  const actualUrl = comparableUrl(tab.url);
  if (lease.require_same_url !== false && expectedUrl && actualUrl !== expectedUrl) {
    await reportControlEvent({
      type: "human_interrupt",
      reason: "tab_url_changed",
      source: "chrome_extension",
      lease,
      activity: {
        kind: "tab_url_changed",
        at: nowSeconds(),
        expectedUrl,
        actualUrl,
      },
    });
    throw commandInterruptedError("tab_url_changed", { expectedUrl, actualUrl });
  }
  const recentActivity = recentHumanActivityByTab.get(tabId);
  const issuedAt = Number(lease.issued_at || 0);
  if (
    recentActivity &&
    Number(recentActivity.at || 0) >= issuedAt &&
    !READ_ONLY_ACTIONS.has(String(command.action || ""))
  ) {
    await reportControlEvent({
      type: "human_interrupt",
      reason: recentActivity.kind,
      source: "chrome_content_script",
      lease,
      activity: recentActivity,
    });
    throw commandInterruptedError(recentActivity.kind, { activity: recentActivity });
  }
  return lease;
}

async function executeCommand(command) {
  const lease = await validateCommandLease(command);
  const tab = await currentTab();
  const tabId = tab.id;
  const action = command.action;
  const params = command.params || {};

  activeLease = lease;
  try {
    if (action === "navigate") {
      const url = String(params.url || "");
      if (!url) throw new Error("url is required");
      await chrome.tabs.update(tabId, { url });
      await waitForTabComplete(tabId);
    } else if (action === "reload") {
      await chrome.tabs.reload(tabId);
      await waitForTabComplete(tabId);
    } else if (action === "back") {
      await chrome.tabs.goBack(tabId);
      await waitForTabComplete(tabId);
    } else if (action === "forward") {
      await chrome.tabs.goForward(tabId);
      await waitForTabComplete(tabId);
    } else if (action === "screenshot") {
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
      return { ok: true, dataUrl };
    } else {
      const domResult = await runInTab(tabId, runDomAction, [action, params]);
      if (domResult && action !== "extract" && action !== "aria") {
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
      if (domResult && (action === "extract" || action === "aria")) return domResult;
    }

    const next = await chrome.tabs.get(tabId);
    return { ok: true, url: next.url || "", title: next.title || "" };
  } finally {
    activeLease = null;
  }
}

async function reportResult(command, result) {
  await apiFetch("/api/browser/relay/result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: command.id,
      active_tab: await activeTabInfo(),
      result,
    }),
  });
}

async function processCommands(commands = []) {
  for (const command of commands) {
    if (!command?.id || runningCommands.has(command.id)) continue;
    runningCommands.add(command.id);
    try {
      const result = await executeCommand(command);
      await reportResult(command, result);
    } catch (error) {
      await reportResult(command, {
        ok: false,
        error: error instanceof Error ? error.message : String(error),
        code: error?.code || "",
        reason: error?.reason || "",
        detail: error?.detail || {},
      });
    } finally {
      runningCommands.delete(command.id);
    }
  }
}

async function postHeartbeat() {
  const data = await apiJson("/api/browser/relay/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      extension_version: EXTENSION_VERSION,
      active_tab: await activeTabInfo(),
      active_lease: activeLease,
      recent_human_activity: Array.from(recentHumanActivityByTab.values()).slice(-5),
    }),
  });
  if (!data) return false;
  void processCommands(Array.isArray(data.commands) ? data.commands : []);
  return true;
}

async function relayStatus() {
  await postHeartbeat();
  const data = await apiJson("/api/browser/relay/status", { method: "GET" });
  return {
    ok: Boolean(data),
    base_url: lastWorkingBase,
    active_tab: await activeTabInfo(),
    relay: data || null,
  };
}

async function openSidePanel(windowId) {
  if (!chrome.sidePanel?.open || !windowId) return false;
  await chrome.sidePanel.open({ windowId });
  return true;
}

async function openPageAgent(tabId) {
  if (!tabId) return false;
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["bookmarklet.js"],
  });
  await postHeartbeat();
  return true;
}

async function configureSidePanelBehavior() {
  if (!chrome.sidePanel?.setPanelBehavior) return;
  try {
    await chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true });
  } catch (error) {
    console.warn(
      "Octopus Browser Relay: failed to enable side panel behavior",
      error instanceof Error ? error.message : error,
    );
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void configureSidePanelBehavior();
  void postHeartbeat();
});

chrome.runtime.onStartup.addListener(() => {
  void configureSidePanelBehavior();
  void postHeartbeat();
});

chrome.action.onClicked.addListener(async (tab) => {
  const tabId = tab.id;
  const windowId = tab.windowId;
  try {
    const opened = await openSidePanel(windowId);
    if (!opened && tabId) {
      await openPageAgent(tabId);
    }
    await postHeartbeat();
  } catch (error) {
    console.warn(
      "Octopus Browser Relay: failed to open Agent Sidecar",
      error instanceof Error ? error.message : error,
    );
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = String(message?.type || "");
  (async () => {
    if (type === "octopus.userActivity") {
      recordHumanActivity(_sender.tab?.id, message.activity || {});
      return { ok: true };
    }
    if (type === "octopus.status") {
      return relayStatus();
    }
    if (type === "octopus.heartbeat") {
      return { ok: await postHeartbeat(), base_url: lastWorkingBase };
    }
    if (type === "octopus.control") {
      return relayControl(String(message.action || ""), String(message.reason || ""));
    }
    if (type === "octopus.openPageAgent") {
      const tab = await currentTab();
      return { ok: await openPageAgent(tab.id) };
    }
    if (type === "octopus.activeTab") {
      return { ok: true, active_tab: await activeTabInfo() };
    }
    return { ok: false, error: `unknown message: ${type}` };
  })()
    .then((result) => sendResponse(result))
    .catch((error) => {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    });
  return true;
});

chrome.tabs.onActivated.addListener(() => {
  if (activeLease) {
    void currentTab()
      .then((tab) => {
        const expectedTabId = leaseTabId(activeLease);
        if (expectedTabId && String(tab.id) !== expectedTabId) {
          return reportControlEvent({
            type: "human_interrupt",
            reason: "active_tab_changed",
            source: "chrome_tabs_api",
            lease: activeLease,
            activity: {
              kind: "active_tab_changed",
              at: nowSeconds(),
              expectedTabId,
              actualTabId: tab.id,
            },
          });
        }
        return null;
      })
      .catch(() => null);
  }
  void postHeartbeat();
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url) {
    void postHeartbeat();
  }
});

setInterval(() => {
  void postHeartbeat();
}, 500);

void postHeartbeat();
