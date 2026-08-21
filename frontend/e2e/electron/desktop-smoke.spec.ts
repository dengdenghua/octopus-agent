/**
 * Desktop shell smoke test (Playwright Electron).
 *
 * Proves the Electron shell boots end to end from an unpackaged checkout:
 *  1. the window is created and loads the built ``dist/`` workbench,
 *  2. the preload bridge (``window.octopus``) is wired to the main process,
 *  3. the React workbench mounts into ``#root``.
 *
 * The unpackaged launch intentionally does NOT spawn the Python backend
 * (main.cjs keeps that for packaged builds), so the workbench may sit on its
 * "reconnecting" state — this test is about the SHELL, not the backend. A
 * backend-health assertion belongs to the browser full-stack smoke lane.
 */
import { test, expect, _electron as electron } from "@playwright/test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import path from "node:path";

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
const ELECTRON_DIR = path.resolve(THIS_DIR, "..", "..", "electron");
const REPO_ROOT = path.resolve(THIS_DIR, "..", "..", "..");

test("desktop shell boots: window, preload bridge, workbench root", async () => {
  const userDataDir = await mkdtemp(
    path.join(tmpdir(), "octopus-electron-shell-"),
  );
  const app = await electron.launch({
    args: [
      path.join(ELECTRON_DIR, "main.cjs"),
      "--smoke-test",
      `--user-data-dir=${userDataDir}`,
    ],
    cwd: REPO_ROOT,
    env: { ...process.env, OCTOPUS_PET_DISABLED: "1" },
  });

  try {
    const win = await app.firstWindow();
    await win.waitForLoadState("domcontentloaded");

    const rendererOrigin = await win.evaluate(() => ({
      protocol: window.location.protocol,
      host: window.location.host,
      origin: window.location.origin,
      secureContext: window.isSecureContext,
    }));
    expect(rendererOrigin).toEqual({
      protocol: "octopus-app:",
      host: "app",
      origin: "octopus-app://app",
      secureContext: true,
    });

    // The preload bridge must be present and resolved to the main process.
    const bridge = await win.evaluate(() => ({
      isElectron: window.octopus?.isElectron,
      platform: window.octopus?.platform,
      backendBaseURL: window.octopus?.backendBaseURL,
    }));
    expect(bridge.isElectron).toBe(true);
    expect(typeof bridge.platform).toBe("string");
    expect(typeof bridge.backendBaseURL).toBe("string");

    // The workbench mounts into #root (dist/index.html).
    await win.waitForSelector("#root");
    const rootHasContent = await win.evaluate(
      () => !!document.querySelector("#root")?.firstElementChild,
    );
    expect(rootHasContent).toBe(true);

    // Absolute public URLs must stay inside the packaged renderer origin.
    const communityAsset = await win.evaluate(async () => {
      const res = await fetch("/community/memory-video(1).jpg");
      return {
        ok: res.ok,
        size: (await res.arrayBuffer()).byteLength,
        allowOrigin: res.headers.get("access-control-allow-origin"),
      };
    });
    expect(communityAsset.ok).toBe(true);
    expect(communityAsset.size).toBeGreaterThan(0);
    expect(communityAsset.allowOrigin).not.toBe("*");

    const webPreferences = await app.evaluate(({ BrowserWindow }) =>
      BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences(),
    );
    expect(webPreferences.webSecurity).not.toBe(false);

    // The desktop organizer IPC round-trips (listItems → {ok, items}).
    const listing = await win.evaluate(() =>
      window.octopus?.desktop?.listItems(),
    );
    expect(listing.ok).toBe(true);
    expect(Array.isArray(listing.items)).toBe(true);

    // The browser bridge must refuse to drive the MAIN window's webContents:
    // browser:executeJS is for embedded <webview> tabs only. This proves the
    // renderer cannot pivot off its own webviews (defense in depth).
    const mainContentsId = await app.evaluate(
      ({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.id,
    );
    const executeOnMain = await win.evaluate(async (wid) => {
      try {
        await window.octopus?.browser?.executeJS?.(wid, "1+1");
        return "accepted";
      } catch (err) {
        return err instanceof Error ? err.message : String(err);
      }
    }, mainContentsId);
    expect(executeOnMain).toContain("not a webview");
  } finally {
    await app.close();
    await rm(userDataDir, { recursive: true, force: true });
  }
});

test("desktop backend spawns and the renderer reaches it", async () => {
  const backendPort = 18000;
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const userDataDir = await mkdtemp(
    path.join(tmpdir(), "octopus-electron-backend-"),
  );
  const app = await electron.launch({
    args: [
      path.join(ELECTRON_DIR, "main.cjs"),
      "--smoke-test-backend",
      `--user-data-dir=${userDataDir}`,
    ],
    cwd: REPO_ROOT,
    env: {
      ...process.env,
      OCTOPUS_PET_DISABLED: "1",
      // Reuse the checkout's venv so the spawn path runs without a
      // first-launch bootstrap download.
      OCTOPUS_DESKTOP_BACKEND_ROOT: REPO_ROOT,
      OCTOPUS_BACKEND_URL: backendUrl,
    },
  });

  try {
    const win = await app.firstWindow();
    await win.waitForLoadState("domcontentloaded");

    // The preload must advertise the smoke backend URL the renderer connects
    // to — proves the spawn port and the renderer's base URL agree.
    const baseURL = await win.evaluate(() => window.octopus?.backendBaseURL);
    expect(baseURL).toBe(backendUrl);

    // Poll /api/health until the Python backend finishes booting.
    let healthOk = false;
    for (let i = 0; i < 60; i++) {
      try {
        const res = await fetch(`${backendUrl}/api/health`);
        if (res.ok) {
          healthOk = true;
          break;
        }
      } catch {
        // backend still booting — retry
      }
      await new Promise((r) => setTimeout(r, 500));
    }
    expect(healthOk).toBe(true);

    // This is the production contract that Node-side polling cannot prove:
    // Chromium fetches native /api and /api/plugins paths from the fixed app
    // origin, and the main process forwards them without disabling CORS.
    const rendererContract = await win.evaluate(async () => {
      const health = await fetch("/api/health");
      const auth = await fetch("/api/auth/status");
      const plugin = await fetch("/api/plugins/paper-trading/page");
      return {
        origin: window.location.origin,
        healthStatus: health.status,
        healthAllowOrigin: health.headers.get("access-control-allow-origin"),
        authStatus: auth.status,
        authBody: await auth.json(),
        pluginStatus: plugin.status,
        pluginContentType: plugin.headers.get("content-type"),
        pluginBody: (await plugin.text()).slice(0, 500),
      };
    });
    expect(rendererContract.origin).toBe("octopus-app://app");
    expect(rendererContract.healthStatus).toBe(200);
    expect(rendererContract.healthAllowOrigin).not.toBe("*");
    expect(rendererContract.authStatus).toBe(200);
    expect(rendererContract.authBody).toMatchObject({ enabled: true });
    expect(rendererContract.pluginStatus).toBe(200);
    expect(rendererContract.pluginContentType).toContain("text/html");
    expect(rendererContract.pluginBody).toContain("<");

    // Authenticate through the custom origin, then establish the raw
    // loopback WebSocket transport used by realtime/terminal/tentacle hooks.
    // This catches secure-context mixed-content regressions that HTTP fetch
    // and Node-side backend polling cannot see.
    const websocketContract = await win.evaluate(async () => {
      const login = await fetch("/api/auth/local/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: `electron-e2e-${Date.now()}` }),
      });
      const body = (await login.json()) as { access_token?: string };
      if (!login.ok || !body.access_token) {
        return { loginStatus: login.status, websocket: "no-token" };
      }
      const backend = window.octopus?.backendBaseURL ?? "";
      const websocketBase = backend.replace(/^http/, "ws");
      const websocket = await new Promise<string>((resolve) => {
        const socket = new WebSocket(
          `${websocketBase}/api/realtime`,
          ["bearer", body.access_token!],
        );
        const timer = window.setTimeout(() => {
          socket.close();
          resolve("timeout");
        }, 5_000);
        socket.onopen = () => {
          window.clearTimeout(timer);
          socket.close();
          resolve("open");
        };
        socket.onerror = () => {
          window.clearTimeout(timer);
          resolve("error");
        };
      });
      return { loginStatus: login.status, websocket };
    });
    expect(websocketContract).toEqual({ loginStatus: 200, websocket: "open" });
  } finally {
    await app.close();
    await rm(userDataDir, { recursive: true, force: true });
  }
});
