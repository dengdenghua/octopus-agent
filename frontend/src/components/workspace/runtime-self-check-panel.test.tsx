import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test/harness";

import { RuntimeSelfCheckPanel } from "./runtime-self-check-panel";

const fetchMock = vi.fn();

const SAMPLE = {
  schema: "octopus.runtime_self_check.v1",
  ready: false,
  status: "degraded",
  generated_at: "2026-06-29T08:00:00Z",
  version: "0.2.0",
  version_drift: {
    runtime_matches_pyproject: true,
    frontend_matches_runtime: false,
    version_sources: {
      runtime: "0.2.0",
      pyproject: "0.2.0",
      frontend_package: "0.1.0",
    },
  },
  backend: {
    canonical_base_url: "http://127.0.0.1:8000",
    request_origin_base_url: "http://localhost:8000",
    request_url: "http://localhost:8000/api/runtime/self-check",
    host: "localhost",
    canonical_host: "127.0.0.1",
    port: 8000,
    env_port: null,
    server_host: "0.0.0.0",
    server_port: 8000,
  },
  process: {
    pid: 4242,
    python: "3.12.13",
    cwd: "/repo",
    argv: ["python", "-m", "runtime", "serve"],
  },
  frontend: {
    observed_origin: "http://localhost:3000",
    canonical_origin: "http://localhost:3000",
    canonical_host: "localhost",
    port: 3000,
    env_port: null,
    dev_proxy_mode: true,
    proxy_target: "http://127.0.0.1:8000",
    proxy_targets_backend: true,
    origin_normalized: true,
    loopback_aliases: ["http://127.0.0.1:3000", "http://localhost:3000"],
  },
  webui: {
    available: true,
    selected_dist: "/repo/frontend/dist",
    env_dist: "/missing/dist",
    env_dist_invalid: true,
    assets_count: 12,
    dev_fallback_expected: false,
    detail:
      "configured OCTOPUS_WEBUI_DIST is invalid: /missing/dist; fallback=/repo/frontend/dist",
  },
  api_surface: {
    route_count: 180,
    required_routes_present: true,
    missing_required_routes: [],
  },
  loopback_aliases: {
    requested_host: "localhost",
    canonical_host: "127.0.0.1",
    same_loopback_family: true,
    aliases: ["http://127.0.0.1:8000", "http://localhost:8000"],
  },
  paths: {
    project_root: "/repo",
    journal_source: "/repo/data/journal.jsonl",
  },
  checks: [
    {
      id: "runtime_version",
      passed: true,
      severity: "error",
      detail: "runtime=0.2.0 pyproject=0.2.0",
    },
    {
      id: "frontend_version",
      passed: false,
      severity: "error",
      detail: "frontend=0.1.0 runtime=0.2.0",
    },
    {
      id: "webui_dist",
      passed: false,
      severity: "warn",
      detail:
        "configured OCTOPUS_WEBUI_DIST is invalid: /missing/dist; fallback=/repo/frontend/dist",
    },
  ],
  next_actions: ["frontend=0.1.0 runtime=0.2.0"],
  warnings: [
    "configured OCTOPUS_WEBUI_DIST is invalid: /missing/dist; fallback=/repo/frontend/dist",
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.restoreAllMocks();
});

function mockOnce(body: unknown) {
  fetchMock.mockResolvedValueOnce({
    ok: true,
    status: 200,
    json: async () => body,
  });
}

describe("RuntimeSelfCheckPanel", () => {
  it("renders runtime version, backend URL, loopback aliases, and next actions", async () => {
    mockOnce(SAMPLE);
    renderWithProviders(
      <RuntimeSelfCheckPanel baseUrl="http://127.0.0.1:8000" />,
    );

    await waitFor(() => {
      expect(screen.getByText("Runtime Self-Check")).toBeInTheDocument();
      expect(screen.getAllByText("degraded").length).toBeGreaterThan(0);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/runtime/self-check",
    );
    expect(screen.getAllByText("0.2.0").length).toBeGreaterThan(0);
    expect(screen.getAllByText("http://127.0.0.1:8000").length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText("http://localhost:8000").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Frontend")).toBeInTheDocument();
    expect(screen.getByText("Observed origin")).toBeInTheDocument();
    expect(screen.getAllByText("http://localhost:3000").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Vite proxy target")).toBeInTheDocument();
    expect(screen.getByText("Proxy matches backend")).toBeInTheDocument();
    expect(screen.getByText("Process")).toBeInTheDocument();
    expect(screen.getByText("4242")).toBeInTheDocument();
    expect(screen.getByText("WebUI static bundle")).toBeInTheDocument();
    expect(screen.getAllByText("/repo/frontend/dist").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("API surface")).toBeInTheDocument();
    expect(screen.getByText("180")).toBeInTheDocument();
    expect(screen.getByText("frontend_version")).toBeInTheDocument();
    expect(screen.getByText("webui_dist")).toBeInTheDocument();
    expect(screen.getByText("warn")).toBeInTheDocument();
    expect(screen.getByText("Warnings")).toBeInTheDocument();
    expect(screen.getAllByText("frontend=0.1.0 runtime=0.2.0").length).toBe(2);
  });

  it("refreshes the self-check on demand", async () => {
    mockOnce(SAMPLE);
    mockOnce({
      ...SAMPLE,
      ready: true,
      status: "degraded",
      next_actions: [],
      warnings: ["configured OCTOPUS_WEBUI_DIST is invalid"],
    });
    renderWithProviders(<RuntimeSelfCheckPanel />);

    await waitFor(() => {
      expect(screen.getAllByText("degraded").length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole("button", { name: /Refresh/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(screen.getAllByText("degraded").length).toBeGreaterThan(0);
    });
  });

  it("shows fetch failures", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => ({}),
    });
    renderWithProviders(<RuntimeSelfCheckPanel />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("HTTP 503");
    });
  });
});
