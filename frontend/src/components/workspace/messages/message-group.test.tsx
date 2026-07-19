import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AIMessage, Message } from "@/core/api/types";
import { renderWithProviders } from "@/test/harness";

import { groupMessages } from "@/core/messages/utils";

import { AGENT_WORKBENCH_OPEN_EVENT } from "../agent-workbench-events";
import { hasVisibleMessageGroupContent, MessageGroup } from "./message-group";

vi.mock("../artifacts", () => ({
  useArtifacts: () => ({
    setOpen: vi.fn(),
    autoOpen: false,
    autoSelect: false,
    selectedArtifact: null,
    select: vi.fn(),
  }),
}));

describe("MessageGroup todo_write rendering", () => {
  it("hides todo_write tool calls from the execution timeline", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "todo-1",
          name: "todo_write",
          args: {
            todos: JSON.stringify([
              { text: "Confirm task", status: "completed" },
              {
                text: "Check constraints",
                status: "in_progress",
                active_form: "Checking constraints",
              },
              { text: "Output result", status: "pending" },
            ]),
          },
        },
      ],
    };

    renderWithProviders(<MessageGroup messages={[message]} />, {
      locale: "en-US",
    });

    expect(screen.queryByText("Update to-do list")).not.toBeInTheDocument();
    expect(screen.queryByText("Task plan")).not.toBeInTheDocument();
    expect(screen.queryByText("Confirm task")).not.toBeInTheDocument();
    expect(screen.queryByText("Checking constraints")).not.toBeInTheDocument();
    expect(screen.queryByText("Output result")).not.toBeInTheDocument();
    expect(screen.queryByText(/todo_write/)).not.toBeInTheDocument();
  });

  it("hides auto verification tool calls from restored history", () => {
    const messages: Message[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "verify-1",
            name: "verification",
            args: {},
          },
          {
            id: "read-1",
            name: "read_file",
            args: { path: "notes.md" },
          },
        ],
      },
      {
        id: "tool-verify-1",
        type: "tool",
        content: "verification required",
        tool_call_id: "verify-1",
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "en-US",
    });

    expect(screen.queryByText(/verification/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/verification required/i),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Process details"));

    expect(screen.queryByText(/verification/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/verification required/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/notes\.md/)).toBeInTheDocument();
  });

  it("treats auto-verification-only groups as empty", () => {
    const messages: Message[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "verify-1",
            name: "verification",
            args: {},
          },
        ],
      },
      {
        id: "tool-verify-1",
        type: "tool",
        content: "verification required",
        tool_call_id: "verify-1",
      },
    ];

    expect(hasVisibleMessageGroupContent(messages)).toBe(false);

    const { container } = renderWithProviders(
      <MessageGroup messages={messages} />,
      {
        locale: "en-US",
      },
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("MessageGroup reasoning grouping", () => {
  it("does not echo a public checkpoint as thinking when it carries completed tools", () => {
    const paths = ["a.py", "b.ts", "c.ts", "d.ts"];
    const messages: AIMessage[] = [
      {
        id: "coverage-progress",
        type: "ai",
        content: "四个目标文件均已读取完毕，关键字段一致；下一步整理最终结论。",
        additional_kwargs: {
          public_progress: true,
          progress_sequence: 1,
          timeline_sequence: 5,
        },
        tool_calls: paths.map((path, index) => ({
          id: `read-${index}`,
          name: "read_file",
          args: { path },
          timelineSequence: index + 1,
          type: "tool_call" as const,
        })),
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "zh-CN",
    });

    expect(screen.getAllByTestId("public-progress-event")).toHaveLength(1);
    const visibleExecution = screen.getByTestId(
      "process-timeline-event-execution",
    );
    expect(visibleExecution).toHaveAttribute("data-process-event-id", "read-3");
    expect(
      screen.queryByTestId("process-timeline-event-thinking"),
    ).not.toBeInTheDocument();

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("过程细节"));
    expect(opened.at(-1)?.detail).toMatchObject({
      eventKind: "execution",
      view: "trace",
      processEvent: { count: 5 },
    });
    for (const path of paths) {
      expect(opened.at(-1)?.detail.processEvent.detail).toContain(path);
    }
    expect(screen.queryByText("a.py")).not.toBeInTheDocument();
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("renders public checkpoints inline between thinking and execution", () => {
    const messages: AIMessage[] = [
      {
        id: "progress-1",
        type: "ai",
        content: "已确认流事件按消息、思考和执行三条通道归一化。",
        additional_kwargs: {
          public_progress: true,
          reasoning_content: "inspect the bridge",
          grounding: [
            {
              kind: "source",
              title: "realtime_event_bridge.py",
              path: "runtime/sensing/gateway/realtime_event_bridge.py",
            },
          ],
        },
      },
      {
        id: "progress-2",
        type: "ai",
        content: "进一步确认执行完成后才会开启下一轮公开结论。",
        additional_kwargs: {
          public_progress: true,
          phase_id: "turn-1:progress:2",
          parent_item_id: "read-bridge",
          progress_sequence: 2,
          timeline_sequence: 3,
          reasoning_content: "inspect the reducer",
        },
        tool_calls: [
          {
            id: "read-bridge",
            name: "read_file",
            args: { path: "realtime_event_bridge.py" },
            timelineSequence: 2,
            parentItemId: "progress-1",
            phaseId: "turn-1:progress:1",
          },
        ],
      },
    ];

    const groups = groupMessages(messages, (group) => group);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.type).toBe("assistant:processing");

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    const checkpoints = screen.getAllByTestId("public-progress-event");
    expect(checkpoints).toHaveLength(2);
    expect(checkpoints[1]).toHaveAttribute(
      "data-phase-id",
      "turn-1:progress:2",
    );
    expect(checkpoints[1]).toHaveAttribute(
      "data-parent-item-id",
      "read-bridge",
    );
    expect(checkpoints[1]).toHaveAttribute("data-progress-sequence", "2");
    expect(checkpoints[1]).toHaveAttribute("data-timeline-sequence", "3");
    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(checkpoints[0]!);
    expect(opened.at(-1)?.detail).toMatchObject({
      eventId: "progress-1",
      eventKind: "thinking",
      view: "summary",
      processEvent: {
        kind: "thinking",
        detail: "已确认流事件按消息、思考和执行三条通道归一化。",
        status: "done",
        count: 1,
      },
    });
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    const groundingTrigger = screen.getByRole("button", {
      name: "预读了 0 篇项目文档 · 1 处代码",
    });
    expect(checkpoints[0]).toContainElement(groundingTrigger);
    expect(screen.queryByText("定向")).not.toBeInTheDocument();
    expect(screen.queryByText("验证")).not.toBeInTheDocument();
    expect(
      screen.getByText("已确认流事件按消息、思考和执行三条通道归一化。"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("进一步确认执行完成后才会开启下一轮公开结论。"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).toHaveAttribute("data-timeline-sequence", "2");
    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).not.toHaveTextContent(/^执行(?:\s|·)/);
  });

  it("deduplicates replayed checkpoints and tool ids in the main transcript", () => {
    const repeatedProgress = "正在读取消息组件，确认时间线的真实渲染顺序。";
    const messages: AIMessage[] = ["progress-a", "progress-b"].map((id) => ({
      id,
      type: "ai",
      content: repeatedProgress,
      additional_kwargs: { public_progress: true },
      tool_calls: [
        {
          id: "read-shared",
          name: "read_file",
          args: { path: "message-group.tsx" },
        },
      ],
    }));

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "zh-CN",
    });

    expect(screen.getAllByTestId("public-progress-event")).toHaveLength(1);
    expect(
      screen.getAllByTestId("process-timeline-event-execution"),
    ).toHaveLength(1);
    expect(screen.getAllByText(repeatedProgress)).toHaveLength(1);
  });

  it("keeps only the latest thinking step visible while streaming", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: { public_reasoning_summary: "先扫一遍上下文" },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "再整理成可执行步骤",
        },
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    const thinkingEvent = screen.getByTestId("process-timeline-event-thinking");
    expect(thinkingEvent).toBeInTheDocument();
    expect(thinkingEvent).not.toHaveTextContent(/^思考过程(?:\s|·)/);
    const replayToggle = screen.getByTitle("过程细节");
    const currentFrame = screen.getByText("再整理成可执行步骤");
    expect(replayToggle).toBeInTheDocument();
    expect(currentFrame).toBeInTheDocument();
    expect(screen.queryByText("先扫一遍上下文")).not.toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("02")).not.toBeInTheDocument();

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(replayToggle);

    expect(screen.queryByText("先扫一遍上下文")).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail).toMatchObject({
      eventKind: "thinking",
      view: "summary",
      processEvent: { count: 2 },
    });
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "先扫一遍上下文",
    );
    expect(screen.getAllByText("再整理成可执行步骤")).toHaveLength(1);
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("keeps kept-open traces compact and sends prior steps to the workbench", () => {
    const messages: AIMessage[] = Array.from({ length: 4 }, (_, index) => ({
      id: `ai-${index + 1}`,
      type: "ai",
      content: "",
      additional_kwargs: {
        public_reasoning_summary: `Latest trace thought ${index + 1}.`,
      },
    }));

    renderWithProviders(
      <MessageGroup messages={messages as never} keepOpen />,
      {
        locale: "en-US",
      },
    );

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("03")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Latest trace thought 1."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Latest trace thought 4.")).toBeInTheDocument();

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("Process details"));

    expect(
      screen.queryByText("Latest trace thought 1."),
    ).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "Latest trace thought 1.",
    );
    expect(opened.at(-1)?.detail.processEvent.count).toBe(4);
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("never turns private reasoning tool protocol into public actions", () => {
    const message: AIMessage = {
      id: "ai-search",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: [
          "Let me search for more specific data on this.",
          "<tool_call><function=web_search><parameter=query>AI Agent SMB opportunity</parameter></function></tool_call>",
          "The search results are coming back empty for many of my queries.",
        ].join("\n\n"),
      },
    };

    renderWithProviders(<MessageGroup messages={[message]} keepOpen />, {
      locale: "en-US",
    });

    expect(
      screen.queryByTestId("process-timeline-event-execution"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Thought")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Let me search for more specific data on this."),
    ).not.toBeInTheDocument();

    expect(screen.queryByTitle(/Replay/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Search sources: AI Agent SMB opportunity"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/web_search/)).not.toBeInTheDocument();
  });

  it("keeps long thinking details out of the transcript and sends them to the workbench", () => {
    const hiddenTail = "UNIQUE_NESTED_REASONING_TAIL";
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: `First I will inspect the request and summarize the path before touching the UI. ${"extra context ".repeat(24)} ${hiddenTail}`,
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "Second I will choose the next interface step.",
        },
      },
    ];

    renderWithProviders(<MessageGroup messages={messages as never} />, {
      locale: "en-US",
    });

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("Process details"));

    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("02")).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(hiddenTail))).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(hiddenTail);
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("keeps saved steps compact and opens their detail in the workbench", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "First inspect the request.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "laser engraving market 2025" },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages as never} />, {
      locale: "en-US",
    });

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Process details"));

    expect(screen.queryByTitle("Hide saved steps")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/laser engraving market 2025/).length,
    ).toBeGreaterThan(0);
  });

  it("keeps completed code-mode traces behind the workbench disclosure", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "Inspect the user request before editing.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "frontend route structure" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup codeMode messages={messages as never} />,
      {
        locale: "en-US",
      },
    );

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    expect(
      screen.queryByText("Inspect the user request before editing."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("frontend route structure"),
    ).not.toBeInTheDocument();
  });

  it("keeps a live code-mode trace compact when the same turn becomes historical", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "Inspect the user request before editing.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "frontend route structure" },
          },
        ],
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup codeMode isLoading messages={messages as never} />,
      {
        locale: "en-US",
      },
    );

    expect(screen.queryByTitle(/Replay/)).not.toBeInTheDocument();
    expect(screen.getByText(/frontend route structure/)).toBeInTheDocument();

    rerender(<MessageGroup codeMode messages={messages as never} />);

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    expect(screen.queryByTitle("Hide saved steps")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();
  });

  it("keeps code-mode traces compact while the turn is live", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "Inspect the user request before editing.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "frontend route structure" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup codeMode isLoading messages={messages as never} />,
      {
        locale: "en-US",
      },
    );

    expect(
      screen.queryByText("Inspect the user request before editing."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Live process")).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Replay/)).not.toBeInTheDocument();
    expect(screen.getByText(/frontend route structure/)).toBeInTheDocument();
  });

  it("shows the current action in chat mode without duplicating the code process strip", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-chat-action",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-chat",
            name: "web_search",
            args: { query: "conversational streaming rhythm" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup isLoading messages={messages as never} />,
      { locale: "zh-CN" },
    );

    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/conversational streaming rhythm/).length,
    ).toBeGreaterThan(0);
  });

  it("keeps a confirmation action compact in the live code timeline", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "ask-1",
            name: "ask_user_question",
            args: { question: "是否继续写入文件？" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup codeMode isLoading messages={messages as never} />,
      {
        locale: "zh-CN",
      },
    );

    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).toBeInTheDocument();
    expect(screen.queryByText("实时进程")).not.toBeInTheDocument();
  });

  it("keeps only the current frame visible when latest trace is kept open", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "First inspect the request.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "laser engraving market 2025" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} keepOpen />,
      {
        locale: "en-US",
      },
    );

    expect(screen.queryByTitle("View 2 saved steps")).not.toBeInTheDocument();
    expect(screen.queryByTitle(/Replay/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("First inspect the request."),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();

    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
  });

  it("keeps the lead-in before Phase 1 visible during live streaming", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-lead-in",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "这个问题需要先确认赛道边界，否则机会点会太泛。",
        },
      },
      {
        id: "ai-phase-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "Phase 1: 先拆分候选细分赛道。",
        },
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} keepOpen />,
      {
        locale: "zh-CN",
      },
    );

    expect(
      screen.queryByText("这个问题需要先确认赛道边界，否则机会点会太泛。"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Phase 1: 先拆分候选细分赛道。"),
    ).toBeInTheDocument();
    expect(screen.queryByTitle(/过程回放/)).not.toBeInTheDocument();
  });

  it("does not open a questionnaire for ordinary clarification text inside reasoning steps", () => {
    const message: AIMessage = {
      id: "ai-clarify",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: [
          "先问一个关键问题再动手，避免方向偏了：",
          "",
          "你有偏好的行业方向或资源背景吗？ 比如：",
          "",
          "- 你在某个行业有供应链/技术/渠道资源？",
          "- 关注消费品、B2B SaaS、硬件，还是其他？",
          "- 预算规模和团队能力大致是什么量级？",
          "",
          "一句话告诉我方向，我直接开挖。",
        ].join("\n"),
      },
    };

    renderWithProviders(
      <MessageGroup enableClarificationActions messages={[message]} />,
      {
        locale: "zh-CN",
      },
    );

    expect(
      screen.queryByRole("region", { name: "请回答以下问题" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("更想看哪个行业方向？")).not.toBeInTheDocument();
  });

  it("uses a live status dot without synthetic thinking labels", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: "先确认搜索目标。",
      },
      tool_calls: [
        {
          id: "search-1",
          name: "web_search",
          args: { query: "smart sleep market" },
        },
      ],
    };

    renderWithProviders(<MessageGroup messages={[message]} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.queryByTitle(/过程回放/)).not.toBeInTheDocument();
    expect(
      screen.getAllByTestId("process-timeline-event-execution").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("思考中")).not.toBeInTheDocument();

    expect(screen.getByText(/smart sleep market/)).toBeInTheDocument();
    expect(screen.queryByText("思考中")).not.toBeInTheDocument();
  });

  it("groups consecutive tool calls into a collapsible execution summary", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "laser engraving market 2025" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();
  });

  it("keeps search results out of the compact main timeline", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "laser engraving market 2025" },
          },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        content: JSON.stringify({
          results: [
            {
              title: "OpenClaw GitHub repo",
              url: "https://github.com/openclaw/openclaw",
            },
            { title: "OpenClaw docs", url: "https://openclaw.dev/docs" },
          ],
        }),
        tool_call_id: "search-1",
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    expect(screen.queryByText("已搜索到 2 个网页")).not.toBeInTheDocument();
    expect(screen.queryByText("OpenClaw GitHub repo")).not.toBeInTheDocument();
    expect(screen.queryByText("OpenClaw docs")).not.toBeInTheDocument();
    expect(
      screen.getByTestId("process-timeline-event-execution"),
    ).toBeInTheDocument();
  });

  it("keeps unknown Action callback text out of the public timeline", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content:
            '先整理报告结构。\n\nAction: ipython({"code":"print(\'write file\')"})\n\n继续检查输出文件。',
        },
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    expect(screen.queryByText("已调用")).not.toBeInTheDocument();
    expect(screen.queryByText(/ipython/)).not.toBeInTheDocument();
    expect(screen.queryByText("继续检查输出文件。")).not.toBeInTheDocument();
    expect(screen.queryByText("执行动作")).not.toBeInTheDocument();
    expect(screen.queryByText("整理调研结果")).not.toBeInTheDocument();
    expect(screen.queryByText(/ipython/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Action:/)).not.toBeInTheDocument();
    expect(screen.queryByText("执行中")).not.toBeInTheDocument();
  });

  it("uses tool targets without synthetic action badges", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "ls-1",
            name: "ls",
            args: { path: "src" },
          },
          {
            id: "read-1",
            name: "read_file",
            args: { path: "src/app.tsx" },
          },
          {
            id: "write-1",
            name: "write_file",
            args: { path: "plan.md" },
          },
        ],
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    expect(screen.queryByText("已浏览目录")).not.toBeInTheDocument();
    expect(screen.queryByText("已读取")).not.toBeInTheDocument();
    expect(
      screen.getAllByTestId("process-timeline-event-execution"),
    ).toHaveLength(3);

    fireEvent.click(screen.getByTitle("过程细节"));

    expect(screen.queryByText("已浏览目录")).not.toBeInTheDocument();
    expect(screen.queryByText("已读取")).not.toBeInTheDocument();
    expect(screen.getAllByText(/src$/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/src\/app\.tsx/).length).toBeGreaterThan(0);
  });
});

