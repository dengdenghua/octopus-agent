(() => {
  const version =
    typeof chrome !== "undefined" && chrome.runtime?.getManifest
      ? chrome.runtime.getManifest().version
      : "local-dev";

  Object.defineProperty(window, "__OCTOPUS_BROWSER_RELAY__", {
    value: { ready: true, version },
    configurable: true,
  });

  document.documentElement.dataset.octopusBrowserRelay = "ready";

  let lastActivityAt = 0;
  function reportUserActivity(kind, event) {
    if (!event?.isTrusted || typeof chrome === "undefined" || !chrome.runtime?.sendMessage) {
      return;
    }
    const now = Date.now();
    if (now - lastActivityAt < 400) return;
    lastActivityAt = now;
    chrome.runtime
      .sendMessage({
        type: "octopus.userActivity",
        activity: {
          kind,
          at: now / 1000,
          url: location.href,
          title: document.title,
        },
      })
      .catch(() => {
        // The extension may have been reloaded while this content script is still alive.
      });
  }

  document.addEventListener("pointerdown", (event) => reportUserActivity("pointerdown", event), {
    capture: true,
    passive: true,
  });
  document.addEventListener("keydown", (event) => reportUserActivity("keydown", event), {
    capture: true,
  });
  document.addEventListener("input", (event) => reportUserActivity("input", event), {
    capture: true,
  });
  document.addEventListener("paste", (event) => reportUserActivity("paste", event), {
    capture: true,
  });
})();
