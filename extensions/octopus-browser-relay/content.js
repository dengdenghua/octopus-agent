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
})();
