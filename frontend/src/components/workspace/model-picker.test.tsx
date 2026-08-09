/**
 * Tests for the chat-input model picker — compact dropdown variant.
 *
 * Focus: one flat model list + selection plumbing. The Official/Custom
 * tab split was removed — with a handful of configured endpoints it cost
 * two clicks to reach a neighbouring model and hid the selected row behind
 * whichever tab opened by default. We don't re-test Radix DropdownMenu
 * internals.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AllProviders } from "@/test/harness";

import { ModelPicker, type PickerModel } from "./model-picker";

// Stub useOctLink — picker reads `link.oct_user_id` to auto-enable
// unconfigured models.
vi.mock("@/core/oct/hooks", () => ({
  useOctLink: () => ({ data: null }),
}));

function withProviders(node: React.ReactNode) {
  // Test assertions reference zh-CN copy, so prime the I18nProvider to zh-CN.
  return <AllProviders locale="zh-CN">{node}</AllProviders>;
}

// Backwards-compat alias used in older tests.
const withRouter = withProviders;

// MODELS includes octopus-mix (official) plus several custom models.
// The picker opens on the category that contains the current selection.
const MODELS: PickerModel[] = [
  { name: "octopus-mix", display_name: "Octopus Mix", provider: "octopus" },
  { name: "kimi-k2.5", display_name: "Kimi K2.5", model: "kimi" },
  { name: "minimax-m2.7", display_name: "MiniMax M2.7", model: "minimax" },
  { name: "glm-5", display_name: "GLM-5", model: "glm" },
  { name: "deepseek-v3.2", display_name: "DeepSeek-V3.2", model: "deepseek" },
  { name: "qwen3-max", display_name: "Qwen3-Max", model: "qwen" },
  {
    name: "claude-opus-4-6-mirror",
    display_name: "Claude Opus 4.6 (mirror)",
    model: "claude-opus",
    description: "Anthropic Opus via mirror",
  },
];

describe("<ModelPicker />", () => {
  function setup(value = "kimi-k2.5") {
    const onChange = vi.fn();
    const utils = render(
      withRouter(
        <ModelPicker models={MODELS} value={value} onChange={onChange} />,
      ),
    );
    return { ...utils, onChange };
  }

  it("renders the default trigger with the resolved model name", () => {
    setup();
    expect(screen.getByRole("button", { name: "选择模型" })).toHaveTextContent(
      "Kimi K2.5",
    );
  });

  it("lists every model in one flat list, no tabs", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByTestId("model-picker-trigger"));
    const menu = await screen.findByTestId("model-picker-menu");
    expect(menu).toBeInTheDocument();
    // No tab strip at all — every model is reachable without a category hop.
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    for (const label of [
      "Octopus Mix",
      "Kimi K2.5",
      "GLM-5",
      "Claude Opus 4.6 (mirror)",
    ]) {
      expect(within(menu).getByText(label)).toBeInTheDocument();
    }
  });

  it("folds the 1M variant into its base row instead of a second row", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      withRouter(
        <ModelPicker
          models={[
            {
              name: "deepseek-v4-pro",
              model: "deepseek-v4-pro",
              display_name: "DeepSeek V4 Pro",
              context_profile: "default",
            },
            {
              name: "deepseek-v4-pro::1m",
              model: "deepseek-v4-pro",
              display_name: "DeepSeek V4 Pro",
              context_profile: "1m",
            },
          ]}
          value="deepseek-v4-pro"
          onChange={onChange}
        />,
      ),
    );

    await user.click(screen.getByTestId("model-picker-trigger"));
    const menu = await screen.findByTestId("model-picker-menu");
    // One row for the model, not two near-identical ones. Scoped to the menu
    // because the trigger also renders the selected model's label.
    expect(within(menu).getAllByText("DeepSeek V4 Pro")).toHaveLength(1);
    // The long-context variant is still reachable, as an inline affordance.
    await user.click(screen.getByTestId("model-picker-1m-deepseek-v4-pro"));
    expect(onChange).toHaveBeenCalledWith("deepseek-v4-pro::1m");
  });

  it("selecting the row itself keeps the default context window", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      withRouter(
        <ModelPicker
          models={[
            {
              name: "deepseek-v4-pro",
              model: "deepseek-v4-pro",
              display_name: "DeepSeek V4 Pro",
              context_profile: "default",
            },
            {
              name: "deepseek-v4-pro::1m",
              model: "deepseek-v4-pro",
              display_name: "DeepSeek V4 Pro",
              context_profile: "1m",
            },
          ]}
          value="deepseek-v4-pro"
          onChange={onChange}
        />,
      ),
    );

    await user.click(screen.getByTestId("model-picker-trigger"));
    const menu = await screen.findByTestId("model-picker-menu");
    await user.click(
      within(menu).getByText("DeepSeek V4 Pro").closest("button")!,
    );
    expect(onChange).toHaveBeenCalledWith("deepseek-v4-pro");
  });

  it("keeps reasoning effort inside the model dropdown", async () => {
    const user = userEvent.setup();
    const onReasoningEffortChange = vi.fn();
    render(
      withRouter(
        <ModelPicker
          models={MODELS}
          value="kimi-k2.5"
          onChange={vi.fn()}
          reasoningEffort="medium"
          onReasoningEffortChange={onReasoningEffortChange}
        />,
      ),
    );

    await user.click(screen.getByRole("button", { name: "选择模型" }));
    const group = await screen.findByRole("radiogroup", {
      name: "推理等级",
    });

    expect(within(group).getByRole("radio", { name: "中" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(within(group).getByRole("radio", { name: "超高" }));

    expect(onReasoningEffortChange).toHaveBeenCalledWith("xhigh");
  });

  it("selecting the official Octopus Mix row invokes onChange with its backend name", async () => {
    const user = userEvent.setup();
    const { onChange } = setup("kimi-k2.5");
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    const mixBtn = Array.from(root.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("Octopus Mix"),
    );
    expect(mixBtn).toBeTruthy();
    await user.click(mixBtn!);

    expect(onChange).toHaveBeenCalledWith("octopus-mix");
  });

  it("shows a bare model name with no guessed vendor label", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByText("Claude Opus 4.6 (mirror)"),
    ).toBeInTheDocument();
    // The old right column guessed a vendor from the model name ("claude" →
    // "Claude"), which restated what the label already said.
    expect(within(menu).queryByText("Claude")).not.toBeInTheDocument();
  });

  it("shows the 添加模型 CTA", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByRole("button", { name: /添加模型/ }),
    ).toBeInTheDocument();
  });

  it("clicking a custom row fires onChange", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    await user.click(
      within(menu).getByText("Claude Opus 4.6 (mirror)").closest("button")!,
    );
    expect(onChange).toHaveBeenCalledWith("claude-opus-4-6-mirror");
  });

  it("trigger shows Octopus Mix label when that model is selected", () => {
    setup("octopus-mix");
    expect(screen.getByRole("button", { name: "选择模型" })).toHaveTextContent(
      "Octopus Mix",
    );
  });

  it("supports a renderTrigger override", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      withRouter(
        <ModelPicker
          models={MODELS}
          value="kimi-k2.5"
          onChange={onChange}
          renderTrigger={(sel) => (
            <button type="button">CUSTOM-TRIGGER {sel?.name}</button>
          )}
        />,
      ),
    );
    const trigger = screen.getByRole("button", {
      name: /CUSTOM-TRIGGER kimi-k2.5/,
    });
    await user.click(trigger);
    expect(await screen.findByRole("menu")).toBeInTheDocument();
  });

  it("surfaces octopus-mix in the Official tab when advertised", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      withProviders(
        <ModelPicker
          models={[
            {
              name: "octopus-mix",
              display_name: "Octopus Mix · 多模型协同",
              provider: "octopus",
            },
            { name: "minimax-m2.5", display_name: "MiniMax M2.5" },
          ]}
          value="octopus-mix"
          onChange={onChange}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: "选择模型" }));
    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    // models advertises octopus-mix → it classifies as Official (not Custom)
    expect(root.textContent ?? "").toContain("Octopus Mix");
  });
});
