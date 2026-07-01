const API_BASES = ["http://127.0.0.1:8000", "http://localhost:8000"];
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const runningCommands = new Set();
let lastWorkingBase = API_BASES[0];

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

async function executeCommand(command) {
  const tab = await currentTab();
  const tabId = tab.id;
  const action = command.action;
  const params = command.params || {};

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
    if (type === "octopus.status") {
      return relayStatus();
    }
    if (type === "octopus.heartbeat") {
      return { ok: await postHeartbeat(), base_url: lastWorkingBase };
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
