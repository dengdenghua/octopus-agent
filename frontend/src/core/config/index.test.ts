import { afterEach, describe, expect, test, vi } from "vitest";

import { getBackendBaseURL, getOctopusBaseURL } from ".";

const ORIGINAL_LOCATION = window.location;

function setLocation(url: string) {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: new URL(url),
  });
}

describe("backend base URL resolution", () => {
  afterEach(() => {
    window.sessionStorage.clear();
    vi.unstubAllEnvs();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: ORIGINAL_LOCATION,
    });
    delete window.octopus;
  });

  test("uses Vite proxy-relative URLs in dev mode by default", () => {
    setLocation("http://localhost:3000/#/workspace/agents");

    expect(getBackendBaseURL()).toBe("");
    expect(getOctopusBaseURL()).toBe("/api");
  });

  test("lets runtime backend query param override dev proxy defaults", () => {
    setLocation(
      "http://localhost:3000/?octopusBackend=http%3A%2F%2F127.0.0.1%3A8000%2F#/workspace/realtime/new",
    );

    expect(getBackendBaseURL()).toBe("http://127.0.0.1:8000");
    expect(getOctopusBaseURL()).toBe("http://127.0.0.1:8000/api");
    expect(window.sessionStorage.getItem("octopusBackend")).toBe(
      "http://127.0.0.1:8000",
    );
  });

  test("lets Electron-injected runtime backend override dev proxy defaults", () => {
    setLocation("http://localhost:3000/#/workspace/realtime/new");
    window.octopus = {
      backendBaseURL: "http://127.0.0.1:8765/",
      isElectron: true,
    };

    expect(getBackendBaseURL()).toBe("http://127.0.0.1:8765");
    expect(getOctopusBaseURL()).toBe("http://127.0.0.1:8765/api");
  });

  test("rejects unsafe runtime backend protocols", () => {
    setLocation(
      "http://localhost:3000/?octopusBackend=javascript%3Aalert%281%29#/workspace/agents",
    );

    expect(getBackendBaseURL()).toBe("");
    expect(getOctopusBaseURL()).toBe("/api");
    expect(window.sessionStorage.getItem("octopusBackend")).toBeNull();
  });
});
