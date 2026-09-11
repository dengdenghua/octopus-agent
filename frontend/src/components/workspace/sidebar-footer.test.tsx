import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLocation } from "react-router-dom";

import type { Agent } from "@/core/agents";
import { ACTIVE_AGENT_KEY } from "@/core/agents/active";
import { renderWithProviders } from "@/test/harness";

const mocks = vi.hoisted(() => ({
  agentState: {
    agents: [] as Agent[],
    isLoading: false,
    isFetching: false,
    error: null as Error | null,
    refetch: vi.fn(),
  },
  logout: vi.fn(),
  credits: 999 as number | undefined,
}));

vi.mock("@/core/agents", () => ({
  useAgents: () => mocks.agentState,
  dedupePersonaAgentsByDisplayName: (agents: Agent[]) => agents,
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    user: { user_id: "user-1", email: "user@example.com" },
    logout: mocks.logout,
  }),
}));

vi.mock("@/core/oct/hooks", () => ({
  useOctLink: () => ({
    data: { credits: { surplusCredits: mocks.credits } },
  }),
}));

vi.mock("@/core/evolution/hooks", () => ({
  useEvolutionOverview: () => ({ data: null }),
}));

vi.mock("@/components/workspace/credits-center", () => ({
  CreditsCenterDialog: () => null,
}));

import { AgentAvatar, AgentFooter } from "./sidebar-footer";

function RouteProbe() {
  const location = useLocation();
  return (
    <output data-testid="route">{location.pathname + location.search}</output>
  );
}

beforeEach(() => {
  mocks.agentState.agents = [];
  mocks.agentState.isLoading = false;
  mocks.agentState.isFetching = false;
  mocks.agentState.error = null;
  mocks.agentState.refetch.mockReset();
  mocks.logout.mockReset();
  mocks.credits = 999;
  window.localStorage.clear();
});

describe("AgentAvatar", () => {
  it("resolves an API avatar to the backend origin", () => {
    const agent: Agent = {
      name: "researcher",
      display_name: "Researcher",
      description: "Research agent",
      avatar_url: "/api/agents/researcher/avatar",
      icon: "R",
      model: null,
      tool_groups: null,
    };

    const { container } = render(<AgentAvatar agent={agent} />);

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      expect.stringContaining("/api/agents/researcher/avatar"),
    );
  });

  it("falls back to the agent icon when a remote avatar fails", () => {
    const agent: Agent = {
      name: "remote_researcher",
      display_name: "Remote Researcher",
      description: "Remote agent",
      avatar_url: "https://invalid.example/avatar.svg",
      icon: "🟦",
      model: null,
      tool_groups: null,
    };

    const { container } = render(<AgentAvatar agent={agent} />);
    const image = container.querySelector("img");
    expect(image).not.toBeNull();
    fireEvent.error(image!);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByText("🟦")).toBeInTheDocument();
  });
});

describe("AgentFooter roster states", () => {
  it.each([undefined, 0])(
    "keeps the account entry usable with credits %s",
    async (credits) => {
      mocks.credits = credits;
      mocks.agentState.agents = [
        {
          name: "general",
          display_name: "Eve",
          description: "Long biography",
          model: null,
          tool_groups: [],
        },
      ];
      const user = userEvent.setup();
      renderWithProviders(<AgentFooter />, {
        initialRoute: "/workspace/realtime/new",
        locale: "zh-CN",
      });
      await user.click(
        screen.getByRole("button", { name: "Eve", exact: true }),
      );
      expect(screen.getByText("办公统筹")).toBeVisible();
      const account = screen.getByRole("menuitem", {
        name: /user@example.com/,
      });
      expect(account).not.toHaveTextContent("—");
      if (credits === 0) expect(account).toHaveTextContent("0");
      else expect(account).toHaveTextContent(/^user@example.com$/);
    },
  );
  it.each(["click", "Enter", "Space"])(
    "opens the requested profile with %s without switching the active role",
    async (activation) => {
      const user = userEvent.setup();
      mocks.agentState.agents = [
        {
          name: "general",
          display_name: "Eve",
          description: "助理",
          model: null,
          tool_groups: [],
        },
        {
          name: "coder",
          display_name: "Kane",
          description: "工程师",
          model: null,
          tool_groups: [],
        },
      ];
      window.localStorage.setItem(ACTIVE_AGENT_KEY, "general");
      renderWithProviders(
        <>
          <AgentFooter />
          <RouteProbe />
        </>,
        {
          initialRoute: "/workspace/realtime/new",
          locale: "zh-CN",
        },
      );
      await user.click(
        screen.getByRole("button", { name: "Eve", exact: true }),
      );
      const profileButton = screen.getByRole("button", {
        name: "查看 Kane 的资料",
      });
      expect(profileButton).toHaveTextContent("资料");
      if (activation === "click") {
        await user.click(profileButton);
      } else {
        screen.getByRole("menuitem", { name: /Kane/ }).focus();
        await user.keyboard("{ArrowRight}");
        expect(profileButton).toHaveFocus();
        await user.keyboard(activation === "Enter" ? "{Enter}" : " ");
      }
      expect(screen.getByTestId("route")).toHaveTextContent(
        "/workspace/agents?hud=1&surface=chat&agent=coder",
      );
      expect(window.localStorage.getItem(ACTIVE_AGENT_KEY)).toBe("general");
      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    },
  );

  it("shows a real loading state instead of a fake question-mark agent", () => {
    mocks.agentState.isLoading = true;
    mocks.agentState.isFetching = true;

    renderWithProviders(<AgentFooter />, {
      initialRoute: "/workspace/realtime/thread-1",
      locale: "zh-CN",
    });

    expect(
      screen.getByRole("button", { name: "正在加载智能体…" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("?")).not.toBeInTheDocument();
    expect(screen.queryByText("EchoAI")).not.toBeInTheDocument();
  });

  it("exposes a retry action when the roster request fails", async () => {
    const user = userEvent.setup();
    mocks.agentState.error = new Error("401 Unauthorized");

    renderWithProviders(<AgentFooter />, {
      initialRoute: "/workspace/realtime/thread-1",
      locale: "zh-CN",
    });

    await user.click(
      screen.getByRole("button", { name: "智能体列表加载失败" }),
    );
    expect(screen.getAllByText("智能体列表加载失败")).toHaveLength(2);

    await user.click(screen.getByRole("menuitem", { name: "重新加载" }));
    expect(mocks.agentState.refetch).toHaveBeenCalledTimes(1);
  });

  it("renders the backend persona once the roster is available", () => {
    mocks.agentState.agents = [
      {
        name: "general",
        display_name: "Eve",
        description: "通用智能助理",
        avatar_url: "/api/agents/general/avatar",
        icon: "",
        model: null,
        tool_groups: [],
      },
    ];

    renderWithProviders(<AgentFooter />, {
      initialRoute: "/workspace/realtime/thread-1",
      locale: "zh-CN",
    });

    expect(screen.getByRole("button", { name: "Eve" })).toBeInTheDocument();
    expect(screen.queryByText("EchoAI")).not.toBeInTheDocument();
  });
});
