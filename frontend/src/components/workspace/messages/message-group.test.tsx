import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AIMessage, Message } from "@/core/api/types";
import { renderWithProviders } from "@/test/harness";

import { groupMessages } from "@/core/messages/utils";

import { AGENT_WORKBENCH_OPEN_EVENT } from "../agent-workbench-events";
import {
  hasVisibleMessageGroupContent,
  MessageGroup,
  convertToSteps,
  selectCompactTimelineItems,
  type TimelineItem,
} from "./message-group";

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
  it("removes recovery handoff text from public timeline steps", () => {
    const steps = convertToSteps([
      {
        id: "ai-recovery",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "所有文件读取任务已完成。Resume state: 继续核对剩余证据。",
        },
      } as AIMessage,
    ]);
    expect(
      steps.map((step) => ("reasoning" in step ? step.reasoning : "")),
    ).toEqual(["所有文件读取任务已完成。"]);
  });

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

  it("hides internal blackboard writes from the public execution timeline", () => {
    const message: AIMessage = {
      id: "ai-blackboard",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "bb-1",
          name: "bb_write",
          args: {
            key: "internal.progress",
            value: "machine-only coordination state",
          },
        },
      ],
    };

    renderWithProviders(<MessageGroup messages={[message]} />, {
      locale: "en-US",
    });

    expect(screen.queryByText(/bb_write/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText("machine-only coordination state"),
    ).not.toBeInTheDocument();
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

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("Open details"));

    const processEvent = opened.at(-1)?.detail.processEvent;
    expect(processEvent?.summary).not.toBe("Open details");
    expect(processEvent?.summary).toMatch(/notes\.md/);
    expect(processEvent?.detail).toMatch(/notes\.md/);
    expect(screen.queryByText(/verification/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/verification required/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/notes\.md/)).toBeInTheDocument();
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
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
    fireEvent.click(screen.getByTitle("展开线索"));
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

  it("renders identical public summary and checkpoint text only once", () => {
    const checkpoint = "正在读取事件适配器与消息组件，核对时间线顺序。";
    const messages: AIMessage[] = [
      {
        id: "progress-with-summary",
        type: "ai",
        content: checkpoint,
        additional_kwargs: {
          public_progress: true,
          public_reasoning_summary: checkpoint,
        },
        tool_calls: [
          {
            id: "read-adapter",
            name: "read_file",
            args: { path: "realtime-adapter.ts" },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getAllByText(checkpoint)).toHaveLength(1);
    expect(screen.getAllByTestId("public-progress-event")).toHaveLength(1);
    expect(
      screen.queryByTestId("process-timeline-event-thinking"),
    ).not.toBeInTheDocument();
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
      name: "参考 realtime_event_bridge.py",
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

  it("keeps representative public progress while bounding a long run", () => {
    const updates = [
      "先确认时间线的数据来源。",
      "第一次读取失败，正在切换路径。",
      "第二次读取仍失败，继续尝试。",
      "已经找到真实仓库位置，开始核对适配层。",
      "适配层已确认，继续检查渲染层。",
      "渲染层证据已齐，准备收束。",
      "全部证据已经完成。",
    ];
    const messages: AIMessage[] = updates.map((content, index) => ({
      id: `progress-${index + 1}`,
      type: "ai",
      content,
      additional_kwargs: {
        public_progress: true,
        progress_sequence: index + 1,
        timeline_sequence: index + 1,
      },
    }));

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getAllByTestId("public-progress-event")).toHaveLength(4);
    expect(screen.getByText(updates[0]!)).toBeInTheDocument();
    expect(screen.getByText(updates[1]!)).toBeInTheDocument();
    expect(screen.getByText(updates[4]!)).toBeInTheDocument();
    expect(screen.getByText(updates[6]!)).toBeInTheDocument();
    expect(screen.queryByText(updates[2]!)).not.toBeInTheDocument();
    expect(screen.queryByText(updates[3]!)).not.toBeInTheDocument();
    expect(screen.queryByText(updates[5]!)).not.toBeInTheDocument();
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
    const replayToggle = screen.getByTitle("展开线索");
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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("03")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Latest trace thought 1."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Latest trace thought 4.")).toBeInTheDocument();

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(screen.getByTitle("Open details"));

    expect(
      screen.queryByText("Latest trace thought 1."),
    ).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "Latest trace thought 1.",
    );
    expect(opened.at(-1)?.detail.processEvent.count).toBe(4);
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("keeps compact process rows visually quiet instead of card-like", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-quiet-expanded-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "第一段足够长，需要展开才能看到完整内容。\n继续说明这一段的细节。",
        },
      },
      {
        id: "ai-quiet-expanded-2",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "第二段也足够长，需要展开才能看到完整内容。\n继续说明这一段的细节。",
        },
      },
    ];

    const { container } = renderWithProviders(
      <MessageGroup messages={messages} keepOpen />,
      {
        locale: "zh-CN",
      },
    );

    const row = screen.getByTestId("process-timeline-event-thinking");
    expect(row).not.toHaveClass("rounded-md");
    expect(row).not.toHaveClass("border");
    expect(row).not.toHaveClass("bg-muted");
    expect(row).not.toHaveClass("shadow");
    expect(container.querySelector("[data-cot-connector='true']")).toBeNull();
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
    fireEvent.click(screen.getByTitle("Open details"));

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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Open details"));

    expect(screen.queryByTitle("Hide saved steps")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/laser engraving market 2025/).length,
    ).toBeGreaterThan(0);
  });

  it("keeps completed code-mode traces concrete without action categories", () => {
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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
    // Raw reasoning_content now renders as a collapsed one-line trace row
    // (design: actual thinking trace in chronological order, truncated by
    // default, expands on click).
    expect(
      screen.getByText("Inspect the user request before editing."),
    ).toBeInTheDocument();
    expect(screen.getByText("frontend route structure")).toBeInTheDocument();
    expect(screen.queryByText(/Search sources/)).not.toBeInTheDocument();
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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
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

    // Raw reasoning trace renders as a collapsed timeline row (see above).
    expect(
      screen.getByText("Inspect the user request before editing."),
    ).toBeInTheDocument();
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
    // Raw reasoning trace renders as a collapsed timeline row (see above).
    expect(
      screen.getByText("First inspect the request."),
    ).toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();

    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
  });

  it("uses structured order instead of phase wording for the live frame", () => {
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
        id: "ai-current",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "先拆分候选细分赛道。",
          phase_id: "turn-1:progress:1",
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
    expect(screen.getByText("先拆分候选细分赛道。")).toBeInTheDocument();
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
    // The Action callback syntax is stripped, but the trailing narration
    // still renders as a collapsed trace row (raw-reasoning fallback).
    expect(screen.getByText("继续检查输出文件。")).toBeInTheDocument();
    expect(screen.queryByText("执行动作")).not.toBeInTheDocument();
    expect(screen.queryByText("整理调研结果")).not.toBeInTheDocument();
    expect(screen.queryByText(/ipython/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Action:/)).not.toBeInTheDocument();
    expect(screen.queryByText("执行中")).not.toBeInTheDocument();
  });

  it("does not infer a second narration lane from ordinary tool-bearing content", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-read",
        type: "ai",
        content: "我先读取消息组件，再把证据串起来。",
        tool_calls: [
          {
            id: "read-message-group",
            name: "read_file",
            args: { path: "frontend/src/messages/message-group.tsx" },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "zh-CN",
    });

    expect(
      screen.queryByText("我先读取消息组件，再把证据串起来。"),
    ).not.toBeInTheDocument();
    const executions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    const execution = executions[0]!;
    expect(execution).toHaveTextContent("message-group.tsx");
    expect(execution).not.toHaveTextContent("查看文件");
    expect(execution).not.toHaveTextContent("执行动作");
    expect(
      screen.queryByTestId("process-timeline-event-thinking"),
    ).not.toBeInTheDocument();
  });

  it("collapses consecutive tool targets into one quiet evidence row", () => {
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
    const executions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    expect(executions).toHaveLength(2);
    expect(executions[0]).toHaveTextContent("src");
    expect(executions[0]).toHaveTextContent("app.tsx");
    expect(executions[1]).toHaveTextContent("plan.md");
    const execution = executions[0]!;

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(execution);

    expect(opened.at(-1)?.detail.processEvent).toMatchObject({
      kind: "execution",
      count: 2,
    });
    expect(opened.at(-1)?.detail.processEvent.detail).toContain("src/app.tsx");

    fireEvent.click(
      screen.getAllByTestId("process-timeline-event-execution")[1]!,
    );
    expect(opened.at(-1)?.detail.processEvent.detail).toContain("plan.md");

    expect(screen.queryByText("已浏览目录")).not.toBeInTheDocument();
    expect(screen.queryByText("已读取")).not.toBeInTheDocument();
    expect(opened.at(-1)?.detail.processEvent.detail).toContain("plan.md");
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("reduces shell workarounds to concrete evidence without leaking local paths", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "root-1",
            name: "list_cwd",
            args: { path: "../.." },
          },
          {
            id: "read-group-1",
            name: "read_file",
            args: {
              path: "/Users/dangbei/Public/octopus/octopus-agent/frontend/src/components/workspace/messages/message-group.tsx",
            },
          },
          {
            id: "read-1",
            name: "read_file",
            args: {
              path: "/Users/dangbei/Public/octopus/octopus-agent/runtime/protocol/items.py",
            },
          },
          {
            id: "cat-1",
            name: "exec_shell",
            args: {
              command:
                "cat /Users/dangbei/Public/octopus/octopus-agent/runtime/protocol/items.py",
            },
          },
          {
            id: "copy-1",
            name: "exec_shell",
            args: {
              command:
                "cp /Users/dangbei/Public/octopus/octopus-agent/runtime/protocol/items.py /tmp/_items_readonly_copy.py",
            },
          },
          {
            id: "read-reducer-1",
            name: "exec_shell",
            args: {
              command:
                "sed -n '1,240p' /Users/dangbei/Public/octopus/octopus-agent/frontend/src/core/realtime/reducer.ts",
            },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    const executions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    const execution = executions[0]!;
    expect(execution).toHaveTextContent(
      "message-group.tsx · items.py · reducer.ts",
    );
    expect(execution).not.toHaveTextContent("/Users/");
    expect(execution).not.toHaveTextContent("../..");
    expect(execution).not.toHaveTextContent("cat ");
    expect(execution).not.toHaveTextContent("cp ");
    expect(execution).not.toHaveTextContent("_items_readonly_copy.py");
    // Shell file-read workarounds and concrete read_file calls are folded into
    // one evidence cluster so the transcript stays concise.
    expect(executions).toHaveLength(1);
  });

  it("attributes every execution inside a commentary interval to its visible anchor", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-progress",
        type: "ai",
        content: "我先核对这几个文件。",
        additional_kwargs: {
          public_progress: true,
          timeline_sequence: 1,
        },
      },
      {
        id: "ai-reads",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "read-a",
            name: "read_file",
            args: { path: "src/a.ts" },
            timelineSequence: 2,
          },
          {
            id: "read-b",
            name: "read_file",
            args: { path: "src/b.ts" },
            timelineSequence: 3,
          },
          {
            id: "read-c",
            name: "read_file",
            args: { path: "src/c.ts" },
            timelineSequence: 4,
          },
        ],
      },
      {
        id: "ai-final",
        type: "ai",
        content: "核对完成。",
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "zh-CN",
    });

    const executions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    expect(executions).toHaveLength(1);
    expect(executions[0]).toHaveTextContent("a.ts · b.ts · c.ts");

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(executions[0]!);

    const detail = opened.at(-1)?.detail.processEvent.detail as string;
    expect(detail).toContain("a.ts");
    expect(detail).toContain("b.ts");
    expect(detail).toContain("c.ts");
    expect(opened.at(-1)?.detail.processEvent.count).toBe(3);
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("keeps mixed-kind execution clusters separate within the same interval", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-progress",
        type: "ai",
        content: "读取并验证。",
        additional_kwargs: {
          public_progress: true,
          timeline_sequence: 1,
        },
      },
      {
        id: "ai-tools",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "read-a",
            name: "read_file",
            args: { path: "src/a.ts" },
            timelineSequence: 2,
          },
          {
            id: "read-b",
            name: "read_file",
            args: { path: "src/b.ts" },
            timelineSequence: 3,
          },
          {
            id: "run-test",
            name: "exec_shell",
            args: { command: "npm test" },
            timelineSequence: 4,
          },
        ],
      },
      {
        id: "ai-final",
        type: "ai",
        content: "完成。",
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} />, {
      locale: "zh-CN",
    });

    const executions = screen.getAllByTestId(
      "process-timeline-event-execution",
    );
    expect(executions).toHaveLength(2);
    expect(executions[0]).toHaveTextContent("a.ts · b.ts");
    expect(executions[1]).toHaveTextContent("运行");
  });

  it("does not render raw shell commands for a single shell tool call", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-shell",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "shell-1",
            name: "exec_shell",
            args: {
              command: "cat ~/.ssh/id_rsa && npm run typecheck",
            },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("运行")).toBeInTheDocument();
    expect(screen.queryByText(/cat ~\/.ssh\/id_rsa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/npm run typecheck/)).not.toBeInTheDocument();
  });

  it("uses a public fallback for unknown tool names", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-unknown-tool",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "custom-1",
            name: "mcp_secret_probe",
            args: {
              token: "sk-test-should-not-render",
            },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("执行操作")).toBeInTheDocument();
    expect(screen.queryByText(/mcp_secret_probe/)).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-test/)).not.toBeInTheDocument();
  });

  it("renders capability tools as a localized human action", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-capability-tool",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "capability-1",
            name: "use_capability",
            args: { capability: "deep_research" },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("使用能力")).toBeInTheDocument();
    expect(screen.getByText("deep_research")).toBeInTheDocument();
    expect(screen.queryByText("use_capability")).not.toBeInTheDocument();
  });

  it("keeps explicit human descriptions for unknown tools", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-described-tool",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "custom-2",
            name: "mcp_custom_bridge",
            args: {
              description: "同步外部任务状态",
            },
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("同步外部任务状态")).toBeInTheDocument();
    expect(screen.queryByText(/mcp_custom_bridge/)).not.toBeInTheDocument();
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

  it("opens right-side process details without leaked protocol or internal blocks", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-thinking",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary:
            "<read_only> </read_only>\n<TextBlock>先确认公开进展</TextBlock>\nAction: read_file\n失败原因：token=super-secret\n<ToolCallBlock>private tool args</ToolCallBlock>",
        },
      },
      {
        id: "ai-tool",
        type: "ai",
        content: "",
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

    expect(
      screen.queryByText(/read_only|ToolCallBlock|read_file/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/super-secret/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("process-timeline-event-thinking"));

    const processEvent = opened.at(-1)?.detail.processEvent;
    expect(processEvent).toMatchObject({
      kind: "thinking",
      summary: expect.stringContaining("先确认公开进展"),
    });
    expect(processEvent?.detail).toContain("先确认公开进展");
    expect(JSON.stringify(processEvent)).not.toMatch(
      /read_only|TextBlock|ToolCallBlock|private tool args|read_file|super-secret/i,
    );

    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
  });

  it("cleans public progress body before rendering it in the main timeline", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-public-progress",
        type: "ai",
        content:
          "<read_only> </read_only>\n<TextBlock>已确认主线展示。</TextBlock>\nAction: read_file\nObservation: token=super-secret",
        additional_kwargs: {
          public_progress: true,
        },
      },
    ];
    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText(/已确认主线展示/)).toBeInTheDocument();
    expect(
      screen.queryByText(/read_only|TextBlock|read_file|Observation/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/super-secret/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("public-progress-event"));
    const processEvent = opened.at(-1)?.detail.processEvent;
    expect(processEvent?.summary).toContain("已确认主线展示");
    expect(JSON.stringify(processEvent)).not.toMatch(
      /read_only|TextBlock|read_file|Observation|super-secret/i,
    );

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
    expect(visibleExecutions).toHaveLength(1);
    expect(visibleExecutions[0]).toHaveAttribute(
      "data-process-event-id",
      "read-7",
    );
    expect(visibleExecutions[0]).toHaveTextContent(
      "file-5.ts · file-6.ts · file-7.ts +5",
    );

    const opened: CustomEvent[] = [];
    const handleOpen = (event: Event) => opened.push(event as CustomEvent);
    window.addEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
    fireEvent.click(visibleExecutions[0]!);
    expect(opened.at(-1)?.detail.processEvent).toMatchObject({ count: 8 });
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "src/file-0.ts",
    );
    expect(opened.at(-1)?.detail.processEvent.detail).toContain(
      "src/file-7.ts",
    );
    window.removeEventListener(AGENT_WORKBENCH_OPEN_EVENT, handleOpen);
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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Open details"));
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
    fireEvent.click(screen.getByTitle("Open details"));
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

    expect(screen.getByTitle("Open details")).toBeInTheDocument();
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

