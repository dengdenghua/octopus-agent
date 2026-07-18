import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AIMessage, Message } from "@/core/api/types";
import { renderWithProviders } from "@/test/harness";

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

    fireEvent.click(screen.getByText("View 1 saved steps"));

    expect(screen.queryByText(/verification/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/verification required/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText("notes.md")).toBeInTheDocument();
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
  it("keeps only the latest thinking step visible while streaming", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: [{ type: "thinking", thinking: "先扫一遍上下文" }],
      },
      {
        id: "ai-2",
        type: "ai",
        content: [{ type: "thinking", thinking: "再整理成可执行步骤" }],
      },
    ];

    renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      {
        locale: "zh-CN",
      },
    );

    expect(screen.getByText("思考中")).toBeInTheDocument();
    const replayToggle = screen.getByText("过程回放 1 步");
    const currentFrame = screen.getByText("再整理成可执行步骤");
    expect(replayToggle).toBeInTheDocument();
    expect(currentFrame).toBeInTheDocument();
    expect(
      replayToggle.compareDocumentPosition(currentFrame) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByText("先扫一遍上下文")).not.toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("02")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("过程回放 1 步"));

    expect(screen.getByText("收起过程回放")).toBeInTheDocument();
    const previousFrame = screen.getByText("先扫一遍上下文");
    expect(previousFrame).toBeInTheDocument();
    expect(
      previousFrame.compareDocumentPosition(currentFrame) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps kept-open traces on the current frame and replays prior steps on demand", () => {
    const messages: AIMessage[] = Array.from({ length: 4 }, (_, index) => ({
      id: `ai-${index + 1}`,
      type: "ai",
      content: [
        {
          type: "thinking",
          thinking: `Latest trace thought ${index + 1}.`,
        },
      ],
    }));

    renderWithProviders(
      <MessageGroup messages={messages as never} keepOpen />,
      {
        locale: "en-US",
      },
    );

    expect(screen.getByText("Replay 3 previous steps")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(screen.queryByText("03")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Latest trace thought 1."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Latest trace thought 4.")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Replay 3 previous steps"));

    expect(screen.getByText("Hide process replay")).toBeInTheDocument();
    expect(
      screen.getAllByText("Latest trace thought 1.").length,
    ).toBeGreaterThan(0);
  });

  it("classifies obvious search and tool-protocol chunks as actions", () => {
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

    expect(screen.getByText("Searching")).toBeInTheDocument();
    expect(screen.queryByText("Thought")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Let me search for more specific data on this."),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Replay 1 previous steps"));

    expect(
      screen.queryByText("Let me search for more specific data on this."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Search sources: AI Agent SMB opportunity"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/web_search/)).not.toBeInTheDocument();
  });

  it("nests long numbered thinking steps under their own disclosure row", () => {
    const hiddenTail = "UNIQUE_NESTED_REASONING_TAIL";
    const messages: AIMessage[] = [
      {
        id: "ai-1",
        type: "ai",
        content: [
          {
            type: "thinking",
            thinking: `First I will inspect the request and summarize the path before touching the UI. ${"extra context ".repeat(24)} ${hiddenTail}`,
          },
        ],
      },
      {
        id: "ai-2",
        type: "ai",
        content: [
          {
            type: "thinking",
            thinking: "Second I will choose the next interface step.",
          },
        ],
      },
    ];

    renderWithProviders(<MessageGroup messages={messages as never} />, {
      locale: "en-US",
    });

    fireEvent.click(screen.getByText("View 2 saved steps"));

    expect(screen.getByText("01")).toBeInTheDocument();
    expect(screen.getByText("02")).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(hiddenTail))).not.toBeInTheDocument();

    const [, nestedSummary] = screen.getAllByText(
      /First I will inspect the request/,
    );
    fireEvent.click(nestedSummary!);

    expect(screen.getByText(new RegExp(hiddenTail))).toBeInTheDocument();
  });

  it("collapses saved steps behind a compact disclosure after completion", () => {
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

    expect(screen.getByText("View 2 saved steps")).toBeInTheDocument();
    expect(screen.queryByText("01")).not.toBeInTheDocument();
    expect(
      screen.queryByText(/laser engraving market 2025/),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("View 2 saved steps"));

    expect(screen.getByText("Hide saved steps")).toBeInTheDocument();
    expect(screen.getByText("Clarify task direction")).toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();
  });

  it("keeps completed code-mode traces behind the saved-steps disclosure", () => {
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

    expect(screen.getByText("View 2 saved steps")).toBeInTheDocument();
    expect(
      screen.queryByText("Inspect the user request before editing."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("frontend route structure"),
    ).not.toBeInTheDocument();
  });

  it("collapses a live code-mode trace when the same turn becomes historical", () => {
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

    expect(screen.getByText("Hide process replay")).toBeInTheDocument();
    expect(screen.getByText("Clarify task direction")).toBeInTheDocument();

    rerender(<MessageGroup codeMode messages={messages as never} />);

    expect(screen.getByText("View 2 saved steps")).toBeInTheDocument();
    expect(screen.queryByText("Hide saved steps")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Clarify task direction"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("live-process-strip")).not.toBeInTheDocument();
  });

  it("auto-expands code-mode traces while the turn is live", () => {
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
    expect(screen.getByTestId("live-process-strip")).toBeInTheDocument();
    expect(screen.getByText("Live process")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("1 replay step")).toBeInTheDocument();
    expect(screen.getByText("Hide process replay")).toBeInTheDocument();
    expect(screen.getByText("Clarify task direction")).toBeInTheDocument();
    expect(screen.getAllByText(/frontend route structure/).length).toBe(2);
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

    expect(screen.queryByTestId("live-process-strip")).not.toBeInTheDocument();
    expect(
      screen.getAllByText(/conversational streaming rhythm/).length,
    ).toBeGreaterThan(0);
  });

  it("marks the live code process strip as waiting when user confirmation is needed", () => {
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

    expect(screen.getByTestId("live-process-strip")).toBeInTheDocument();
    expect(screen.getByText("实时进程")).toBeInTheDocument();
    expect(screen.getByText("待确认")).toBeInTheDocument();
    expect(screen.getByText("需要你的帮助")).toBeInTheDocument();
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

    expect(screen.queryByText("View 2 saved steps")).not.toBeInTheDocument();
    expect(screen.getByText("Replay 1 previous steps")).toBeInTheDocument();
    expect(
      screen.queryByText("First inspect the request."),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("Replay 1 previous steps"));

    expect(screen.getByText("Clarify task direction")).toBeInTheDocument();
  });

  it("keeps the lead-in before Phase 1 visible during live streaming", () => {
    const messages: AIMessage[] = [
      {
        id: "ai-lead-in",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "这个问题需要先确认赛道边界，否则机会点会太泛。",
        },
      },
      {
        id: "ai-phase-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: "Phase 1: 先拆分候选细分赛道。",
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
    expect(screen.queryByText(/过程回放/)).not.toBeInTheDocument();
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

  it("uses completed labels for historical steps and active labels for the latest step", () => {
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

    expect(screen.getByText("过程回放 1 步")).toBeInTheDocument();
    expect(screen.getByText("正在搜索")).toBeInTheDocument();
    expect(screen.queryByText("思考中")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("过程回放 1 步"));

    expect(screen.getByText("\u641c\u7d22\u8d44\u6599")).toBeInTheDocument();
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

    expect(screen.getByText("正在搜索")).toBeInTheDocument();
    expect(screen.getByText(/laser engraving market 2025/)).toBeInTheDocument();
  });

  it("shows search results under each web search action", () => {
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

    expect(screen.getByText("已搜索到 2 个网页")).toBeInTheDocument();
    expect(screen.getByText("OpenClaw GitHub repo")).toBeInTheDocument();
    expect(screen.getByText("OpenClaw docs")).toBeInTheDocument();
  });

  it("keeps Action callback text out of thinking groups", () => {
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
    expect(screen.getByText("执行动作")).toBeInTheDocument();

    fireEvent.click(screen.getByText("过程回放 1 步"));

    expect(screen.getByText("整理调研结果")).toBeInTheDocument();
    expect(screen.getByText("\u6267\u884c\u52a8\u4f5c")).toBeInTheDocument();
    expect(screen.queryByText(/ipython/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Action:/)).not.toBeInTheDocument();
    expect(screen.queryByText("执行中")).not.toBeInTheDocument();
  });

  it("uses specific labels for common action categories", () => {
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
    expect(screen.getByText("正在写入文件")).toBeInTheDocument();

    fireEvent.click(screen.getByText("过程回放 2 步"));

    expect(screen.getByText("已浏览目录")).toBeInTheDocument();
    expect(screen.getByText("已读取")).toBeInTheDocument();
  });
});

describe("MessageGroup streaming lifecycle", () => {
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
        ],
      },
      {
        id: "tool-1",
        type: "tool",
        content: "search results here",
        tool_call_id: "search-1",
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup messages={messages as never} isLoading />,
      { locale: "en-US" },
    );

    expect(screen.getByText(/test query/)).toBeInTheDocument();

    rerender(<MessageGroup messages={messages as never} />);

    expect(screen.getByText("View 2 saved steps")).toBeInTheDocument();
    fireEvent.click(screen.getByText("View 2 saved steps"));
    expect(screen.getByText(/test query/)).toBeInTheDocument();
  });

  it("keeps reasoning content stable when streaming tokens arrive", () => {
    const makeMessages = (reasoning: string): AIMessage[] => [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: { reasoning_content: reasoning },
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup messages={makeMessages("Thinking about phase one")} isLoading />,
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

    expect(screen.getByTestId("live-process-strip")).toBeInTheDocument();

    rerender(<MessageGroup codeMode messages={messages as never} />);

    expect(screen.queryByTestId("live-process-strip")).not.toBeInTheDocument();
  });

  it("preserves user-opened reasoning groups across streaming updates", () => {
    const makeMessages = (reasoning: string): AIMessage[] => [
      {
        id: "ai-1",
        type: "ai",
        content: "",
        additional_kwargs: {
          reasoning_content: [
            "Reasoning step 1 with enough text to trigger nesting. ".repeat(12),
            reasoning,
          ].join("\n\n"),
        },
      },
      {
        id: "ai-2",
        type: "ai",
        content: "",
        additional_kwargs: { reasoning_content: "Reasoning step 3" },
      },
    ];

    const { rerender } = renderWithProviders(
      <MessageGroup messages={makeMessages("Reasoning step 2")} keepOpen />,
      { locale: "en-US" },
    );

    fireEvent.click(screen.getByText(/Replay \d+ previous steps/));
    expect(screen.getByText(/Reasoning step 1/)).toBeInTheDocument();

    const nestedTriggers = screen.getAllByText(/Reasoning step 1/);
    const nestedTrigger = nestedTriggers.find(
      (el) => el.closest("[data-state]") !== null,
    );
    if (nestedTrigger) {
      fireEvent.click(nestedTrigger);
      expect(screen.getByText(/Reasoning step 2/)).toBeInTheDocument();
    }

    rerender(
      <MessageGroup
        messages={makeMessages("Reasoning step 2 extended")}
        keepOpen
      />,
    );

    expect(screen.getByText(/Replay \d+ previous steps/)).toBeInTheDocument();
    expect(screen.getByText(/Reasoning step 3/)).toBeInTheDocument();
  });

  it("handles mixed content + tool calls in the same AI message", () => {
    const message: AIMessage = {
      id: "ai-mixed",
      type: "ai",
      content: "Let me look this up for you.",
      tool_calls: [
        {
          id: "search-1",
          name: "web_search",
          args: { query: "reference docs" },
        },
      ],
    };

    renderWithProviders(<MessageGroup messages={[message]} isLoading />, {
      locale: "en-US",
    });

    expect(screen.getByText(/reference docs/)).toBeInTheDocument();
    expect(screen.getByText(/Let me look this up/)).toBeInTheDocument();
  });
});
