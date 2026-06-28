import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ClusterWorkbench, clusterProgress } from "./cluster-workbench";
import type { SwarmAgent, SwarmSession } from "./types";

function makeAgent(
  over: Partial<SwarmAgent> & { id: string; index: number; name: string },
): SwarmAgent {
  return {
    role: "调研员",
    motto: "稳准狠",
    avatarEmoji: "🤖",
    hue: 220,
    skills: [],
    task: "调研任务",
    status: "reasoning",
    progress: 0.4,
    ...over,
  };
}

const SESSION: SwarmSession = {
  id: "s1",
  title: "测试集群",
  status: "running",
  mode: "live",
  agents: [
    makeAgent({
      id: "a1",
      index: 0,
      name: "优伶",
      motto: "精准调研",
      status: "done",
      progress: 1,
      skills: ["web-search"],
      tokenUsed: 1200,
    }),
    makeAgent({ id: "a2", index: 1, name: "普朗", status: "reasoning", progress: 0.5 }),
    makeAgent({ id: "a3", index: 2, name: "唐墨", status: "pending", progress: 0 }),
  ],
  trace: [
    {
      id: "t1",
      agentId: "a1",
      timestamp: 1,
      kind: "search",
      title: "搜索 Qoder",
      url: "https://qoder.com",
    },
    { id: "t2", agentId: "a2", timestamp: 2, kind: "read", title: "阅读 Trae 文档" },
  ],
  deliverables: [],
};

describe("clusterProgress", () => {
  it("counts terminal as done, active as running, over total", () => {
    expect(clusterProgress(SESSION.agents)).toEqual({ done: 1, running: 1, total: 3 });
  });
});

describe("<ClusterWorkbench />", () => {
  it("renders each agent (card + tab) and a segmented progress bar", () => {
    render(<ClusterWorkbench session={SESSION} selectedAgentId="a1" />);
    // every agent shows in both the cluster card and the tab strip
    expect(screen.getAllByText("优伶").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("普朗").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("唐墨").length).toBeGreaterThanOrEqual(2);
    // progress: 1 of 3 terminal
    expect(screen.getByText("1/3")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "1");
    expect(bar).toHaveAttribute("aria-valuemax", "3");
  });

  it("shows the selected agent's detail + only its trace", () => {
    render(<ClusterWorkbench session={SESSION} selectedAgentId="a1" />);
    expect(screen.getByText(/精准调研/)).toBeInTheDocument(); // a1 motto
    expect(screen.getByText("web-search")).toBeInTheDocument(); // a1 skill chip
    expect(screen.getByText("搜索 Qoder")).toBeInTheDocument(); // a1 trace
    expect(screen.queryByText("阅读 Trae 文档")).not.toBeInTheDocument(); // a2 trace hidden
  });

  it("calls onSelectAgent when a cluster card is clicked", async () => {
    const onSelect = vi.fn();
    render(
      <ClusterWorkbench session={SESSION} selectedAgentId="a1" onSelectAgent={onSelect} />,
    );
    await userEvent.click(screen.getAllByText("唐墨")[0]);
    expect(onSelect).toHaveBeenCalledWith("a3");
  });

  it("falls back to the first agent when selectedAgentId is missing", () => {
    render(<ClusterWorkbench session={SESSION} />);
    expect(screen.getByText(/精准调研/)).toBeInTheDocument(); // first agent (优伶) detail
  });

  it("renders an empty state when the cluster has no agents", () => {
    render(<ClusterWorkbench session={{ ...SESSION, agents: [] }} />);
    expect(screen.getByText("集群尚未分配 agent")).toBeInTheDocument();
  });
});