describe("MessageGroup 紧凑模式叙事保真", () => {
  // 构造 6 轮「意图 → 工具 → 事实」长任务：意图消息的 reasoning 紧跟上一轮
  // 工具调用（iteration 由此递增），事实以 public_progress checkpoint 呈现。
  function buildLongRunMessages(): AIMessage[] {
    const intentMessage = (round: number): AIMessage => ({
      id: `ai-intent-${round}`,
      type: "ai",
      content: "",
      additional_kwargs: {
        public_reasoning_summary: `第 ${round} 轮意图：读取 round-${round}.ts`,
      },
    });
    const toolsMessage = (round: number): AIMessage => ({
      id: `ai-tools-${round}`,
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: `call-${round}`,
          name: "read_file",
          args: { path: `src/round-${round}.ts` },
        },
      ],
    });
    const factMessage = (round: number): AIMessage => ({
      id: `ai-fact-${round}`,
      type: "ai",
      content: `已确认第 ${round} 轮事实`,
      additional_kwargs: { public_progress: true },
    });

    const messages: AIMessage[] = [intentMessage(1), toolsMessage(1)];
    for (let round = 2; round <= 6; round += 1) {
      messages.push(
        intentMessage(round),
        factMessage(round - 1),
        toolsMessage(round),
      );
    }
    messages.push(factMessage(6));
    return messages;
  }

  it("长任务压缩后每轮至少保留一个叙事锚点、最新事实必留", () => {
    renderWithProviders(<MessageGroup messages={buildLongRunMessages()} />, {
      locale: "zh-CN",
    });

    // 6 个事实 checkpoint 全部被语义保底（每轮兜底锚点 + 最新事实）
    expect(screen.getAllByTestId("public-progress-event")).toHaveLength(6);
    for (let round = 1; round <= 6; round += 1) {
      expect(screen.getByText(`已确认第 ${round} 轮事实`)).toBeInTheDocument();
    }
    // 第 1 轮意图（该轮 intent 锚点）与最近一轮思考（latestThinking）可见
    expect(screen.getByText(/第 1 轮意图/)).toBeInTheDocument();
    expect(screen.getByText(/第 6 轮意图/)).toBeInTheDocument();
    // 中间轮的意图仍被压缩掉，完整事件链留在工作台
    expect(screen.queryByText(/第 3 轮意图/)).not.toBeInTheDocument();
    expect(screen.queryByText(/第 4 轮意图/)).not.toBeInTheDocument();
    expect(
      screen.getAllByTestId("process-timeline-event-thinking"),
    ).toHaveLength(2);
    // 纯过程组没有最终回答，不出现分界
    expect(screen.queryByTestId("final-answer-boundary")).toBeNull();
  });
});

