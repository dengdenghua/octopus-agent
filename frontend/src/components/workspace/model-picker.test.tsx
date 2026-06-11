/**
 * Tests for the chat-input model picker — compact dropdown variant.
 *
 * Focus: classification (official vs custom) + selection plumbing.
 * We don't re-test Radix Tabs / DropdownMenu internals.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AllProviders } from "@/test/harness";

import { ModelPicker, type PickerModel } from "./model-picker";

const authState = vi.hoisted(() => ({
  isGuest: false,
  isAuthenticated: true,
}));

// Stub useMoliliLink + useQueryClient consumers — picker now reads
// `link.molili_user_id` to auto-enable unconfigured models.
vi.mock("@/core/molili", () => ({
  useMoliliLink: () => ({ data: null }),
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
    smsLogin: vi.fn(),
    guestLogin: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));
const CATALOG = [
  { id: "minimax-m2.5", display_name: "MiniMax M2.5", multiplier: "0.2x", recommended: true },
  { id: "glm-4.7", display_name: "GLM-4.7", multiplier: "0.6x", recommended: true },
  { id: "kimi-k2.5", display_name: "Kimi K2.5", multiplier: "0.3x", recommended: false },
  { id: "deepseek-v3.2", display_name: "DeepSeek-V3.2", multiplier: "0.5x", recommended: false },
  { id: "qwen3-max", display_name: "Qwen3-Max", multiplier: "0.2x", recommended: false },
];

beforeEach(() => {
  authState.isGuest = false;
  authState.isAuthenticated = true;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: CATALOG }),
    }),
  );
});

function withProviders(node: React.ReactNode) {
  // Test assertions reference zh-CN copy, so prime the I18nProvider to zh-CN.
  return <AllProviders locale="zh-CN">{node}</AllProviders>;
}

// Backwards-compat alias used in older tests.
const withRouter = withProviders;

// Keep display_names aligned with the CURRENT OFFICIAL_META.displayName
// values (MiniMax M2.5 / GLM-4.7 / Kimi K2.5 / DeepSeek-V3.2 / Qwen3-Max).
// The component now routes a model to the "custom" tab if its
// display_name differs from the curated pack label · so mismatched
// names would make the "5 official rows" assertion fail even though
// the backend model is recognized by the regex.
const MODELS: PickerModel[] = [
  { name: "kimi-k2.5", display_name: "Kimi K2.5", model: "kimi" },
  { name: "minimax-m2.7", display_name: "MiniMax M2.5", model: "minimax" },
  { name: "glm-5", display_name: "GLM-4.7", model: "glm" },
  { name: "deepseek-v3.2", display_name: "DeepSeek-V3.2", model: "deepseek" },
  { name: "qwen3-max", display_name: "Qwen3-Max", model: "qwen" },
  // Implementation note.
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
    expect(
      screen.getByRole("button", { name: "选择模型" }),
    ).toHaveTextContent("Kimi K2.5");
  });

  it("opens the dropdown with the official tab active by default", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(screen.getByRole("button", { name: "选择模型" }));
    const officialTab = await screen.findByRole("tab", { name: "官方模型" });
    expect(officialTab).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("tab", { name: "自定义" })).toBeInTheDocument();
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

  it("renders all 5 official rows with multipliers", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    // Labels are nested spans · menu.textContent flattens them but
    // Radix Tabs content sits in a sibling of the menu container, so
    // scope at the dropdown root instead.
    const allText = (menu.parentElement ?? menu).textContent ?? "";
    for (const display of [
      "MiniMax M2.5",
      "GLM-4.7",
      "Kimi K2.5",
      "DeepSeek-V3.2",
      "Qwen3-Max",
    ]) {
      expect(allText).toContain(display);
    }
    // Multipliers come from OFFICIAL_META — minimax + qwen both 0.2x,
    // so we assert >=2 occurrences rather than exactly-one.
    expect(within(menu).getAllByText("0.2x").length).toBeGreaterThanOrEqual(2);
    expect(within(menu).getByText("0.6x")).toBeInTheDocument(); // glm
    // The current selection (Kimi K2.5) renders 0.3x in the header AND
    // again in the list, so we can't assert exactly-one.
    expect(within(menu).getAllByText("0.3x").length).toBeGreaterThanOrEqual(1);
  });

  it("MiniMax + GLM carry the 推荐 badge", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));
    const menu = await screen.findByRole("menu");
    // Implementation note.
    // visible text. Query by attribute at the dropdown root since
    // Tabs content is a sibling of the menu role.
    const root = menu.parentElement ?? menu;
    const badges = root.querySelectorAll('[title="推荐"]');
    expect(badges.length).toBe(2);
  });

  it("selecting an official row invokes onChange with the backend name", async () => {
    const user = userEvent.setup();
    const { onChange } = setup("kimi-k2.5");
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    // Click MiniMax row — its label is the curated "MiniMax M2.5" but
    // onChange must surface the backend name from MODELS.
    const menu = await screen.findByRole("menu");
    // Tabs content is a sibling of the menu · search the whole
    // dropdown portal. Label is in a nested span · find the button
    // via textContent.
    const root = menu.parentElement ?? menu;
    const miniMaxBtn = Array.from(
      root.querySelectorAll("button"),
    ).find((b) => (b.textContent ?? "").includes("MiniMax M2.5"));
    expect(miniMaxBtn).toBeTruthy();
    await user.click(miniMaxBtn!);

    expect(onChange).toHaveBeenCalledWith("minimax-m2.7");
  });

  it("自定义 tab lists non-official models with provider hints", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    await user.click(screen.getByRole("tab", { name: "自定义" }));

    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("Claude Opus 4.6 (mirror)")).toBeInTheDocument();
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

    const customTab = await screen.findByRole("tab", { name: "自定义" });
    expect(customTab).toHaveAttribute("data-state", "active");
    expect(screen.getByRole("tab", { name: "官方模型" })).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "官方模型" }));
    const menu = await screen.findByRole("menu");
    const root = menu.parentElement ?? menu;
    const miniMaxBtn = Array.from(root.querySelectorAll("button")).find((b) =>
      (b.textContent ?? "").includes("MiniMax M2.5"),
    );
    expect(miniMaxBtn).toBeTruthy();
    expect(miniMaxBtn).toBeDisabled();
    expect(root.textContent ?? "").toContain("登录后可用");
    await user.click(miniMaxBtn!);
    expect(onChange).not.toHaveBeenCalledWith("minimax-m2.7");

    await user.click(screen.getByRole("tab", { name: "自定义" }));
    const customBtn = Array.from(root.querySelectorAll("button")).find(
      (b) =>
        (b.textContent ?? "").includes("Claude Opus 4.6 (mirror)") &&
        !(b.textContent ?? "").includes("1.0x"),
    );
    expect(customBtn).toBeTruthy();
    await user.click(customBtn!);
    expect(onChange).toHaveBeenCalledWith("claude-opus-4-6-mirror");
  });

  it("header shows the curated displayName + multiplier of the current model", async () => {
    const user = userEvent.setup();
    setup("minimax-m2.7");
    await user.click(screen.getByRole("button", { name: "选择模型" }));

    const menu = await screen.findByRole("menu");
    // Tabs content (including the official tab's row for MiniMax) is
    // a sibling of the menu container, so walk up to the dropdown
    // root. The header shows the raw display_name ("MiniMax M2.7" in
    // the test MODELS) but the list row still shows the curated
    // "MiniMax M2.5" from OFFICIAL_META.
    const root = menu.parentElement ?? menu;
    const all = root.textContent ?? "";
    expect(all).toContain("MiniMax M2.5");
    expect(all).toContain("0.2x");
  });

  it("falls back to 自定义 tab when no official models exist", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ data: [] }),
    } as Response);
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
});
