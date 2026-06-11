/*
 * Entry-point script. Loaded at the bottom of index.html so the DOM is
 * already parsed — no need for DOMContentLoaded guards for simple apps.
 *
 * Keep this file focused on wiring DOM events → app state. If the app
 * grows beyond ~200 lines, split by concern (e.g. audio.js, storage.js,
 * ui.js) and import them with <script src="./audio.js"></script> tags
 * — or upgrade to the vite-ts template.
 */

(function boot() {
  // Example: demonstrate the file is actually loaded.
  const h1 = document.querySelector("h1");
  if (h1) {
    h1.addEventListener("click", () => {
      h1.style.color = "var(--accent)";
    });
  }

  // TODO: wire up your app here.
})();