describe("selectCompactTimelineItems 语义保真采样", () => {
  // 手搓 TimelineItem：每轮 intent commentary + 工具 + fact commentary
  function buildRoundItems(withRoles: boolean) {
    const items: TimelineItem[] = [];
    const intents: TimelineItem[] = [];
    const facts: TimelineItem[] = [];
    for (let round = 1; round <= 6; round += 1) {
      const intent: TimelineItem = {
        id: `intent-${round}`,
        type: "commentary",
        step: {
          id: `intent-step-${round}`,
          type: "commentary",
          commentary: `第 ${round} 轮意图`,
          iteration: round,
        },
        ...(withRoles ? { role: "intent" as const } : {}),
      };
      const tool: TimelineItem = {
        id: `tool-${round}`,
        type: "toolCall",
        step: {
          id: `call-${round}`,
          type: "toolCall",
          name: "read_file",
          args: { path: `src/round-${round}.ts` },
          iteration: round,
        },
        ...(withRoles ? { role: "execution" as const } : {}),
      };
      const fact: TimelineItem = {
        id: `fact-${round}`,
        type: "commentary",
        step: {
          id: `fact-step-${round}`,
          type: "commentary",
          commentary: `第 ${round} 轮事实`,
          iteration: round,
        },
        ...(withRoles ? { role: "fact" as const } : {}),
      };
      items.push(intent, tool, fact);
      intents.push(intent);
      facts.push(fact);
    }
    return { items, intents, facts };
  }

  it("每个 iteration 必留 intent 条目、最新 fact 必留，且返回原引用", () => {
    const { items, intents, facts } = buildRoundItems(true);

    const result = selectCompactTimelineItems(items);

    for (const intent of intents) {
      expect(result).toContain(intent);
    }
    expect(result).toContain(facts[5]!);
    // 保底已超额，较早的 fact 不再额外补样
    expect(result).not.toContain(facts[1]!);
    expect(result).not.toContain(facts[2]!);
    // 引用相等：选择器返回原 item，不破坏下游 React memo
    for (const item of result) {
      expect(items).toContain(item);
    }
    expect(result[0]).toBe(items[0]);
  });

  it("role 缺失的旧数据按位置兜底，行为正常", () => {
    const { items, intents, facts } = buildRoundItems(false);

    const result = selectCompactTimelineItems(items);

    // 角色由 assignTimelineRoles 在判定副本上补齐：第 1 轮首个 commentary
    // 推断为 intent，其余轮按位置取首个 commentary 兜底，最新 fact 必留
    for (const intent of intents) {
      expect(result).toContain(intent);
    }
    expect(result).toContain(facts[5]!);
    for (const item of result) {
      expect(items).toContain(item);
    }
  });

  it("短对话（commentary ≤ 4）行为完全不变", () => {
    const items: TimelineItem[] = [];
    const commentaries: TimelineItem[] = [];
    for (let round = 1; round <= 4; round += 1) {
      const commentary: TimelineItem = {
        id: `commentary-${round}`,
        type: "commentary",
        step: {
          id: `commentary-step-${round}`,
          type: "commentary",
          commentary: `进展 ${round}`,
          iteration: round,
        },
        role: round === 1 ? "intent" : "fact",
      };
      commentaries.push(commentary);
      items.push(commentary);
      if (round < 4) {
        items.push({
          id: `tool-${round}`,
          type: "toolCall",
          step: {
            id: `call-${round}`,
            type: "toolCall",
            name: "read_file",
            args: { path: `src/round-${round}.ts` },
            iteration: round,
          },
          role: "execution",
        });
      }
    }

    const result = selectCompactTimelineItems(items);

    for (const commentary of commentaries) {
      expect(result).toContain(commentary);
    }
  });
});

