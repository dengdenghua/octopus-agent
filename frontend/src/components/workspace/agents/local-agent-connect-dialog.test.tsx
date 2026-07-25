import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalAgentPartner } from "@/core/agents/api";
import type * as AgentsApi from "@/core/agents/api";
import { renderWithProviders } from "@/test/harness";

const apiMocks = vi.hoisted(() => ({
  doctor: vi.fn(),
  list: vi.fn(),
  probe: vi.fn(),
  register: vi.fn(),
}));

vi.mock("@/core/agents/api", async () => {
  const actual = (await vi.importActual("@/core/agents/api")) as typeof AgentsApi;
  return {
    ...actual,
    getLocalAgentPartnersDoctor: apiMocks.doctor,
    listLocalAgentPartners: apiMocks.list,
    probeLocalAgentPartner: apiMocks.probe,
    registerLocalAgentPartners: apiMocks.register,
  };
});

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

import {
  isValidPartnerAlias,
  LocalAgentConnectDialog,
  normalizePartnerAlias,
} from "./local-agent-connect-dialog";

function partner(
  id: string,
  overrides: Partial<LocalAgentPartner> = {},
): LocalAgentPartner {
  return {
    id,
    agent_id: `local_${id.replaceAll("-", "_")}`,
    name: id === "codebuddy-cli" ? "CodeBuddy CLI" : "Codex CLI",
    default_alias: id === "codebuddy-cli" ? "CodeBuddy 伙伴" : "Codex 伙伴",
    description: "本机 CLI 伙伴",
    detected: true,
    registered: false,
    status: "detected",
    effective_status: "ready",
    ready: true,
    setup_hint: "使用 CLI 自己的登录态。",
    ...overrides,
  };
}

const READY = partner("codebuddy-cli");
const REGISTERED = partner("codex-cli", {
  registered: true,
  status: "registered",
  effective_status: "registered",
});
const MISSING = partner("qoder-cli", {
  name: "Qoder CLI",
  detected: false,
  ready: false,
  status: "missing",
  effective_status: "missing",
  install_command: "npm install qoder-cli",
});

describe("LocalAgentConnectDialog", () => {
  beforeEach(() => {
    apiMocks.doctor.mockReset().mockResolvedValue(null);
    apiMocks.list.mockReset().mockResolvedValue([REGISTERED, MISSING, READY]);
    apiMocks.probe.mockReset();
    apiMocks.register.mockReset().mockResolvedValue({
      registered_count: 1,
      already_exists_count: 0,
    });
  });

  it("keeps the header and footer fixed while partner details scroll internally", async () => {
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const dialog = await screen.findByRole("dialog", { name: "接入本地伙伴" });
    expect(dialog).toHaveClass("overflow-hidden");
    expect(dialog.className).toContain("max-h-");

    const scrollRegion = dialog.querySelector(".overflow-y-auto");
    expect(scrollRegion).not.toBeNull();
    expect(
      await screen.findByRole("button", { name: "接入 1 个 Agent" }),
    ).toBeInTheDocument();
    expect(screen.getByText("可接入 1 个")).toBeInTheDocument();
  });

  it("uses one explicit selection control and only shows an alias for connectable partners", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const select = await screen.findByRole("button", {
      name: "取消选择 CodeBuddy CLI",
    });
    expect(select).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.queryByRole("button", { name: /选择 Codex CLI/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /选择 Qoder CLI/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "CodeBuddy CLI 名称" }),
    ).toBeEnabled();
    expect(
      screen.queryByRole("textbox", { name: "Codex CLI 名称" }),
    ).not.toBeInTheDocument();

    await user.click(select);
    expect(
      screen.getByRole("button", { name: "选择 CodeBuddy CLI" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.getByRole("button", { name: "接入 0 个 Agent" }),
    ).toBeDisabled();
  });

  it("submits the edited alias for the selected partner", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const alias = await screen.findByRole("textbox", {
      name: "CodeBuddy CLI 名称",
    });
    await user.clear(alias);
    await user.type(alias, "Buddy Build");
    await user.click(screen.getByRole("button", { name: "接入 1 个 Agent" }));

    await waitFor(() => expect(apiMocks.register).toHaveBeenCalled());
    expect(apiMocks.register.mock.calls[0]?.[0]).toEqual([
      { id: "codebuddy-cli", alias: "Buddy Build" },
    ]);
  });

  it("blocks aliases the backend would reject", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const alias = await screen.findByRole("textbox", {
      name: "CodeBuddy CLI 名称",
    });
    await user.clear(alias);
    await user.type(alias, "Buddy/Build");

    expect(alias).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText("仅支持文字、数字、空格、点、短横线和下划线"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "接入 1 个 Agent" }),
    ).toBeDisabled();
  });

  it("shows a recoverable empty state and refreshes both partner queries", async () => {
    const user = userEvent.setup();
    apiMocks.list.mockResolvedValue([]);
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const emptyCopy = await screen.findByText(
      "没有可接入的本地伙伴，请先安装对应本地工具",
    );
    const emptyState = emptyCopy.parentElement!;
    await user.click(
      within(emptyState).getByRole("button", { name: "重新检测" }),
    );

    await waitFor(() => expect(apiMocks.list).toHaveBeenCalledTimes(2));
    expect(apiMocks.doctor).toHaveBeenCalledTimes(2);
  });

  it("recovers from detection errors without reopening the dialog", async () => {
    const user = userEvent.setup();
    apiMocks.list
      .mockRejectedValueOnce(new Error("probe failed"))
      .mockResolvedValueOnce([READY]);
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    const errorState = await screen.findByRole("alert");
    await user.click(
      within(errorState).getByRole("button", { name: "重新检测" }),
    );

    expect(
      await screen.findByRole("button", { name: "取消选择 CodeBuddy CLI" }),
    ).toBeInTheDocument();
    expect(apiMocks.list).toHaveBeenCalledTimes(2);
    expect(apiMocks.doctor).toHaveBeenCalledTimes(2);
  });

  it("falls back to the provider icon when a remote logo fails", async () => {
    apiMocks.list.mockResolvedValue([
      partner("codebuddy-cli", {
        avatar_url: "https://invalid.example/codebuddy.svg",
      }),
    ]);
    renderWithProviders(
      <LocalAgentConnectDialog open onOpenChange={vi.fn()} />,
      { locale: "zh-CN" },
    );

    await screen.findByText("CodeBuddy CLI");
    const image = document.querySelector<HTMLImageElement>(
      'img[src*="invalid.example"]',
    );
    expect(image).not.toBeNull();
    fireEvent.error(image!);
    expect(
      document.querySelector('img[src*="invalid.example"]'),
    ).not.toBeInTheDocument();
  });
});

describe("local partner alias validation", () => {
  it("matches the backend character and fallback rules", () => {
    expect(isValidPartnerAlias("Buddy_伙伴-1.0")).toBe(true);
    expect(isValidPartnerAlias("Buddy/伙伴")).toBe(false);
    expect(normalizePartnerAlias("   ", "默认伙伴")).toBe("默认伙伴");
    expect(normalizePartnerAlias("  Buddy  ", "默认伙伴")).toBe("Buddy");
  });
});
