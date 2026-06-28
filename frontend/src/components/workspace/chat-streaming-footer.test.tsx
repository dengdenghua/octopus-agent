import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { AllProviders } from "@/test/harness";
import type { BaseStream } from "@/core/api/use-stream";
import type { AgentThreadState } from "@/core/threads";

import { ChatStreamingFooter } from "./chat-streaming-footer";
import type { LiveToolEvent } from "./live-tool-timeline";

function mockThread(
  overrides: Partial<BaseStream<AgentThreadState>> = {},
): BaseStream<AgentThreadState> {
  return {
    isLoading: true,
    streamingMessage: undefined,
    ...overrides,
  } as BaseStream<AgentThreadState>;
}

function renderFooter(events: LiveToolEvent[]) {
  return render(
    <AllProviders>
      <ChatStreamingFooter
        thread={mockThread()}
        liveToolEvents={events}
        mode="deep"
      />
    </AllProviders>,
  );
}

describe("ChatStreamingFooter", () => {
  test("deep mode shows a compact phase summary and lightweight timeline details", () => {
    renderFooter([
      {
        id: "search-1",
        name: "web_search",
        status: "running",
        startedAt: 1000,
        iteration: 1,
        agentId: "market",
        agentName: "Market Researcher",
        input: { query: "NAS market share", max_results: 5 },
      },
      {
        id: "search-2",
        name: "web_search",
        status: "done",
        startedAt: 1100,
        finishedAt: 1300,
        iteration: 1,
        agentId: "pricing",
        agentName: "Pricing Analyst",
        input: { query: "NAS price comparison", max_results: 5 },
        output: {
          results: [{ title: "Price", url: "https://example.com/price" }],
        },
      },
    ]);

    expect(screen.getByText("Collecting data")).toBeInTheDocument();
    expect(screen.getByText("NAS market share")).toBeInTheDocument();
    expect(screen.getByText("2 Agent")).toBeInTheDocument();
    expect(screen.queryByText(/Agent Cluster/)).not.toBeInTheDocument();
    const executionStrip = screen.getByTestId("chat-execution-strip");
    expect(executionStrip).toHaveTextContent("Octopus Agent is executing");
    expect(executionStrip).toHaveTextContent("Current progress 1/2");
    expect(executionStrip).toHaveTextContent("View result");
    expect(executionStrip).toHaveTextContent("Replay");
    expect(executionStrip.className).toContain("rounded-xl");

    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(screen.getAllByText("Market Researcher").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Pricing Analyst").length).toBeGreaterThan(0);
    expect(screen.getByText(/NAS price comparison/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { expanded: true }));
    expect(screen.queryByText("Market Researcher")).not.toBeInTheDocument();
  });

  test("team mode shows a collaboration header and member cluster", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="team"
          liveToolEvents={[
            {
              id: "plan-1",
              name: "todo_write",
              status: "done",
              startedAt: 1000,
              finishedAt: 1100,
              iteration: 1,
              agentName: "Team Lead",
              output: { todos: [] },
            },
            {
              id: "impl-1",
              name: "read_file",
              status: "running",
              startedAt: 1200,
              iteration: 1,
              agentName: "Engineer",
              input: { path: "frontend/src/app.tsx" },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Reading context")).toBeInTheDocument();
    expect(screen.getAllByText("frontend/src/app.tsx").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("2 Agent")).toBeInTheDocument();

    expect(screen.getAllByText(/Team Lead/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Engineer/).length).toBeGreaterThan(0);
  });

  test("code mode uses coding-specific process language", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="code"
          liveToolEvents={[
            {
              id: "read-1",
              name: "read_file",
              status: "running",
              startedAt: 1000,
              iteration: 1,
              input: { path: "frontend/src/app.tsx" },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Reading context")).toBeInTheDocument();
    expect(screen.getAllByText("frontend/src/app.tsx").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Processing...")).toBeInTheDocument();
  });

  test("expanded deep mode renders heavy tasks as a single lightweight timeline", () => {
    renderFooter([
      {
        id: "todo-1",
        name: "todo_write",
        status: "done",
        startedAt: 900,
        finishedAt: 950,
        iteration: 1,
        input: {
          items: [
            { content: "制定研究计划", status: "completed" },
            {
              content: "并行研究 AI 芯片市场规模",
              status: "in_progress",
              activeForm: "正在并行研究 AI 芯片市场规模",
            },
            { content: "撰写行业报告", status: "pending" },
            { content: "事实核查与语言润色", status: "pending" },
            { content: "导出最终 Word 文档", status: "pending" },
          ],
        },
      },
      {
        id: "search-1",
        name: "web_search",
        status: "running",
        startedAt: 1000,
        iteration: 1,
        agentName: "市场研究员",
        input: { query: "AI chip market size 2025" },
      },
      {
        id: "draft-1",
        name: "write_file",
        status: "done",
        startedAt: 1200,
        finishedAt: 1300,
        iteration: 1,
        agentName: "写手",
        input: { path: "stage3_drafts/chapter_01.md" },
      },
      {
        id: "review-1",
        name: "fact_check",
        status: "done",
        startedAt: 1400,
        finishedAt: 1450,
        iteration: 1,
        agentName: "事实核查员",
      },
    ]);

    expect(screen.queryByText("Heavy Task Pipeline")).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/AI chip market size 2025/).length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByText(/chapter_01\.md/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/3 Agent/).length).toBeGreaterThan(0);
  });

  test("todo details remain accessible without rendering a fixed stage template", () => {
    renderFooter([
      {
        id: "todo-custom",
        name: "todo_write",
        status: "done",
        startedAt: 900,
        finishedAt: 950,
        iteration: 1,
        input: {
          items: [
            {
              content: "收集英伟达和 AMD 财报数据",
              status: "completed",
              stage: "财报数据收集",
            },
            {
              content: "对比训练芯片与推理芯片路线",
              status: "in_progress",
              activeForm: "正在对比训练芯片与推理芯片路线",
              stage: "技术路线对比",
            },
            {
              content: "输出投资风险清单",
              status: "pending",
              stage: "风险清单",
            },
          ],
        },
      },
    ]);

    expect(screen.getByText("Todos")).toBeInTheDocument();
    expect(screen.queryByText("Assemble deliverable")).not.toBeInTheDocument();
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getAllByText(/items/).length).toBeGreaterThan(0);
    expect(screen.queryByText("Assemble deliverable")).not.toBeInTheDocument();
  });

  test("plain chat only shows a minimal thinking indicator", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="chat"
          liveToolEvents={[
            {
              id: "todo-1",
              name: "todo_write",
              status: "running",
              startedAt: 1000,
              iteration: 1,
              input: {
                todos: [
                  {
                    content: "\u660e\u786e\u4efb\u52a1\u76ee\u6807",
                    status: "in_progress",
                  },
                ],
              },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(screen.queryByText("Thinking process")).not.toBeInTheDocument();
    expect(screen.queryByText("Task Plan")).not.toBeInTheDocument();
  });

  test("plain chat does not show realtime work log before backend tool events arrive", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="chat"
          liveToolEvents={[]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(screen.queryByText("Thinking process")).not.toBeInTheDocument();
    expect(screen.queryByText("Understanding Task")).not.toBeInTheDocument();
    expect(screen.queryByText("Connecting Runtime")).not.toBeInTheDocument();
    expect(screen.queryByText("AI is thinking")).not.toBeInTheDocument();
  });

  test("react mode stays minimal before semantic work events arrive", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="react"
          liveToolEvents={[]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(screen.queryByText("Thinking process")).not.toBeInTheDocument();
    expect(screen.queryByText("Understanding Task")).not.toBeInTheDocument();
    expect(screen.queryByText("Connecting Runtime")).not.toBeInTheDocument();
    expect(screen.queryByText("AI is thinking")).not.toBeInTheDocument();
  });

  test("react mode hides the fallback footer once the assistant message is streaming", () => {
    const rawReasoning =
      "  I need to inspect the failing stream path before editing.\n\nNext, read the footer.  ";

    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread({
            streamingMessage: {
              type: "ai",
              id: "stream-1",
              content: "",
              additional_kwargs: {
                reasoning_content: rawReasoning,
              },
            },
          })}
          mode="react"
          liveToolEvents={[]}
        />
      </AllProviders>,
    );

    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Model Public Reasoning Stream"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        /I need to inspect the failing stream path before editing/,
      ),
    ).not.toBeInTheDocument();
  });

  test("workflow event details do not render in the footer after a streaming message exists", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread({
            streamingMessage: {
              type: "ai",
              id: "stream-1",
              content: "Working",
            },
          })}
          mode="code"
          liveToolEvents={[
            {
              id: "read-1",
              name: "read_file",
              status: "running",
              startedAt: 1000,
              iteration: 1,
              input: { path: "frontend/src/app.tsx" },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    expect(screen.queryByText("Reading context")).not.toBeInTheDocument();
    expect(screen.queryByText("frontend/src/app.tsx")).not.toBeInTheDocument();
  });

  test("react mode keeps model gateway-only turns minimal", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="react"
          liveToolEvents={[
            {
              id: "gateway-1",
              name: "model_gateway",
              status: "running",
              startedAt: 1000,
              iteration: 1,
              input: { phase: "waiting_first_chunk" },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Thinking...")).toBeInTheDocument();
    expect(screen.queryByText("Connecting Model")).not.toBeInTheDocument();
    expect(screen.queryByText("Thinking process")).not.toBeInTheDocument();
  });

  test("shows thought, observation, and skill calls in the live trace", () => {
    render(
      <AllProviders>
        <ChatStreamingFooter
          thread={mockThread()}
          mode="code"
          liveToolEvents={[
            {
              id: "thought-1",
              name: "agent_thought",
              status: "done",
              startedAt: 1000,
              finishedAt: 1100,
              iteration: 1,
              thought:
                "Need to search code paths before editing the stream UI.",
              observation: "Found the footer and timeline components.",
            },
            {
              id: "skill-1",
              name: "apply_skill",
              status: "running",
              startedAt: 1200,
              iteration: 1,
              input: {
                skill: "browser-use:browser",
                user_request: "Run local UI regression",
              },
            },
          ]}
        />
      </AllProviders>,
    );

    expect(screen.getByText("Processing task")).toBeInTheDocument();
    expect(screen.getByRole("button", { expanded: true })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Need to search code paths before editing the stream UI.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Observation:/)).toBeInTheDocument();
    expect(
      screen.getByText(/Applying skill browser-use:browser/),
    ).toBeInTheDocument();
    expect(screen.getByText("Run local UI regression")).toBeInTheDocument();
  });
});