describe("MessageGroup 最终回答视觉分层", () => {
  const longAnswer = [
    "# 调查结论",
    "",
    "这是一段足够长的最终回答，用于触发最终回答判定阈值。",
    "",
    "1. 第一点结论",
    "2. 第二点结论",
    "3. 第三点结论",
    "4. 第四点结论",
    "",
    "这一段继续补充正文长度，确保超过 320 字符的最终回答阈值，",
    "使该消息被视为最终回答而不是过程旁白，从而在下方独立渲染。",
  ].join("\n");

  const answerMessage: AIMessage = {
    id: "ai-answer-with-tools",
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

  it("流式结束后过程段落与最终回答之间出现分界", () => {
    renderWithProviders(<MessageGroup messages={[answerMessage]} />, {
      locale: "zh-CN",
    });

    expect(screen.getByTestId("final-answer-boundary")).toBeInTheDocument();
  });

  it("流式进行中不渲染分界，避免跳动", () => {
    renderWithProviders(<MessageGroup messages={[answerMessage]} isLoading />, {
      locale: "zh-CN",
    });

    expect(screen.queryByTestId("final-answer-boundary")).toBeNull();
  });
});

describe("MessageGroup 收敛摘要行", () => {
  // 构造两个 phase 的流式任务：phase-1 已完成（含 commentary + 3 个 read_file），
  // phase-2 进行中。流式中 phase-1 应收敛为摘要行，含 phase 名称 + 关键统计。
  function buildMultiPhaseMessages(): AIMessage[] {
    return [
      // phase-1: commentary (phase intent) + 3 个 read_file
      {
        id: "ai-phase1-intent",
        type: "ai",
        content: "了解代码结构",
        additional_kwargs: {
          public_progress: true,
          phase_id: "turn-1:progress:1",
        },
      },
      {
        id: "ai-phase1-tools",
        type: "ai",
        content: "",
        tool_calls: [
          {
            id: "read-1",
            name: "read_file",
            args: { path: "src/auth.ts" },
            phaseId: "turn-1:progress:1",
          },
          {
            id: "read-2",
            name: "read_file",
            args: { path: "src/middleware.ts" },
            phaseId: "turn-1:progress:1",
          },
          {
            id: "read-3",
            name: "read_file",
            args: { path: "src/config.ts" },
            phaseId: "turn-1:progress:1",
          },
        ],
      },
      // phase-2: 进行中
      {
        id: "ai-phase2-intent",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "开始修改代码",
          phase_id: "turn-1:progress:2",
        },
      },
    ];
  }

  it("收敛摘要行包含 phase 名称 + 关键统计", () => {
    renderWithProviders(
      <MessageGroup messages={buildMultiPhaseMessages() as never} isLoading />,
      { locale: "zh-CN" },
    );

    const collapsed = screen.getByTestId("collapsed-history-phase");
    expect(collapsed).toBeInTheDocument();
    // phase 名称（来自 phase-1 的 commentary）
    expect(collapsed).toHaveTextContent("了解代码结构");
    // 关键统计（3 个 read_file → file_read 聚合）
    expect(collapsed).toHaveTextContent("查看了 3 个文件");
  });

  it("点击收敛摘要行展开对应 phase", () => {
    renderWithProviders(
      <MessageGroup messages={buildMultiPhaseMessages() as never} isLoading />,
      { locale: "zh-CN" },
    );

    const collapsed = screen.getByTestId("collapsed-history-phase");
    fireEvent.click(collapsed);
    // 展开后收敛行消失，phase 内容可见
    expect(screen.queryByTestId("collapsed-history-phase")).toBeNull();
  });
});

