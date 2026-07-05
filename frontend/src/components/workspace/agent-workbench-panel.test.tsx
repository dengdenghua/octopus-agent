import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import {
  AgentWorkbenchPanel,
  hasAgentWorkbenchContent,
} from "./agent-workbench-panel";
import type { LiveToolEvent } from "./live-tool-timeline";

vi.mock("@/components/workspace/terminal-panel", () => ({
  TerminalPanel: ({ cwd, sessionId }: { cwd?: string; sessionId: string }) => (
    <div data-testid="mock-terminal-panel">
      Terminal {sessionId} {cwd}
    </div>
  ),
}));

vi.mock("./live-preview-panel", () => ({
  LivePreviewPanel: ({
    previewUrl,
    htmlContent,
  }: {
    previewUrl?: string | null;
    htmlContent?: string;
  }) => (
    <div
      data-testid="mock-live-preview"
      data-preview-url={previewUrl ?? ""}
      data-has-srcdoc={htmlContent ? "true" : "false"}
    />
  ),
}));

vi.mock("./browser-preview-panel", () => ({
  BrowserPreviewPanel: () => <div data-testid="mock-browser-preview" />,
}));

function event(partial: Partial<LiveToolEvent>): LiveToolEvent {
  return {
    id: "event-1",
    name: "read_file",
    status: "done",
    startedAt: 1000,
    iteration: 0,
    ...partial,
  };
}

function renderWorkbench(ui: ReactElement) {
  return renderWithProviders(ui, { locale: "zh-CN" });
}

function expandSummarySection(name: RegExp) {
  const trigger = screen.getByRole("button", { name });
  if (trigger.getAttribute("aria-expanded") !== "true") {
    fireEvent.click(trigger);
  }
}

function listAfterSummaryLabel(label: string): HTMLElement {
  const labelElement = screen.getAllByText(label).find((element) => {
    const next = element.closest("div")?.nextElementSibling;
    return next instanceof HTMLElement && next.tagName.toLowerCase() === "ul";
  });
  expect(labelElement).toBeTruthy();
  return labelElement?.closest("div")?.nextElementSibling as HTMLElement;
}

