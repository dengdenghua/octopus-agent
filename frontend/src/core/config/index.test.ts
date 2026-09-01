import { afterEach, describe, expect, test, vi } from "vitest";

import {
  getBackendBaseURL,
  getBackendTransportBaseURL,
  getBackendWebSocketBaseURL,
  getControlPlaneBaseURL,
  getOctopusBaseURL,
  getPublicAssetURL,
} from ".";

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
    expect(getControlPlaneBaseURL()).toBe("");
    expect(getOctopusBaseURL()).toBe("/api");
    expect(getBackendWebSocketBaseURL()).toBe("ws://localhost:3000");
  });

  test("keeps authenticated control-plane requests on the current loopback origin", () => {
    setLocation("http://127.0.0.1:3000/#/workspace/agents");

    expect(getBackendBaseURL()).toBe("");
    expect(getControlPlaneBaseURL()).toBe("");
  });

  test("lets runtime backend query param override dev proxy defaults", () => {
    setLocation(
      "http://localhost:3000/?octopusBackend=http%3A%2F%2F127.0.0.1%3A8000%2F#/workspace/realtime/new",
    );

    expect(getBackendBaseURL()).toBe("http://127.0.0.1:8000");
    expect(getControlPlaneBaseURL()).toBe("http://127.0.0.1:8000");
    expect(getOctopusBaseURL()).toBe("http://127.0.0.1:8000/api");
    expect(window.sessionStorage.getItem("octopusBackend")).toBe(
      "http://127.0.0.1:8000",
    );
  });

  test("reads runtime backend query param from hash-router routes", () => {
    setLocation(
      "http://localhost:3000/#/workspace/realtime/new?octopusBackend=http%3A%2F%2Flocalhost%3A8001%2F",
    );

    expect(getBackendBaseURL()).toBe("http://localhost:8001");
    expect(getOctopusBaseURL()).toBe("http://localhost:8001/api");
    expect(window.sessionStorage.getItem("octopusBackend")).toBe(
      "http://localhost:8001",
    );
  });

  test("prefers shell query runtime backend over hash route query", () => {
    setLocation(
      "http://localhost:3000/?octopusBackend=http%3A%2F%2F127.0.0.1%3A8000%2F#/workspace/realtime/new?octopusBackend=http%3A%2F%2Flocalhost%3A8001",
    );

    expect(getBackendBaseURL()).toBe("http://127.0.0.1:8000");
    expect(getOctopusBaseURL()).toBe("http://127.0.0.1:8000/api");
  });

  test("lets Electron-injected runtime backend override dev proxy defaults", () => {
    setLocation("http://localhost:3000/#/workspace/realtime/new");
    window.octopus = {
      backendBaseURL: "http://127.0.0.1:8765/",
      isElectron: true,
    };

    expect(getBackendBaseURL()).toBe("http://127.0.0.1:8765");
    expect(getBackendTransportBaseURL()).toBe("http://127.0.0.1:8765");
    expect(getBackendWebSocketBaseURL()).toBe("ws://127.0.0.1:8765");
    expect(getOctopusBaseURL()).toBe("http://127.0.0.1:8765/api");
  });

  test("keeps packaged Electron HTTP on its app origin and WebSockets on loopback", () => {
    setLocation(
      "octopus-app://app/index.html?octopusBackend=http%3A%2F%2Fevil.example#/workspace/realtime/new",
    );
    window.octopus = {
      backendBaseURL: "http://127.0.0.1:8765/",
      isElectron: true,
    };

    expect(getBackendBaseURL()).toBe("");
    expect(getOctopusBaseURL()).toBe("/api");
    expect(getBackendTransportBaseURL()).toBe("http://127.0.0.1:8765");
    expect(getBackendWebSocketBaseURL()).toBe("ws://127.0.0.1:8765");
  });

  test("resolves bundled community assets through Vite's public base", () => {
    expect(getPublicAssetURL("/community/memory-video(1).jpg")).toBe(
      "/community/memory-video(1).jpg",
    );
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
