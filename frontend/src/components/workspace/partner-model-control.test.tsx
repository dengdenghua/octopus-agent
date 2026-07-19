import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { PartnerModelControl } from "./partner-model-control";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function openControl() {
  const trigger = screen.getByTestId("partner-model-trigger");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
}

describe("PartnerModelControl", () => {
  it("shows the CLI model for Trae without offering an unsupported override", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        model: "doubao-seed-code",
        source: "trae-cli models",
        models: ["doubao-seed-code"],
      }),
    });
    renderWithProviders(
      <PartnerModelControl
        partnerId="trae-cli"
        value="octopus-model-that-must-not-show"
        onChange={vi.fn()}
      />,
      { locale: "zh-CN" },
    );

    expect(await screen.findByText("doubao-seed-code")).toBeInTheDocument();
    await openControl();
    expect(screen.getByText(/由 CLI 自身/)).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(
      screen.queryByText("octopus-model-that-must-not-show"),
    ).not.toBeInTheDocument();
  });

  it("localizes the control and applies a supported Codex override", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        model: "gpt-5.6-codex",
        source: "config.toml",
        models: ["gpt-5.6-codex", "gpt-5.5-codex"],
      }),
    });
    renderWithProviders(
      <PartnerModelControl
        partnerId="codex-cli"
        value=""
        onChange={onChange}
      />,
      { locale: "en-US" },
    );

    await screen.findByText("gpt-5.6-codex");
    await openControl();
    expect(screen.getByText("Local partner model")).toBeInTheDocument();
    const input = screen.getByRole("textbox", {
      name: "Model override for this CLI run",
    });
    await user.clear(input);
    await user.type(input, "gpt-5.5-codex");
    await user.click(screen.getByRole("button", { name: "Apply" }));
    expect(onChange).toHaveBeenCalledWith("gpt-5.5-codex");
  });

  it("shows a retry action when the CLI model cannot be read", async () => {
    const user = userEvent.setup();
    fetchMock
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ model: "gpt-5.6-codex", models: [] }),
      });
    renderWithProviders(
      <PartnerModelControl partnerId="codex-cli" value="" onChange={vi.fn()} />,
      { locale: "en-US" },
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await openControl();
    expect(screen.getByText(/Controlled by the CLI itself/)).toHaveTextContent(
      "The CLI default model could not be read.",
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("gpt-5.6-codex")).toBeInTheDocument();
  });
});