describe("reasoning duration replay", () => {
  it("回放时显示后端持久化的思考耗时", () => {
    const message = {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: {
        public_reasoning_summary: "分析需求",
        reasoning_duration_ms: 3500,
      },
    } as AIMessage;

    renderWithProviders(<MessageGroup messages={[message]} />, {
      locale: "zh-CN",
    });

    const thinkingRow = screen.getByTestId("process-timeline-event-thinking");
    expect(thinkingRow).toHaveTextContent("思考了 3.5s");
  });

  it("reasoning_duration_ms 为 0 时不显示耗时", () => {
    const message = {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: {
        public_reasoning_summary: "分析需求",
        reasoning_duration_ms: 0,
      },
    } as AIMessage;

    renderWithProviders(<MessageGroup messages={[message]} />, {
      locale: "zh-CN",
    });

    const thinkingRow = screen.getByTestId("process-timeline-event-thinking");
    expect(thinkingRow).not.toHaveTextContent(/思考了/);
  });

  it("缺少 reasoning_duration_ms 时不显示耗时", () => {
    const message = {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: {
        public_reasoning_summary: "分析需求",
      },
    } as AIMessage;

    renderWithProviders(<MessageGroup messages={[message]} />, {
      locale: "zh-CN",
    });

    const thinkingRow = screen.getByTestId("process-timeline-event-thinking");
    expect(thinkingRow).not.toHaveTextContent(/思考了/);
  });
});

