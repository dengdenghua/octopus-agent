/**
 * Tests for the chat-input model picker — compact dropdown variant.
 *
 * Focus: classification (official vs custom) + selection plumbing.
 * We don't re-test Radix Tabs / DropdownMenu internals.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AllProviders } from "@/test/harness";

import { ModelPicker, type PickerModel } from "./model-picker";

const authState = vi.hoisted(() => ({
  isGuest: false,
  isAuthenticated: true,
}));

// Stub useOctLink — picker reads `link.oct_user_id` to auto-enable
// unconfigured models.
vi.mock("@/core/oct", () => ({
  useOctLink: () => ({ data: null }),
}));

// Picker's `useAuth()` is for read-only identity · stub with a
// minimal guest identity so the hook doesn't throw.
vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    isLoading: false,
    authStatus: { enabled: false, allow_registration: false },
    user: null,
    isAuthenticated: authState.isAuthenticated,
    isGuest: authState.isGuest,
    login: vi.fn(),
    guestLogin: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

beforeEach(() => {
  authState.isGuest = false;
  authState.isAuthenticated = true;
});

function withProviders(node: React.ReactNode) {
  // Test assertions reference zh-CN copy, so prime the I18nProvider to zh-CN.
  return <AllProviders locale="zh-CN">{node}</AllProviders>;
}

// Backwards-compat alias used in older tests.
const withRouter = withProviders;

// MODELS includes octopus-mix (official) plus several custom models.
// The official tab is active by default when octopus-mix is present.
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

  it("opens the dropdown with the official tab active by default", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByTestId("model-picker-trigger"));
    const menu = await screen.findByTestId("model-picker-menu");
    expect(menu).toBeInTheDocument();
    const officialTab = await screen.findByTestId("model-picker-tab-official");
    expect(officialTab).toHaveAttribute("data-state", "active");
    expect(screen.getByTestId("model-picker-tab-custom")).toBeInTheDocument();
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

  it("official tab shows Octopus Mix with multiplier", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    const allText = root.textContent ?? "";
    expect(allText).toContain("Octopus Mix");
    // MIX_META.multiplier is "Mix"
    expect(allText).toContain("Mix");
  });

  it("Octopus Mix carries the 推荐 badge", async () => {
    const user = userEvent.setup();
    setup("kimi-k2.5");
    await user.click(screen.getByRole("button", { name: "选择模型" }));
    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    const badges = root.querySelectorAll('[title="推荐"]');
    expect(badges.length).toBe(1);
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

  it("自定义 tab lists non-official models with provider hints", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    await user.click(screen.getByRole("tab", { name: "自定义" }));

    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByText("Claude Opus 4.6 (mirror)"),
    ).toBeInTheDocument();
    // Right-hint resolves "claude" → "Claude" provider label.
    expect(within(menu).getByText("Claude")).toBeInTheDocument();
  });

  it("自定义 tab shows 添加模型 CTA", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));
    await user.click(screen.getByRole("tab", { name: "自定义" }));

    const menu = await screen.findByRole("menu");
    expect(
      within(menu).getByRole("button", { name: /添加模型/ }),
    ).toBeInTheDocument();
  });

  it("clicking a custom row fires onChange", async () => {
    const user = userEvent.setup();
    const { onChange } = setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));
    await user.click(screen.getByRole("tab", { name: "自定义" }));

    const menu = await screen.findByRole("menu");
    await user.click(
      within(menu).getByText("Claude Opus 4.6 (mirror)").closest("button")!,
    );
    expect(onChange).toHaveBeenCalledWith("claude-opus-4-6-mirror");
  });

  it("guest users see disabled official models and can only select custom models", async () => {
    authState.isGuest = true;
    authState.isAuthenticated = false;
    const user = userEvent.setup();
    const { onChange } = setup("claude-opus-4-6-mirror");

    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const customTab = await screen.findByTestId("model-picker-tab-custom");
    expect(customTab).toHaveAttribute("data-state", "active");
    expect(screen.getByTestId("model-picker-tab-official")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "官方模型" }));
    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    const mixBtn = Array.from(root.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("Octopus Mix"),
    );
    expect(mixBtn).toBeTruthy();
    expect(mixBtn).toBeDisabled();
    expect(root.textContent ?? "").toContain("登录后可用");
    await user.click(mixBtn!);
    expect(onChange).not.toHaveBeenCalledWith("octopus-mix");

    await user.click(screen.getByRole("tab", { name: "自定义" }));
    const customBtn = Array.from(root.querySelectorAll("button")).find(
      (b) =>
        (b.textContent ?? "").includes("Claude Opus 4.6 (mirror)") &&
        !(b.textContent ?? "").includes("Mix"),
    );
    expect(customBtn).toBeTruthy();
    await user.click(customBtn!);
    expect(onChange).toHaveBeenCalledWith("claude-opus-4-6-mirror");
  });

  it("guest users do not see a disabled official model as the current trigger label", async () => {
    authState.isGuest = true;
    authState.isAuthenticated = false;
    // octopus-mix is an official model → guest fallback must swap it for the first custom model
    const { onChange } = setup("octopus-mix");

    const trigger = screen.getByRole("button", { name: "选择模型" });
    expect(await screen.findByText("Kimi K2.5")).toBeInTheDocument();
    expect(trigger).toHaveTextContent("Kimi K2.5");
    expect(trigger).not.toHaveTextContent("Octopus Mix");
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith("kimi-k2.5");
    });
  });

  it("trigger shows Octopus Mix label when that model is selected", () => {
    setup("octopus-mix");
    expect(screen.getByRole("button", { name: "选择模型" })).toHaveTextContent(
      "Octopus Mix",
    );
  });

  it("falls back to 自定义 tab when no official models exist", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      withRouter(
        <ModelPicker
          models={[{ name: "only-custom", display_name: "Only Custom" }]}
          value="only-custom"
          onChange={onChange}
        />,
      ),
    );
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const customTab = await screen.findByRole("tab", { name: "自定义" });
    expect(customTab).toHaveAttribute("data-state", "active");
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