describe("MessageGroup streaming lifecycle", () => {
  it("interleaves thinking, answer, and execution as quiet timeline rows", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-thinking",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "先确认需求和现有上下文",
        },
      },
      {
        id: "ai-answer-and-tool",
        type: "ai",
        content: "我先给你一个方向，同时继续检查实现。",
        tool_calls: [
          {
            id: "read-1",
            name: "read_file",
            args: { path: "src/chat.tsx" },
          },
        ],
      },
    ];
    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      { locale: "zh-CN" },
    );

    const thinking = screen.getByTestId("process-timeline-event-thinking");
    const answer = screen.getByText("我先给你一个方向，同时继续检查实现。");
    const execution = screen.getByTestId("process-timeline-event-execution");

    expect(
      thinking.compareDocumentPosition(answer) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      answer.compareDocumentPosition(execution) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(thinking.className).not.toMatch(/\b(?:border|rounded|bg-)/);
    expect(execution.className).not.toMatch(/\b(?:border|rounded|bg-)/);
    expect(thinking).toHaveAttribute("data-process-event-id", "ai-thinking");
    expect(execution).toHaveAttribute("data-process-event-id", "read-1");

    fireEvent.click(thinking);
    expect(opened.at(-1)?.detail).toMatchObject({
      tab: "agent",
      eventId: "ai-thinking",
      eventKind: "thinking",
      view: "summary",
      processEvent: {
        kind: "thinking",
        summary: "先确认需求和现有上下文",
        detail: "先确认需求和现有上下文",
        status: "done",
        count: 1,
      },
    });
    fireEvent.click(execution);
    expect(opened.at(-1)?.detail).toMatchObject({
      tab: "agent",
      eventId: "read-1",
      eventKind: "execution",
      view: "trace",
      processEvent: {
        kind: "execution",
        status: "running",
        count: 1,
      },
    });

    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("keeps a thinking checkpoint visible during a long tool run", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-thinking-anchor",
        type: "ai",
        content: "",
        additional_kwargs: { public_reasoning_summary: "先梳理架构边界" },
      },
      {
        id: "ai-long-tool-run",
        type: "ai",
        content: "",
        tool_calls: Array.from({ length: 8 }, (_, index) => ({
          id: `read-${index}`,
          name: "read_file",
          args: { path: `src/file-${index}.ts` },
        })),
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      { locale: "zh-CN" },
    );

    expect(
      screen.getByTestId("process-timeline-event-thinking"),
    ).toHaveAttribute("data-process-event-id", "ai-thinking-anchor");
    const visibleExecutions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    expect(visibleExecutions).toHaveLength(3);
    expect(
      visibleExecutions.map((element) =>
        element.getAttribute("data-process-event-id"),
      ),
    ).toEqual(["read-5", "read-6", "read-7"]);
  });

  it("transitions from streaming to completed without losing tool calls", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "search-1",
            name: "web_search",
            args: { query: "test query" },
          },
          {
            id: "read-1",
            name: "read_file",
            args: { path: "notes.md" },
          },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        content: "search results here",
        tool_call_id: "search-1",
      },
      {
        id: "tool-2",
        type: "tool",
        content: "file content here",
        tool_call_id: "read-1",
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      { locale: "en-US" },
    );

    expect(screen.getAllByText(/notes\.md/).length).toBeGreaterThan(0);

    rerender(<MessageGroup messages={messages as never} />);

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Process details"));
    expect(screen.getAllByText(/test query/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/notes\.md/).length).toBeGreaterThan(0);
  });

  it("keeps public reasoning summaries stable when streaming tokens arrive", () => {
    const makeMessages = (reasoning: string): AIMessage[] => [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: { public_reasoning_summary: reasoning },
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup
        messages={makeMessages("Thinking about phase one")}
        isLoading
      />,
      { locale: "en-US" },
    );

    expect(screen.getByText(/phase one/)).toBeInTheDocument();

    rerender(
      <MessageGroup
        messages={makeMessages("Thinking about phase one and phase two")}
        isLoading
      />,
    );

    expect(screen.getByText(/phase one and phase two/)).toBeInTheDocument();
  });

  it("handles empty message array gracefully", () => {
    const { container } = renderWithProviders(<MessageGroup messages={[]} />, {
      locale: "en-US",
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows error state correctly when tool fails during streaming", () => {
    const messages: Message[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "tool-1",
            name: "web_search",
            args: { query: "test" },
          },
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        content: "",
        tool_call_id: "tool-1",
        additional_kwargs: { status: "error", error: "Search failed" },
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "en-US",
    });

    expect(screen.getByText(/test/)).toBeInTheDocument();
  });

  it("code mode live process strip transitions from running to completed", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "read-1",
            name: "read_file",
            args: { path: "test.ts" },
          },
        ],
      },
      {
        id: "tool-read-1",
        type: "tool",
        content: "file content",
        tool_call_id: "read-1",
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup codeMode isLoading messages={messages as never} />,
      { locale: "en-US" },
    );

    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();

    rerender(<MessageGroup codeMode messages={messages as never} />);

    expect(
      screen.getByTestId("interleaved-process-timeline"),
    ).toBeInTheDocument();
  });

  it("keeps workbench-only reasoning details stable across streaming updates", () => {
    const makeMessages = (extraText: string): AIMessage[] => [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "First thinking step that is visible.",
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: `Second thinking step. ${extraText}`,
        },
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup messages={makeMessages("Initial")} keepOpen />,
      { locale: "en-US" },
    );

    expect(screen.getAllByText(/Second thinking step/).length).toBeGreaterThan(
      0,
    );
    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("Process details"));
    expect(screen.queryByText(/First thinking step/)).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "First thinking step",
    );

    rerender(
      <MessageGroup
        messages={makeMessages("Updated with more content")}
        keepOpen
      />,
    );

    expect(screen.getByTitle("Process details")).toBeInTheDocument();
    expect(screen.queryByText(/First thinking step/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/Second thinking step/).length).toBeGreaterThan(
      0,
    );
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("groups mixed content + tool calls into processing + assistant groups", () => {
    const longAnswer = [
      "# Summary of findings",
      "",
      "Here is a detailed analysis that exceeds the final-answer threshold.",
      "",
      "1. First point about the research",
      "2. Second point about the data",
      "3. Third point about the conclusion",
      "4. Fourth point with additional context",
      "",
      "This paragraph adds enough length to cross the 320-character threshold ",
      "so the message is treated as a final answer rather than a preamble. ",
      "The distinction matters because final answers render as standalone ",
      "assistant content, while short preambles fold into the process timeline.",
    ].join("\n");

    const message: AIMessage = {
      id: "ai-mixed",
      type: "ai",
      content: longAnswer,
      tool_calls: [
        {
          id: "search-1",
          name: "web_search",
          args: { query: "reference docs" },
        },
      ],
    };

    const groups = groupMessages([message], (g) => g);
    expect(groups.length).toBe(2);
    expect(groups[0]?.type).toBe("assistant:processing");
    expect(groups[1]?.type).toBe("assistant");
    expect(groups[0]?.messages).toContain(message);
    expect(groups[1]?.messages).toContain(message);

    renderWithProviders(
      <MessageGroup messages={groups[0]!.messages} isLoading />,
      {
        locale: "en-US",
      },
    );

    expect(screen.getByText(/reference docs/)).toBeInTheDocument();
  });
});