describe("reasoning live timer from backend timestamp", () => {
  it("starts the live timer from reasoning_started_at", () => {
    vi.useFakeTimers();
    try {
      // 用 public_reasoning_summary 让最后一条 compact timeline item 是
      // reasoningGroup，从而 isCurrentlyThinking=true。reasoning_started_at
      // 指向 3.5 秒前；推进 1.5 秒后首个 interval tick 落在 +1s 处，
      // elapsed = (T0+1s) - (T0-3.5s) = 4.5s，越过 200ms 阈值，应渲染
      // `t.messageGrouping.thinkingDuration` 即「思考了 ...」。
      const message = {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "正在分析需求",
          reasoning_started_at: new Date(Date.now() - 3500).toISOString(),
        },
      } as AIMessage;

      renderWithProviders(<MessageGroup messages={[message]} isLoading />, {
        locale: "zh-CN",
      });

      act(() => {
        vi.advanceTimersByTime(1500);
      });

      const thinking = screen.getByTestId(
        "process-timeline-event-thinking",
      );
      expect(thinking).toBeInTheDocument();
      expect(thinking).toHaveTextContent("思考了");
    } finally {
      vi.useRealTimers();
    }
  });

  it("falls back to Date.now() when reasoning_started_at is missing", () => {
    vi.useFakeTimers();
    try {
      // 旧数据没有 reasoning_started_at，计时器回退到 Date.now()；
      // 推进时间后不崩溃，thinking 行仍可定位。
      const message = {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          public_reasoning_summary: "正在分析",
        },
      } as AIMessage;

      renderWithProviders(<MessageGroup messages={[message]} isLoading />, {
        locale: "zh-CN",
      });

      act(() => {
        vi.advanceTimersByTime(1500);
      });

      expect(
        screen.getByTestId("process-timeline-event-thinking"),
      ).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
