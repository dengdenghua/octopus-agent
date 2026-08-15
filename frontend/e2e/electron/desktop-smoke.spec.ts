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
import { fileURLToPath } from "node:url";
import path from "node:path";

const THIS_DIR = path.dirname(fileURLToPath(import.meta.url));
const ELECTRON_DIR = path.resolve(THIS_DIR, "..", "..", "electron");
const REPO_ROOT = path.resolve(THIS_DIR, "..", "..", "..");

test("desktop shell boots: window, preload bridge, workbench root", async () => {
  const app = await electron.launch({
    args: [path.join(ELECTRON_DIR, "main.cjs"), "--smoke-test"],
    cwd: REPO_ROOT,
    env: { ...process.env, OCTOPUS_PET_DISABLED: "1" },
  });

  try {
    const win = await app.firstWindow();
    await win.waitForLoadState("domcontentloaded");

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

    // The desktop organizer IPC round-trips (listItems → {ok, items}).
    const listing = await win.evaluate(() =>
      window.octopus?.desktop?.listItems(),
    );
    expect(listing.ok).toBe(true);
    expect(Array.isArray(listing.items)).toBe(true);
  } finally {
    await app.close();
  }
});
