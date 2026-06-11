/**
 * Application entry point.
 *
 * Keep this file thin — mount the root component, wire up global
 * listeners, and delegate everything else. When this file crosses ~100
 * lines, split by concern into sibling modules under `src/`.
 */

const root = document.getElementById("app");
if (!root) throw new Error('Missing <div id="app">.');

root.innerHTML = `
  <main>
    <h1>{{APP_TITLE}}</h1>
    <p>
      Edit <code>src/main.ts</code> and save — Vite hot-reloads the page.
    </p>
  </main>
`;

// TODO: mount your real component tree here.
