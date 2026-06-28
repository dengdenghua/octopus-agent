/**
 * Smoke tests for the unified "模型配置" panel on the model
 * settings page. After the list refactor, each custom-model row
 * carries an open-ended ``models`` array (index 0 = picker default,
 * index -1 = strongest slot for Auto mode). These tests exercise
 * the new shape — they use the edit form because it has the most
 * surface area (rows render the same data, but the inputs there
 * are editable and let us assert the "+ Add / × remove" controls).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { renderWithProviders } from "@/test/harness";

import ModelSettingsPage from "./model-settings-page";

// The settings page calls ``useAuth`` for the guest-aware branching
// in the official-models section. We don't want a real AuthProvider
// hitting the network, so stub it with a guest-shaped object.
vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    isLoading: false,
    isAuthenticated: false,
    isGuest: true,
    user: null,
  }),
}));

// MixSettingsSection fetches its own /api/mix-config + model list on mount.
// That's unrelated to the custom-model list under test here and would perturb
// the ordered fetch mocks below — stub it out.
vi.mock("./mix-settings-section", () => ({
  MixSettingsSection: () => null,
}));

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  // The default model name is loaded from a /api/config call on mount.
  fetchMock.mockResolvedValue(jsonOk({ default: "", models: [] }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

describe("ModelSettingsPage · custom-model list rendering", () => {
  it("renders the full models list for an entry with multiple slots", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonOk({
        models: [
          {
            id: "openai-prod",
            name: "openai-prod",
            display_name: "My OpenAI",
            models: ["gpt-4o-mini", "gpt-4o", "gpt-4.1"],
            provider: "openai",
            base_url: "https://api.openai.com/v1",
            has_api_key: true,
            supports_thinking: false,
            supports_vision: false,
          },
        ],
      }),
    );

    renderWithProviders(<ModelSettingsPage />, { locale: "zh-CN" });

    await waitFor(() => {
      expect(screen.getByText("My OpenAI")).toBeInTheDocument();
    });

    // The "3 models" count chip surfaces in the row.
    expect(screen.getByText("3 个模型")).toBeInTheDocument();
    // All three model ids are visible inline.
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("gpt-4.1")).toBeInTheDocument();
  });

  it("renders a single-model entry without a trailing junk chip", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonOk({
        models: [
          {
            id: "single",
            name: "single",
            display_name: "Single",
            models: ["gpt-4o-mini"],
            provider: "openai",
            base_url: "https://api.openai.com/v1",
            has_api_key: true,
            supports_thinking: false,
            supports_vision: false,
          },
        ],
      }),
    );

    renderWithProviders(<ModelSettingsPage />, { locale: "zh-CN" });

    await waitFor(() => {
      expect(screen.getByText("Single")).toBeInTheDocument();
    });

    // Singular "1 model" form is rendered.
    expect(screen.getByText("1 个模型")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
  });
});

describe("ModelSettingsPage · add-model form · open-ended list", () => {
  it("renders the model list with an add button and a remove control on each row", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ModelSettingsPage />, { locale: "zh-CN" });

    // Wait for the settings page to mount + the initial list call to resolve.
    await waitFor(() => {
      expect(screen.getByText("添加自定义模型")).toBeInTheDocument();
    });

    // Open the add-model form
    await user.click(screen.getByRole("button", { name: "添加自定义模型" }));

    // Label and hint are both visible, anchoring the new shape.
    expect(screen.getByText("模型列表")).toBeInTheDocument();
    expect(screen.getByText(/首项作为选择器默认值/)).toBeInTheDocument();

    // The initial row + the "add model id" button are present.
    expect(
      screen.getByRole("button", { name: /添加模型 ID/ }),
    ).toBeInTheDocument();

    // Clicking "+ Add model ID" appends a new input row. Each new row
    // exposes a remove control with the documented tooltip.
    await user.click(screen.getByRole("button", { name: /添加模型 ID/ }));
    const removeButtons = screen.getAllByRole("button", {
      name: "删除该模型 ID",
    });
    expect(removeButtons.length).toBeGreaterThanOrEqual(2);
  });
});

describe("ModelSettingsPage · local-model one-click import", () => {
  it("renders the scan button, runs the scan, and shows discovered services", async () => {
    const user = userEvent.setup();
    // URL-aware mock: the scan endpoint returns a discovered
    // service, everything else falls back to the empty default.
    // We can't rely on mockResolvedValueOnce here because the
    // settings page kicks off a handful of fetches in parallel
    // on mount (custom-models list, gateway status, llm-models)
    // and we don't want to count them precisely per test.
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/config/local-models/scan")) {
        return jsonOk({
          services: [
            {
              provider: "openai",
              base_url: "http://127.0.0.1:11434/v1",
              probe_path: "/v1/models",
              models: ["qwen2.5:7b", "llama3.1:8b"],
              status: "ok",
            },
          ],
        });
      }
      return jsonOk({ default: "", models: [] });
    });

    renderWithProviders(<ModelSettingsPage />, { locale: "zh-CN" });

    // The section title is rendered on first paint.
    await waitFor(() => {
      expect(screen.getByText("本地模型")).toBeInTheDocument();
    });

    // The scan button starts in idle state — clicking it dispatches
    // the GET /scan request, then the section re-renders with the
    // discovered service list and its import buttons.
    const scanButton = screen.getByRole("button", {
      name: /扫描本地服务/,
    });
    await user.click(scanButton);

    // The scan response surfaces the base_url and the model-count
    // subtitle for the discovered service.
    await waitFor(() => {
      expect(screen.getByText("http://127.0.0.1:11434/v1")).toBeInTheDocument();
    });
    // Import button is present for the discovered service.
    const importButtons = screen.getAllByRole("button", { name: "一键导入" });
    expect(importButtons.length).toBe(1);
  });

  it("shows the empty-state hint when the scan returns no services", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/config/local-models/scan")) {
        return jsonOk({ services: [] });
      }
      return jsonOk({ default: "", models: [] });
    });

    renderWithProviders(<ModelSettingsPage />, { locale: "zh-CN" });

    await waitFor(() => {
      expect(screen.getByText("本地模型")).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /扫描本地服务/ }));

    // Empty-state hint guides the operator toward starting a service.
    await waitFor(() => {
      expect(
        screen.getByText(/请先启动 Ollama \/ LM Studio/),
      ).toBeInTheDocument();
    });
  });
});