describe("<AgentWorkbenchPanel />", () => {
  test("reports no workbench content for low-level transport events only", () => {
    expect(
      hasAgentWorkbenchContent([
        event({ id: "transport-1", name: "turn_request" }),
        event({ id: "transport-2", name: "response_stream" }),
      ]),
    ).toBe(false);
  });

  test("reports workbench content for visible work events", () => {
    expect(
      hasAgentWorkbenchContent([
        event({
          id: "search-1",
          name: "web_search",
          input: { query: "AI market" },
        }),
      ]),
    ).toBe(true);
  });

  test("renders an empty shell for low-level transport events only", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="subagents"
        events={[
          event({ id: "transport-1", name: "turn_request" }),
          event({ id: "transport-2", name: "response_stream" }),
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "主电脑 · 等待中" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Diff/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /终端/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /浏览器/ })).not.toBeInTheDocument();
    expect(
      screen.getByText("当前没有活跃中的主控执行过程。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("等待开机")).not.toBeInTheDocument();
  });

  test("renders the main agent workstation dock placeholder", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "read-1",
            name: "read_file",
            input: { path: "src/app.tsx" },
            output: "const value = 1;",
          }),
        ]}
      />,
    );

    expect(
      screen.getByRole("button", { name: "主电脑 · 已完成" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("工位")).not.toBeInTheDocument();
  });

  test("renders invited collaborators as workstation seats before they run", () => {
    const { container } = renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="agent"
        events={[]}
        rosterSeats={[
          {
            id: "general",
            name: "Eve",
            role: "tl",
            avatarUrl: "/api/agents/general/avatar",
          },
          { id: "codex-cli", name: "Codex CLI", role: "member" },
          { id: "claude-code", name: "Claude Code", role: "member" },
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: "Eve · 群主" })).toHaveAttribute(
      "title",
      "Eve · 群主",
    );
    expect(
      container.querySelector('button[aria-label="Eve · 群主"] img'),
    ).toHaveAttribute("src", "/api/agents/general/avatar");
    expect(screen.getByText("群主")).toBeInTheDocument();
    expect(screen.queryByText("工位")).not.toBeInTheDocument();
    const workbenchHeader = screen.getByRole("banner");
    expect(
      within(workbenchHeader).queryByRole("button", {
        name: "Codex CLI · 子电脑 · 在场",
      }),
    ).not.toBeInTheDocument();
    const bottomRail = screen.getByTestId("workstation-bottom-rail");
    const codexSeat = within(bottomRail).getByRole("button", {
      name: "Codex CLI · 子电脑 · 在场",
    });
    expect(codexSeat).toHaveAttribute("title", "Codex CLI · 子电脑 · 在场");
    expect(
      screen.getByRole("button", { name: "Claude Code · 子电脑 · 在场" }),
    ).toHaveAttribute("title", "Claude Code · 子电脑 · 在场");
    expect(screen.queryByText("Codex CLI")).not.toBeInTheDocument();
    expect(screen.queryByText("Claude Code")).not.toBeInTheDocument();
    expect(screen.queryByText("协作")).not.toBeInTheDocument();

    fireEvent.click(codexSeat);

    expect(screen.getAllByText("子电脑").length).toBeGreaterThan(0);
    expect(screen.getByText("子电脑待命")).toBeInTheDocument();
    expect(screen.getByText("活动轨迹")).toBeInTheDocument();
    expect(screen.getByText("已加入当前对话")).toBeInTheDocument();
    expect(screen.getByText("等待任务接管")).toBeInTheDocument();
    expect(screen.getByText("独立进程尚未开始")).toBeInTheDocument();
    expect(screen.getAllByText("Codex CLI").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("子电脑已就位，等待独立进程开始输出。").length,
    ).toBeGreaterThan(0);

    const mainComputerButton = screen.getByRole("button", {
      name: "主电脑 · 等待中",
    });
    expect(mainComputerButton).toHaveClass("border-amber-500/40");

    fireEvent.click(mainComputerButton);

    expect(screen.queryByText("子电脑待命")).not.toBeInTheDocument();
    expect(screen.getByText("暂无子智能体")).toBeInTheDocument();

    fireEvent.click(codexSeat);

    fireEvent.click(screen.getByRole("button", { name: "主电脑" }));

    expect(screen.queryByText("子电脑待命")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Eve · 群主" }),
    ).toBeInTheDocument();
  });

  test("uses the leader avatar for the main workstation in solo mode", () => {
    const { container } = renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="agent"
        events={[]}
        rosterSeats={[
          {
            id: "general",
            name: "Eve",
            role: "tl",
            avatarUrl: "/api/agents/general/avatar",
          },
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: "Eve" })).toHaveAttribute(
      "title",
      "Eve",
    );
    expect(
      container.querySelector('button[aria-label="Eve"] img'),
    ).toHaveAttribute("src", "/api/agents/general/avatar");
    expect(screen.queryByText("群主")).not.toBeInTheDocument();
    expect(screen.queryByText("工位")).not.toBeInTheDocument();
  });

  test("renders dispatched subagent seats before lifecycle events arrive", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "parent-call-1",
            name: "call_agent_parallel",
            status: "running",
            input: {
              specs: [
                { agent_id: "researcher", prompt: "pricing lane" },
                { agent_id: "reviewer", prompt: "risk lane" },
                { agent_id: "writer", prompt: "summary lane" },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.getByTitle("researcher: pricing lane")).toBeInTheDocument();
    expect(screen.getByTitle("reviewer: risk lane")).toBeInTheDocument();
    const writerSeat = screen.getByTitle("writer: summary lane");
    expect(writerSeat).toBeInTheDocument();

    fireEvent.click(writerSeat);

    expect(screen.getAllByText("writer").length).toBeGreaterThan(0);
    expect(screen.getByText("summary lane")).toBeInTheDocument();
  });

  test("keeps the main workstation status independent from subagent failures", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "main-approval",
            name: "write_text_file",
            status: "waiting_approval",
            input: { path: "docs/notes.md" },
          }),
          event({
            id: "agent-error",
            name: "read_file",
            status: "error",
            parentToolUseId: "dispatch-1",
            subAgentRole: "reviewer",
            subagentCodename: "Review-03",
            input: { path: "missing/replay.json" },
            output: { error: "Replay artifact was not found" },
          }),
        ]}
      />,
    );

    expect(screen.getByTitle("主电脑 · 待确认")).toBeInTheDocument();
    expect(screen.queryByTitle("主电脑 · 遇到问题")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "查看 Review-03 独立进程" }),
    );

    expect(screen.getByText("Agent 集群 - 独立进程")).toBeInTheDocument();
    expect(screen.getAllByText("异常").length).toBeGreaterThan(0);
  });

  test("surfaces call_agent_parallel result outputs and failures", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "parent-call-1",
            name: "call_agent_parallel",
            status: "done",
            input: {
              specs: [
                { agent_id: "researcher", prompt: "pricing lane" },
                { agent_id: "reviewer", prompt: "risk lane" },
              ],
            },
            output: {
              ok: true,
              partial: true,
              successes: [
                {
                  agent_id: "researcher",
                  spec_index: 0,
                  task_label: "pricing lane",
                  output: "Pricing lane result is ready.",
                  iteration_count: 4,
                },
              ],
              failures: [
                {
                  agent_id: "reviewer",
                  spec_index: 1,
                  task_label: "risk lane",
                  error: "ROUND_CAP_EXCEEDED",
                  error_type: "round_cap_exceeded",
                  partial_output: "Risk lane partial notes.",
                  rounds_completed: 25,
                  round_cap_exceeded: true,
                },
              ],
            },
          }),
        ]}
      />,
    );

    expandSummarySection(/子智能体/);

    expect(
      screen.getByText("Pricing lane result is ready."),
    ).toBeInTheDocument();
    expect(screen.getByText("ROUND_CAP_EXCEEDED")).toBeInTheDocument();
    expect(screen.getAllByText("1/2 已完成").length).toBeGreaterThan(0);
    expect(screen.getByText("1 异常")).toBeInTheDocument();
    expect(screen.getByText(/失败 lane: risk lane/)).toBeInTheDocument();
  });

  test("hides the workstation dock on tool tabs", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="terminal"
        events={[
          event({
            id: "shell-1",
            name: "shell_command",
            input: { command: "pnpm typecheck", cwd: "F:\\repo" },
            output: "Done in 10s",
          }),
        ]}
      />,
    );

    expect(screen.getByTestId("mock-terminal-panel")).toBeInTheDocument();
    expect(screen.queryByText("工位")).not.toBeInTheDocument();
  });

  test("renders readable work steps and selected tool details", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({ id: "transport-1", name: "stream_connection" }),
          event({
            id: "read-1",
            name: "read_file",
            input: { path: "src/app.tsx" },
            output: "const value = 1;",
          }),
          event({
            id: "shell-1",
            name: "shell_command",
            status: "running",
            startedAt: 2000,
            input: { command: "npm run typecheck" },
          }),
          event({
            id: "child-1",
            name: "grep",
            parentToolUseId: "shell-1",
            input: { pattern: "Agent Workspace" },
          }),
        ]}
      />,
    );

    expect(screen.getByRole("tablist", { name: /看板/ })).toBeInTheDocument();
    expandSummarySection(/进展/);
    expect(
      screen.getAllByText("Phase 2: 执行与收集证据").length,
    ).toBeGreaterThan(0);
    // 电脑视图现在仅显示子智能体，主agent的操作记录在概要页中
    fireEvent.click(screen.getByText("电脑视图"));
    expect(screen.getByText("暂无子智能体")).toBeInTheDocument();
    expect(screen.getByTitle("主电脑 · 执行任务中...")).toBeInTheDocument();
  });

  test("groups screen frames by phase while keeping phase titles visible", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "read-server",
            name: "read_file",
            input: { path: "src/context.ts" },
          }),
          event({
            id: "snapshot-1",
            name: "todo_write",
            startedAt: 1200,
            input: {
              workbenchSnapshot: {
                schemaVersion: 2,
                version: 1,
                status: "running",
                phases: [
                  {
                    id: "phase-read",
                    index: 1,
                    total: 2,
                    title: "Phase 1: Read context",
                    status: "running",
                    activeItemId: "read-server",
                  },
                  {
                    id: "phase-test",
                    index: 2,
                    total: 2,
                    title: "Phase 2: Run tests",
                    status: "pending",
                  },
                ],
                currentPhaseId: "phase-read",
                currentItemId: "read-server",
                updatedAt: "2026-01-01T00:00:00.000Z",
              },
            },
          }),
          event({
            id: "shell-server",
            name: "shell_command",
            status: "running",
            startedAt: 2000,
            input: { command: "pnpm test" },
          }),
          event({
            id: "snapshot-2",
            name: "todo_write",
            startedAt: 2200,
            input: {
              workbenchSnapshot: {
                schemaVersion: 2,
                version: 2,
                status: "running",
                phases: [
                  {
                    id: "phase-read",
                    index: 1,
                    total: 2,
                    title: "Phase 1: Read context",
                    status: "done",
                  },
                  {
                    id: "phase-test",
                    index: 2,
                    total: 2,
                    title: "Phase 2: Run tests",
                    status: "running",
                    activeItemId: "shell-server",
                  },
                ],
                currentPhaseId: "phase-test",
                currentItemId: "shell-server",
                updatedAt: "2026-01-01T00:00:01.000Z",
              },
            },
          }),
        ]}
      />,
    );

    expandSummarySection(/进展/);

    expect(screen.getByText(/Phase 1: Read context/)).toBeInTheDocument();
    expect(screen.getByText(/Phase 2: Run tests/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("电脑视图"));

    expect(screen.getByText("暂无子智能体")).toBeInTheDocument();
  });

  test("shows verification-required audit as waiting instead of many failed reads", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "read-package",
            name: "read_file",
            status: "done",
            input: { path: "package.json" },
          }),
          event({
            id: "read-context",
            name: "read_file",
            status: "done",
            startedAt: 1200,
            input: { path: "src/context.tsx" },
          }),
          event({
            id: "verify-required",
            name: "verification:manual",
            status: "error",
            startedAt: 2000,
            input: { command: "verification required" },
            output: {
              summary:
                "Code changes were produced but no verification step was recorded before final answer.",
            },
          }),
        ]}
      />,
    );

    expandSummarySection(/进展/);

    expect(
      screen.getByText(/Phase 1: 理解任务与准备上下文/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Phase 2: 整理结果与交付/),
    ).toBeInTheDocument();
    expect(screen.getByTitle("主电脑 · 待确认")).toBeInTheDocument();
    expect(screen.queryByTitle("主电脑 · 遇到问题")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("电脑视图"));
    expect(screen.getByText("暂无子智能体")).toBeInTheDocument();
  });

  test("shows recovered tool failures as warnings instead of failing the phase", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "read-package",
            name: "read_file",
            status: "done",
            input: { path: "frontend/package.json" },
          }),
          event({
            id: "read-page-failed",
            name: "read_file",
            status: "error",
            startedAt: 1200,
            input: { path: "frontend/src/app/workspace/page.tsx" },
            output:
              "(工具失败) status=failed error=TypeError\n请在下一轮 Thought 中分析失败原因，然后换一种方式重试",
          }),
          event({
            id: "fallback-read",
            name: "ipython",
            status: "done",
            startedAt: 1400,
            input: { command: "read via pathlib" },
            output: "frontend/src/app/workspace/page.tsx",
          }),
        ]}
        hasAnswer
        runSettled
      />,
    );

    expandSummarySection(/进展/);

    expect(
      screen.getByText(/Phase 1: 理解任务与准备上下文/),
    ).toBeInTheDocument();
    expect(screen.getByTitle("主电脑 · 已完成")).toBeInTheDocument();
    expect(screen.queryByTitle("主电脑 · 遇到问题")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("电脑视图"));
    expect(screen.getByText("暂无子智能体")).toBeInTheDocument();
  });

  test("shows only observed context categories in the summary", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "read-context-1",
            name: "read_file",
            input: { path: "src/context.ts" },
            output: "export const context = true;",
          }),
          event({
            id: "write-context-1",
            name: "write_file",
            startedAt: 1500,
            input: {
              changes: [
                { path: "reports/market_report.md", op: "create" },
                { path: "scripts/analyze.py", op: "create" },
              ],
            },
          }),
          event({
            id: "todo-context-1",
            name: "todo_write",
            startedAt: 1750,
            input: {
              todos: [
                {
                  content: "Draft a context plan",
                  status: "pending",
                },
              ],
            },
          }),
          event({
            id: "search-context-1",
            name: "web_search",
            startedAt: 2000,
            input: { query: "AI market" },
            output: {
              results: [
                {
                  title: "AI Market Size Report",
                  url: "https://example.com/ai-market-size",
                  snippet: "Market sizing overview",
                },
                {
                  title: "Industry Forecast",
                  url: "https://research.example.org/forecast",
                },
              ],
            },
          }),
          event({
            id: "search-context-2",
            name: "web_search",
            startedAt: 2250,
            input: { query: "sleep tech" },
            output:
              '(real tool execution succeeded) web_search\n{"query":"sleep tech","backend":"ddg","results":[{"title":"Eight Sleep raises $50M","url":"https://techcrunch.com/eight-sleep-funding","snippet":"Funding news"},{"title":"Oura Ring 5 review","url":"https://www.tomsguide.com/reviews/oura-ring-5"}]}',
          }),
          event({
            id: "search-context-3",
            name: "web_search",
            startedAt: 2350,
            input: {
              query: "企业级AI Agent工作流自动化市场规模 2025 2026",
            },
            output:
              '(real tool execution succeeded) web_search\n{"query": "企业级AI Agent工作流自动化市场规模 2025 2026", "backend": "ddg", "results": [{"title": "企业 AI Agent 落地现状深度调研：从技术 Demo 到&quot;数字员工&quot;规模化实战【2026】 | QubitTool", "url": "https://qubittool.com/zh/blog/enterprise-ai-agent-status-2026", "snipp …(已截断)',
          }),
          event({
            id: "shell-context-1",
            name: "shell_command",
            startedAt: 2500,
            input: { command: "pnpm typecheck" },
            output: "Done in 10s",
          }),
        ]}
      />,
    );

    expandSummarySection(/上下文/);

    expect(screen.getByText("\u4e0a\u4e0b\u6587")).toBeInTheDocument();
    expect(screen.queryByText("Repo Wiki")).not.toBeInTheDocument();
    expect(screen.queryByText("\u77e5\u8bc6\u5361")).not.toBeInTheDocument();
    expect(screen.queryByText("\u8bb0\u5fc6")).not.toBeInTheDocument();
    expect(screen.queryByText("todo_write")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /\u5f85\u529e plan/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "\u7ec8\u7aef 1 \u6761\u6765\u6e90",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "\u5176\u4ed6 1 \u6761\u6765\u6e90",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("context.ts")).toBeInTheDocument();
    expect(screen.getByText("market_report.md")).toBeInTheDocument();
    expect(screen.getByText("analyze.py")).toBeInTheDocument();
    expect(screen.getByText("MD")).toBeInTheDocument();
    expect(screen.getByText("PY")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", {
        name: "\u641c\u7d22/\u7f51\u9875 5 \u6761\u6765\u6e90",
      }),
    );
    expect(screen.getByText("AI Market Size Report")).toBeInTheDocument();
    expect(
      screen.queryByText("https://example.com/ai-market-size"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Industry Forecast")).toBeInTheDocument();
    expect(screen.getByText("Eight Sleep raises $50M")).toBeInTheDocument();
    expect(
      screen.queryByText("https://techcrunch.com/eight-sleep-funding"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Oura Ring 5 review")).toBeInTheDocument();
    expect(
      screen.getByText(
        '企业 AI Agent 落地现状深度调研：从技术 Demo 到"数字员工"规模化实战【2026】 | QubitTool',
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(
        "https://qubittool.com/zh/blog/enterprise-ai-agent-status-2026",
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("AI market")).not.toBeInTheDocument();
    expect(screen.queryByText("sleep tech")).not.toBeInTheDocument();
  });

  test("surfaces real sub-agents as task cards", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="subagents"
        events={[
          event({
            id: "agent-1",
            name: "subagent_spawned",
            agentId: "agent-1",
            agentName: "Researcher",
            subAgentRole: "researcher",
            subagentCodename: "Spark-01",
            thought: "Collect background sources",
            status: "running",
          }),
          event({
            id: "agent-2",
            name: "subagent_finished",
            agentId: "agent-2",
            agentName: "Writer",
            subAgentRole: "writer",
            subagentCodename: "Spark-02",
            observation: "Draft completed",
            status: "done",
            startedAt: 2000,
          }),
        ]}
      />,
    );

    // Summary page shows agent labels (codenames)
    expect(
      screen.queryByRole("tab", { name: "\u5b50\u667a\u80fd\u4f53" }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Spark-01").length).toBeGreaterThan(0);
  });

  test("shows the assistant badge only while the spawn event is focused", async () => {
    const spawn = event({
      id: "spawn-1",
      name: "subagent",
      lifecycle: "spawned",
      status: "running",
      parentToolUseId: "parent-call-1",
      agentId: "designer-a",
      subAgentRole: "designer",
      subagentCodename: "Spark-Design",
      thought: "Create the interaction design direction",
    });
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel events={[spawn]} />,
    );

    expect(screen.getByText("Agent 集群 - 创建助手")).toBeInTheDocument();
    expect(screen.getAllByText("Spark-Design").length).toBeGreaterThan(0);

    rerender(
      <AgentWorkbenchPanel
        events={[
          spawn,
          event({
            id: "read-1",
            name: "read_file",
            status: "running",
            parentToolUseId: "parent-call-1",
            subAgentRole: "designer",
            startedAt: 2000,
            input: { path: "design.md" },
          }),
        ]}
      />,
    );

    await waitFor(() => {
      expect(
        screen.queryByText("Agent 集群 - 创建助手"),
      ).not.toBeInTheDocument();
    });
    expect(screen.queryByRole("tab", { name: /Diff/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /终端/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /浏览器/ })).not.toBeInTheDocument();
  });

  test("opens the focused sub-agent independent process view", async () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        events={[
          event({
            id: "agent-1-spawn",
            name: "subagent_spawned",
            agentId: "agent-1",
            agentName: "Researcher",
            subAgentRole: "researcher",
            subagentCodename: "Spark-01",
            status: "running",
          }),
          event({
            id: "agent-1-read",
            name: "read_file",
            agentId: "agent-1",
            subAgentRole: "researcher",
            input: { path: "research.md" },
          }),
          event({
            id: "agent-2-spawn",
            name: "subagent_spawned",
            agentId: "agent-2",
            agentName: "Writer",
            subAgentRole: "writer",
            subagentCodename: "Spark-02",
            status: "running",
            startedAt: 2000,
          }),
          event({
            id: "agent-2-read",
            name: "read_file",
            agentId: "agent-2",
            subAgentRole: "writer",
            input: { path: "writer.md" },
            startedAt: 2100,
          }),
        ]}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("writer.md")).toBeInTheDocument();
    });
    expect(screen.queryByText("research.md")).not.toBeInTheDocument();
  });

  test("keeps the summary view when the focus intent asks for it", async () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        focusedAgentView="summary"
        events={[
          event({
            id: "agent-2-spawn",
            name: "subagent_spawned",
            agentId: "agent-2",
            agentName: "Writer",
            subAgentRole: "writer",
            subagentCodename: "Spark-02",
            status: "running",
          }),
          event({
            id: "agent-2-read",
            name: "read_file",
            agentId: "agent-2",
            subAgentRole: "writer",
            input: { path: "writer.md" },
            startedAt: 2000,
          }),
        ]}
      />,
    );

    // The intent must not force the computer screen open.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "概要" })).toHaveClass(
        "border-foreground/70",
      );
    });
    expect(
      screen.queryByText("Agent 集群 - 独立进程"),
    ).not.toBeInTheDocument();

    // The sub-agent was still selected: switching to the computer view lands
    // straight on its independent process.
    fireEvent.click(screen.getByRole("button", { name: "电脑视图" }));
    await waitFor(() => {
      expect(screen.getByText("Agent 集群 - 独立进程")).toBeInTheDocument();
    });
    expect(screen.getByText("writer.md")).toBeInTheDocument();
  });

  test("consumes the focus intent once and stays on the main computer after snapshot churn", async () => {
    const focusEvents = [
      event({
        id: "agent-2-spawn",
        name: "subagent_spawned",
        agentId: "agent-2",
        agentName: "Writer",
        subAgentRole: "writer",
        subagentCodename: "Spark-02",
        status: "running",
      }),
      event({
        id: "agent-2-read",
        name: "read_file",
        agentId: "agent-2",
        subAgentRole: "writer",
        input: { path: "writer.md" },
        startedAt: 2000,
      }),
    ];
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel focusedAgentId="agent-2" events={focusEvents} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Agent 集群 - 独立进程")).toBeInTheDocument();
    });

    // User navigates back to the main computer while the run streams.
    fireEvent.click(screen.getByTitle("切回主电脑"));
    await waitFor(() => {
      expect(
        screen.queryByText("Agent 集群 - 独立进程"),
      ).not.toBeInTheDocument();
    });

    // Streaming churn rebuilds agentTiles with a fresh identity; the stale
    // focus intent must not yank the user back to the sub-agent view.
    rerender(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        events={[
          ...focusEvents,
          event({
            id: "agent-2-read-2",
            name: "read_file",
            agentId: "agent-2",
            subAgentRole: "writer",
            status: "running",
            input: { path: "writer-2.md" },
            startedAt: 2200,
          }),
        ]}
      />,
    );
    expect(
      screen.queryByText("Agent 集群 - 独立进程"),
    ).not.toBeInTheDocument();
  });

  test("a bumped nonce re-applies a repeat focus intent for the same agent", async () => {
    const focusEvents = [
      event({
        id: "agent-2-spawn",
        name: "subagent_spawned",
        agentId: "agent-2",
        agentName: "Writer",
        subAgentRole: "writer",
        subagentCodename: "Spark-02",
        status: "running",
      }),
      event({
        id: "agent-2-read",
        name: "read_file",
        agentId: "agent-2",
        subAgentRole: "writer",
        input: { path: "writer.md" },
        startedAt: 2000,
      }),
    ];
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        focusedAgentView="summary"
        focusedAgentNonce={1}
        events={focusEvents}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "概要" })).toHaveClass(
        "border-foreground/70",
      );
    });
    expect(
      screen.queryByText("Agent 集群 - 独立进程"),
    ).not.toBeInTheDocument();

    // Same agent, second emission (查看电脑 right after 查看过程 on one row): the
    // nonce bump makes it a fresh intent instead of being swallowed by the
    // consume-once guard.
    rerender(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        focusedAgentView="screen"
        focusedAgentNonce={2}
        events={focusEvents}
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("Agent 集群 - 独立进程")).toBeInTheDocument();
    });
    expect(screen.getByText("writer.md")).toBeInTheDocument();
  });

  test("keeps a manually selected replay frame while the snapshot updates", async () => {
    const baseEvents = [
      event({
        id: "server-phases:turn-1",
        name: "todo_write",
        status: "running",
        input: {
          items: [
            { content: "Phase 1: Research", status: "in_progress" },
            { content: "Phase 2: Write up", status: "pending" },
          ],
        },
      }),
      event({
        id: "agent-2-spawn",
        name: "subagent_spawned",
        agentId: "agent-2",
        agentName: "Writer",
        subAgentRole: "writer",
        subagentCodename: "Spark-02",
        status: "running",
      }),
      event({
        id: "agent-2-step-1",
        name: "read_file",
        agentId: "agent-2",
        subAgentRole: "writer",
        status: "done",
        input: { path: "history.md" },
        startedAt: 2000,
      }),
      event({
        id: "agent-2-step-2",
        name: "read_file",
        agentId: "agent-2",
        subAgentRole: "writer",
        status: "running",
        input: { path: "current.md" },
        startedAt: 2100,
      }),
    ];
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel focusedAgentId="agent-2" events={baseEvents} />,
    );

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /history\.md/ }),
      ).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /history\.md/ }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /history\.md/ })).toHaveClass(
        "border-l-primary",
      );
    });

    // A streaming delta rebuilds every snapshot object; the manual pick only
    // resets when the block actually leaves the sub-agent's block list.
    rerender(
      <AgentWorkbenchPanel
        focusedAgentId="agent-2"
        events={[
          ...baseEvents,
          event({
            id: "agent-2-step-3",
            name: "read_file",
            agentId: "agent-2",
            subAgentRole: "writer",
            status: "running",
            input: { path: "next.md" },
            startedAt: 2200,
          }),
        ]}
      />,
    );
    expect(screen.getByRole("button", { name: /history\.md/ })).toHaveClass(
      "border-l-primary",
    );
  });

  test("renders a header close button that invokes onClose", () => {
    const onClose = vi.fn();
    renderWorkbench(
      <AgentWorkbenchPanel
        onClose={onClose}
        events={[
          event({
            id: "read-1",
            name: "read_file",
            input: { path: "src/app.tsx" },
          }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  test("renders the deployed site in the browser tab once the run settles", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="browser"
        hasAnswer
        runSettled
        resultPreviewUrl="https://demo.vercel.app"
        events={[
          event({
            id: "read-1",
            name: "read_file",
            input: { path: "src/app.tsx" },
            output: "const value = 1;",
          }),
        ]}
      />,
    );

    expect(screen.getByTestId("mock-live-preview")).toHaveAttribute(
      "data-preview-url",
      "https://demo.vercel.app",
    );
    expect(
      screen.queryByTestId("mock-browser-preview"),
    ).not.toBeInTheDocument();
  });

  test("prefers the live inline preview while streaming and can switch to the deployed site", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="browser"
        resultPreviewUrl="https://demo.vercel.app"
        browserPreviewBlocks={{ html: "<div>hi</div>", css: "", js: "" }}
        events={[
          event({
            id: "read-1",
            name: "read_file",
            status: "running",
            input: { path: "src/app.tsx" },
          }),
        ]}
      />,
    );

    const preview = screen.getByTestId("mock-live-preview");
    expect(preview).toHaveAttribute("data-preview-url", "");
    expect(preview).toHaveAttribute("data-has-srcdoc", "true");

    fireEvent.click(screen.getByRole("button", { name: "已部署" }));
    expect(screen.getByTestId("mock-live-preview")).toHaveAttribute(
      "data-preview-url",
      "https://demo.vercel.app",
    );
  });

  test("uses server workspace focus as the default workbench tab", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "server-phases:turn-1",
            name: "todo_write",
            status: "running",
            input: {
              source: "turn.phases",
              workspaceFocus: {
                itemId: "file-change-1",
                view: "diff",
                title: "Editing src/app.ts",
              },
              items: [
                {
                  content: "Phase 1: Patch UI",
                  status: "in_progress",
                  activeItemId: "file-change-1",
                },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.getByRole("tab", { name: "Diff" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("keeps explicit activeTab ahead of server workspace focus", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="terminal"
        events={[
          event({
            id: "server-phases:turn-1",
            name: "todo_write",
            status: "running",
            input: {
              source: "turn.phases",
              workspaceFocus: {
                itemId: "file-change-1",
                view: "diff",
                title: "Editing src/app.ts",
              },
              items: [
                {
                  content: "Phase 1: Patch UI",
                  status: "in_progress",
                  activeItemId: "file-change-1",
                },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.queryByRole("tab", { name: "CLI" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "终端" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("tab", { name: "Diff" })).not.toBeInTheDocument();
  });

  test("maps terminal workspace focus to the terminal tab", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        events={[
          event({
            id: "shell-1",
            name: "shell_command",
            status: "running",
            input: { command: "pnpm test" },
          }),
          event({
            id: "server-phases:turn-1",
            name: "todo_write",
            status: "running",
            input: {
              source: "turn.phases",
              workspaceFocus: {
                itemId: "shell-1",
                view: "terminal",
                title: "Running tests",
              },
              items: [
                {
                  content: "Phase 1: Verify",
                  status: "in_progress",
                  activeItemId: "shell-1",
                },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.getByRole("tab", { name: "终端" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("keeps the subagent tab hidden while preserving summary observability", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="subagents"
        events={[
          event({
            id: "parent-call-1",
            name: "call_agent_parallel",
            status: "running",
            input: {
              specs: [{ agent_id: "researcher", prompt: "pricing lane" }],
            },
          }),
          event({
            id: "spawn-1",
            name: "subagent",
            lifecycle: "spawned",
            status: "running",
            parentToolUseId: "parent-call-1",
            agentId: "researcher-a",
            subAgentRole: "researcher",
            subagentCodename: "Spark-01",
            thought: "Research lane: collect pricing signals",
          }),
          event({
            id: "bb-1",
            name: "bb_write",
            status: "done",
            parentToolUseId: "parent-call-1",
            subAgentRole: "researcher",
            startedAt: 2000,
            input: { key: "market.pricing" },
          }),
          event({
            id: "write-1",
            name: "write_file",
            status: "done",
            parentToolUseId: "parent-call-1",
            subAgentRole: "researcher",
            startedAt: 3000,
            input: { path: "reports/pricing.md" },
          }),
          event({
            id: "finish-1",
            name: "subagent",
            lifecycle: "finished",
            status: "done",
            parentToolUseId: "parent-call-1",
            agentId: "researcher-a",
            subAgentRole: "researcher",
            subagentCodename: "Spark-01",
            durationMs: 1500,
            filesTouched: ["reports/pricing.md"],
            startedAt: 4000,
          }),
        ]}
      />,
    );

    expect(
      screen.queryByRole("tab", { name: "\u5b50\u667a\u80fd\u4f53" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTitle("主电脑 · 执行任务中...")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "查看主电脑" }),
    ).toBeInTheDocument();
  });

  test("renders diff output as an Agent computer inner page", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="diff"
        hasAnswer
        runSettled
        events={[
          event({
            id: "write-1",
            name: "write_file",
            input: { path: "src/app.tsx" },
            output: {
              diff: "--- a/src/app.tsx\n+++ b/src/app.tsx\n@@\n-old\n+new",
            },
          }),
        ]}
      />,
    );

    expect(screen.getByRole("tab", { name: "Diff" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByText("+++ b/src/app.tsx")).toBeInTheDocument();
    expect(screen.getByText("+new")).toBeInTheDocument();
    expect(screen.queryByText("Agent 01")).not.toBeInTheDocument();
  });

  test("keeps diff output hidden until the answer finishes", () => {
    const events = [
      event({
        id: "write-1",
        name: "write_file",
        input: { path: "src/app.tsx" },
        output: {
          diff: "--- a/src/app.tsx\n+++ b/src/app.tsx\n@@\n-old\n+new",
        },
      }),
    ];
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel activeTab="diff" events={events} />,
    );

    expect(screen.getByRole("tab", { name: "Diff" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByText("+++ b/src/app.tsx")).not.toBeInTheDocument();
    expect(screen.queryByText("+new")).not.toBeInTheDocument();

    rerender(
      <AgentWorkbenchPanel
        activeTab="diff"
        hasAnswer
        runSettled
        events={events}
      />,
    );

    expect(screen.getByText("+++ b/src/app.tsx")).toBeInTheDocument();
    expect(screen.getByText("+new")).toBeInTheDocument();
  });

  test("defers generated artifacts and changed files while the answer streams", () => {
    const events = [
      event({
        id: "create-1",
        name: "write_file",
        input: {
          changes: [
            {
              path: "reports/nas_market_research_plan.md",
              op: "create",
              diff: [
                "--- /dev/null",
                "+++ b/reports/nas_market_research_plan.md",
                "@@ -0,0 +1,2 @@",
                "+# Plan",
                "+body",
              ].join("\n"),
            },
          ],
        },
      }),
      event({
        id: "edit-1",
        name: "edit_file",
        input: {
          changes: [
            {
              path: "src/app.tsx",
              op: "update",
              diff: "--- a/src/app.tsx\n+++ b/src/app.tsx\n@@\n-old\n+new",
            },
          ],
        },
      }),
    ];
    const generatedLabel = "\u751f\u6210\u4ea7\u7269";
    const changedLabel = "\u53d8\u66f4\u6587\u4ef6";
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel events={events} />,
    );

    expect(screen.queryByText(generatedLabel)).not.toBeInTheDocument();
    expect(screen.queryByText(changedLabel)).not.toBeInTheDocument();

    rerender(<AgentWorkbenchPanel hasAnswer runSettled events={events} />);

    expect(screen.getByText(generatedLabel)).toBeInTheDocument();
    expect(screen.getByText(changedLabel)).toBeInTheDocument();
  });

  test("puts newly created files under generated artifacts in the summary", () => {
    const onSelectTab = vi.fn();
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        onSelectTab={onSelectTab}
        events={[
          event({
            id: "create-1",
            name: "write_file",
            input: {
              changes: [
                {
                  path: "reports/nas_market_research_plan.md",
                  op: "create",
                  diff: [
                    "--- /dev/null",
                    "+++ b/reports/nas_market_research_plan.md",
                    "@@ -0,0 +1,2 @@",
                    "+# Plan",
                    "+body",
                  ].join("\n"),
                },
              ],
            },
          }),
          event({
            id: "edit-1",
            name: "edit_file",
            input: {
              changes: [
                {
                  path: "src/app.tsx",
                  op: "update",
                  diff: "--- a/src/app.tsx\n+++ b/src/app.tsx\n@@\n-old\n+new",
                },
              ],
            },
          }),
        ]}
      />,
    );

    const generatedLabel = "\u751f\u6210\u4ea7\u7269";
    const changedLabel = "\u53d8\u66f4\u6587\u4ef6";
    const generatedList = listAfterSummaryLabel(generatedLabel);
    const changedList = listAfterSummaryLabel(changedLabel);

    expect(
      within(generatedList).getByText("nas_market_research_plan.md"),
    ).toBeInTheDocument();
    expect(
      within(generatedList).queryByText("app.tsx"),
    ).not.toBeInTheDocument();
    expect(within(changedList).getByText("app.tsx")).toBeInTheDocument();
    expect(
      within(changedList).queryByText("nas_market_research_plan.md"),
    ).not.toBeInTheDocument();
    expect(
      within(generatedList).queryByText("--- /dev/null"),
    ).not.toBeInTheDocument();
    expect(
      within(generatedList).queryByText(
        "+++ b/reports/nas_market_research_plan.md",
      ),
    ).not.toBeInTheDocument();

    fireEvent.click(
      within(generatedList).getByRole("button", {
        name: /reports\/nas_market_research_plan\.md/,
      }),
    );
    expect(onSelectTab).toHaveBeenCalledWith("artifacts");

    fireEvent.click(
      within(changedList).getByRole("button", { name: /src\/app\.tsx/ }),
    );
    expect(onSelectTab).toHaveBeenCalledWith("diff");
  });

  test("opens artifact rows through onOpenArtifact with the entry path", () => {
    const onSelectTab = vi.fn();
    const onOpenArtifact = vi.fn();
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        onSelectTab={onSelectTab}
        onOpenArtifact={onOpenArtifact}
        events={[
          event({
            id: "create-1",
            name: "write_file",
            input: {
              changes: [
                {
                  path: "reports/nas_market_research_plan.md",
                  op: "create",
                  diff: [
                    "--- /dev/null",
                    "+++ b/reports/nas_market_research_plan.md",
                    "@@ -0,0 +1,2 @@",
                    "+# Plan",
                    "+body",
                  ].join("\n"),
                },
              ],
            },
          }),
        ]}
      />,
    );

    const generatedLabel = "生成产物";
    const generatedList = listAfterSummaryLabel(generatedLabel);
    fireEvent.click(
      within(generatedList).getByRole("button", {
        name: /reports\/nas_market_research_plan\.md/,
      }),
    );
    expect(onOpenArtifact).toHaveBeenCalledWith(
      "reports/nas_market_research_plan.md",
    );
    expect(onSelectTab).not.toHaveBeenCalled();
  });

  test("treats final output writes as generated artifacts without a diff", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        events={[
          event({
            id: "final-write-1",
            name: "write_text_file",
            input: {
              path: "data/workspaces/thread-1/output/final/nas_market_research_plan.md",
            },
          }),
        ]}
      />,
    );

    const generatedLabel = "\u751f\u6210\u4ea7\u7269";
    const changedLabel = "\u53d8\u66f4\u6587\u4ef6";
    const generatedList = listAfterSummaryLabel(generatedLabel);

    expect(
      within(generatedList).getByText("nas_market_research_plan.md"),
    ).toBeInTheDocument();
    expect(screen.queryByText(changedLabel)).not.toBeInTheDocument();
  });

  test("prefers file_change create details over the write command summary", () => {
    const fullPath =
      "F:\\新建文件夹\\octopus-agent\\data\\workspaces\\thread-1\\output\\final\\nas_market_research_plan.md";
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        events={[
          event({
            id: "write-command-1",
            name: "write_text_file",
            input: {
              path: "nas_market_research_plan.md",
            },
            output:
              '(real tool execution succeeded) write_text_file {"path": "' +
              fullPath +
              '"}',
          }),
          event({
            id: "file-change-1",
            name: "file_change",
            input: {
              changes: [
                {
                  path: fullPath,
                  op: "create",
                  diff:
                    "--- /dev/null\n+++ b/" +
                    fullPath +
                    "\n@@ -0,0 +1,1 @@\n+# Plan",
                },
              ],
            },
          }),
        ]}
      />,
    );

    const generatedLabel = "\u751f\u6210\u4ea7\u7269";
    const changedLabel = "\u53d8\u66f4\u6587\u4ef6";
    const generatedList = listAfterSummaryLabel(generatedLabel);

    expect(within(generatedList).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.queryByText(changedLabel)).not.toBeInTheDocument();
  });

  test("renders terminal as an Agent computer inner page", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        activeTab="terminal"
        events={[
          event({
            id: "shell-1",
            name: "shell_command",
            input: { command: "pnpm typecheck", cwd: "F:\\repo" },
            output: "Done in 10s",
          }),
        ]}
      />,
    );

    expect(screen.getByRole("tab", { name: "终端" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByTestId("mock-terminal-panel")).toHaveTextContent(
      "F:\\repo",
    );
    expect(screen.queryByText("Agent 01")).not.toBeInTheDocument();
  });

  test("marks stale approval progress complete after an answer exists", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        events={[
          event({
            id: "approval-1",
            name: "write_text_file",
            status: "waiting_approval",
            input: { path: "plan.md" },
          }),
        ]}
      />,
    );

    expandSummarySection(/进展/);

    expect(screen.getAllByText(/Phase 2:/).length).toBeGreaterThan(0);
    // Summary page shows phases with StatusGlyph icons instead of text
  });
  test("does not show waiting copy for a completed empty selected phase", () => {
    renderWorkbench(
      <AgentWorkbenchPanel
        hasAnswer
        runSettled
        events={[
          event({
            id: "todo-1",
            name: "todo_write",
            input: {
              todos: [
                { content: "draft plan", status: "completed" },
                { content: "write report", status: "completed" },
              ],
            },
          }),
          event({
            id: "write-1",
            name: "write_file",
            status: "done",
            input: { path: "report.md" },
            startedAt: 2000,
          }),
        ]}
      />,
    );

    expandSummarySection(/进展/);

    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);
    expect(screen.queryByText("待开始")).not.toBeInTheDocument();
  });

  test("follows the running phase as streamed todo progress advances", () => {
    const phaseOne = event({
      id: "todo-1",
      name: "todo_write",
      status: "done",
      input: {
        todos: [
          { content: "write plan.md", status: "in_progress" },
          { content: "run research", status: "pending" },
        ],
      },
    });
    const { rerender } = renderWorkbench(
      <AgentWorkbenchPanel events={[phaseOne]} />,
    );

    expandSummarySection(/进展/);
    expect(screen.getAllByText(/Phase 1/).length).toBeGreaterThan(0);

    rerender(
      <AgentWorkbenchPanel
        events={[
          phaseOne,
          event({
            id: "todo-2",
            name: "todo_write",
            status: "done",
            startedAt: 2000,
            input: {
              todos: [
                { content: "write plan.md", status: "completed" },
                { content: "run research", status: "in_progress" },
              ],
            },
          }),
        ]}
      />,
    );

    expect(screen.getAllByText(/Phase 2/).length).toBeGreaterThan(0);
  });
});

// ── Sub-agent visualisation: role → emoji avatar ────────────
import { __testing } from "./agent-workbench-panel";
const { avatarForRole, ROLE_AVATAR, DEFAULT_AVATAR } = __testing;

describe("avatarForRole", () => {
  test("maps known roles to emoji", () => {
    expect(avatarForRole("researcher")).toBe("🔍");
    expect(avatarForRole("critic")).toBe("🛡️");
    expect(avatarForRole("synthesizer")).toBe("✍️");
    expect(avatarForRole("architect")).toBe("🏗️");
    expect(avatarForRole("implementer")).toBe("🔧");
    expect(avatarForRole("debugger")).toBe("🐛");
  });

  test("is case insensitive + trims whitespace", () => {
    expect(avatarForRole("Researcher")).toBe("🔍");
    expect(avatarForRole("CRITIC")).toBe("🛡️");
    expect(avatarForRole("  synthesizer  ")).toBe("✍️");
  });

  test("falls back to octopus mascot for unknown role", () => {
    expect(avatarForRole("unknown_role_x")).toBe(DEFAULT_AVATAR);
  });

  test("returns undefined for empty / null", () => {
    expect(avatarForRole("")).toBeUndefined();
    expect(avatarForRole(null)).toBeUndefined();
    expect(avatarForRole(undefined)).toBeUndefined();
  });

  test("default avatar is octopus", () => {
    expect(DEFAULT_AVATAR).toBe("🐙");
  });

  test("ROLE_AVATAR has the canonical role keys", () => {
    const required = [
      "researcher",
      "critic",
      "synthesizer",
      "architect",
      "implementer",
      "debugger",
      "fact_checker",
    ];
    for (const role of required) {
      expect(ROLE_AVATAR).toHaveProperty(role);
    }
  });
});
