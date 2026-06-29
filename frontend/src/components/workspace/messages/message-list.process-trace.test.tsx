import { act, fireEvent, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { AIMessage, Message } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { AgentThreadState } from "@/core/threads";
import { SubtasksProvider } from "@/core/tasks/context";
import { renderWithProviders } from "@/test/harness";

import type { LiveToolEvent } from "../live-tool-timeline";
import { ThreadProviders } from "./context";
import { MESSAGE_LIST_TIMEOUT_WARNING_MS, MessageList } from "./message-list";

vi.mock("../artifacts", () => ({
  useArtifacts: () => ({
    setOpen: vi.fn(),
    autoOpen: false,
    autoSelect: false,
    selectedArtifact: null,
    select: vi.fn(),
  }),
}));

vi.mock("@/core/settings", () => ({
  useLocalSettings: () => [
    {
      display: {
        chat_font_size: "medium",
      },
    },
    vi.fn(),
  ],
}));

function message(id: string, type: Message["type"], content: string): Message {
  return { id, type, content };
}

function toolEvent(
  name: string,
  overrides: Partial<LiveToolEvent> = {},
): LiveToolEvent {
  return {
    id: `${name}-${overrides.status ?? "done"}`,
    name,
    status: "done",
    startedAt: 1000,
    iteration: 1,
    ...overrides,
  };
}

function mockThread(
  overrides: Partial<BaseStream<AgentThreadState>> = {},
): BaseStream<AgentThreadState> {
  const messages = overrides.messages ?? [];
  return {
    messages,
    streamingMessage: null,
    subgraphStreams: {},
    values: {
      title: "",
      messages,
      artifacts: [],
    },
    isLoading: false,
    isThreadLoading: false,
    error: undefined,
    stop: vi.fn(),
    refresh: vi.fn(),
    submit: vi.fn(),
    threadId: "thread-1",
    ...overrides,
  };
}

function messageListTree({
  thread,
  liveToolEvents = [],
  lastTurnToolEvents = [],
  mode = "code",
  currentAgent = null,
  agentRoster = [],
  completedAgentOutput = false,
  showSenderName = false,
}: {
  thread: BaseStream<AgentThreadState>;
  liveToolEvents?: LiveToolEvent[];
  lastTurnToolEvents?: LiveToolEvent[];
  mode?: "chat" | "code";
  completedAgentOutput?: boolean;
  currentAgent?: {
    name: string;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
  } | null;
  agentRoster?: Array<{
    name?: string | null;
    agent_id?: string | null;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
    role?: string | null;
  }>;
  showSenderName?: boolean;
}) {
  return (
    <SubtasksProvider>
      <ThreadProviders thread={thread}>
        <MessageList
          threadId="thread-1"
          thread={thread}
          paddingBottom={0}
          liveToolEvents={liveToolEvents}
          lastTurnToolEvents={lastTurnToolEvents}
          mode={mode}
          completedAgentOutput={completedAgentOutput}
          currentAgent={currentAgent}
          agentRoster={agentRoster}
          showSenderName={showSenderName}
        />
      </ThreadProviders>
    </SubtasksProvider>
  );
}

function renderMessageList(args: {
  thread: BaseStream<AgentThreadState>;
  liveToolEvents?: LiveToolEvent[];
  lastTurnToolEvents?: LiveToolEvent[];
  mode?: "chat" | "code";
  locale?: "en-US" | "zh-CN";
  currentAgent?: {
    name: string;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
  } | null;
  agentRoster?: Array<{
    name?: string | null;
    agent_id?: string | null;
    display_name?: string | null;
    avatar_url?: string | null;
    icon?: string | null;
    role?: string | null;
  }>;
  showSenderName?: boolean;
  completedAgentOutput?: boolean;
}) {
  return renderWithProviders(messageListTree(args), {
    locale: args.locale ?? "en-US",
    initialRoute: "/workspace/chats/thread-1",
  });
}

describe("MessageList process trace lifecycle", () => {
  test("uses team roster avatars for assistant messages without avatar metadata", () => {
    const thread = mockThread({
      messages: [
        message("user-1", "human", "你好"),
        message("assistant-1", "ai", "你好，我是 Eve。"),
      ],
    });

    renderMessageList({
      thread,
      mode: "chat",
      showSenderName: true,
      agentRoster: [
        {
          name: "general",
          display_name: "Eve",
          avatar_url: "/api/agents/general/avatar",
          role: "tl",
        },
      ],
    });

    expect(screen.getByText("Eve")).toBeInTheDocument();
    expect(screen.getByText("队长")).toBeInTheDocument();
    expect(screen.getByAltText("Eve")).toHaveAttribute(
      "src",
      expect.stringContaining("/api/agents/general/avatar"),
    );
  });

  test("does not render a completed process trace block in chat answers", () => {
    const messages = [
      message("user-1", "human", "What is NAS?"),
      message("assistant-1", "ai", "NAS is network-attached storage."),
    ];
    const thread = mockThread({ messages });

    renderMessageList({
      thread,
      lastTurnToolEvents: [
        toolEvent("read_file", {
          id: "read-1",
          input: { path: "notes/nas.md" },
        }),
      ],
      mode: "chat",
    });

    expect(
      screen.getByText("NAS is network-attached storage."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Process details/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Thinking process/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Read notes\/nas\.md/)).not.toBeInTheDocument();
  });

  test("keeps completed process traces compact even when they are the latest turn", () => {
    const oldTrace: AIMessage = {
      id: "assistant-old",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: "Inspect the old market request.",
      },
      tool_calls: [
        {
          id: "old-search",
          name: "web_search",
          args: { query: "old market query" },
        },
      ],
    };
    const latestTrace: AIMessage = {
      id: "assistant-latest",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: "Inspect the latest market request.",
      },
      tool_calls: [
        {
          id: "latest-search",
          name: "web_search",
          args: { query: "latest market query" },
        },
      ],
    };
    const messages: Message[] = [
      message("user-old", "human", "first request"),
      oldTrace,
      message("user-latest", "human", "second request"),
      latestTrace,
    ];
    const thread = mockThread({ messages });

    renderMessageList({ thread });

    const savedStepToggles = screen.getAllByText("View 2 saved steps");
    expect(savedStepToggles).toHaveLength(2);
    expect(screen.queryByText(/old market query/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Inspect the old market request."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/latest market query/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("Inspect the latest market request."),
    ).not.toBeInTheDocument();

    fireEvent.click(savedStepToggles[0]!);

    expect(screen.getByText(/old market query/)).toBeInTheDocument();
    expect(screen.queryByText(/latest market query/)).not.toBeInTheDocument();
  });

  test("expands only the actively streaming process trace", () => {
    const oldTrace: AIMessage = {
      id: "assistant-old",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: "Inspect the old market request.",
      },
      tool_calls: [
        {
          id: "old-search",
          name: "web_search",
          args: { query: "old market query" },
        },
      ],
    };
    const latestTrace: AIMessage = {
      id: "assistant-latest",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: "Inspect the actively streaming market request.",
      },
      tool_calls: [
        {
          id: "latest-search",
          name: "web_search",
          args: { query: "active market query" },
        },
      ],
    };
    const messages: Message[] = [
      message("user-old", "human", "first request"),
      oldTrace,
      message("user-latest", "human", "second request"),
      latestTrace,
    ];
    const thread = mockThread({
      messages,
      streamingMessage: latestTrace,
      isLoading: true,
    });

    renderMessageList({ thread });

    expect(screen.getByText("View 2 saved steps")).toBeInTheDocument();
    expect(screen.getByTestId("live-process-strip")).toBeInTheDocument();
    expect(screen.queryByText(/old market query/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/active market query/).length).toBe(2);
    expect(
      screen.queryByText("Inspect the actively streaming market request."),
    ).not.toBeInTheDocument();
  });

  test("does not mark a delivered run red for partial tool failures", () => {
    const messages: Message[] = [
      message("user-1", "human", "Write a research report"),
      message("assistant-1", "ai", "Report artifact generated."),
    ];
    const thread = mockThread({
      messages,
      error: new Error("some web searches failed"),
    });
    const { container } = renderMessageList({
      thread,
      completedAgentOutput: true,
      lastTurnToolEvents: [
        toolEvent("web_search", {
          id: "search-error",
          status: "error",
          input: { query: "source timeout" },
        }),
        toolEvent("write_file", {
          id: "write-final",
          status: "done",
          input: { path: "/tmp/workspace/output/final/report.md" },
        }),
      ],
    });

    expect(
      container.querySelector('[data-turn-marker-status="error"]'),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Report artifact generated.")).toBeInTheDocument();
  });
});

describe("MessageList reasoning privacy", () => {
  test("does not derive visible thinking from raw reasoning content", () => {
    const privateChineseReasoning =
      '\u7528\u6237\u95ee\u6211"\u4f60\u662f\u8c01"\uff0c\u6839\u636e\u6211\u7684\u8eab\u4efd\uff0c\u6211\u5e94\u8be5\u56de\u7b54"\u6211\u662f Octopus"\u3002';
    const assistant: AIMessage = {
      id: "assistant-private-reasoning",
      type: "ai",
      content: "\u6211\u662f Octopus\u3002",
      additional_kwargs: {
        reasoning_content: [
          privateChineseReasoning,
          'The user asks "who are you".',
          "Per SOUL.md and the hard system rule, I should answer as the current agent persona.",
        ].join("\n"),
      },
    };
    const thread = mockThread({
      messages: [message("user-1", "human", "\u4f60\u662f\u8c01"), assistant],
    });

    renderMessageList({ thread, locale: "zh-CN" });

    expect(screen.getByText("\u6211\u662f Octopus\u3002")).toBeInTheDocument();
    expect(
      screen.queryByText(/\u601d\u8003\u8fc7\u7a0b/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(privateChineseReasoning)).not.toBeInTheDocument();
    expect(screen.queryByText(/SOUL\.md/)).not.toBeInTheDocument();
  });

  test("does not expose raw reasoning-only streaming messages", () => {
    const leakedReasoning =
      "好的，用户之前发了很长一段关于我是Octopus的系统指令，现在又发了当前日期，我应该先判断是否需要工具。";
    const assistant: AIMessage = {
      id: "assistant-reasoning-only",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: leakedReasoning,
      },
    };
    const thread = mockThread({
      messages: [message("user-1", "human", "请只回复收到"), assistant],
      streamingMessage: assistant,
      isLoading: true,
    });

    renderMessageList({ thread, locale: "zh-CN" });

    expect(screen.queryByText(leakedReasoning)).not.toBeInTheDocument();
    expect(screen.queryByText(/系统指令/)).not.toBeInTheDocument();
    expect(screen.queryByText(/当前日期/)).not.toBeInTheDocument();
  });

  test("renders explicitly public reasoning summaries without exposing raw reasoning", () => {
    const publicSummary =
      "\u6211\u4f1a\u7b80\u8981\u8bf4\u660e\u8eab\u4efd\u3002";
    const assistant: AIMessage = {
      id: "assistant-public-summary",
      type: "ai",
      content: "\u6211\u662f Octopus\u3002",
      additional_kwargs: {
        reasoning_content:
          "Per SOUL.md and the hard system rule, keep this private.",
        public_reasoning_summary: publicSummary,
      },
    };
    const thread = mockThread({
      messages: [message("user-1", "human", "\u4f60\u662f\u8c01"), assistant],
      streamingMessage: assistant,
      isLoading: true,
    });

    renderMessageList({ thread, locale: "zh-CN" });

    expect(screen.getByText(/\u601d\u8003\u8fc7\u7a0b/)).toBeInTheDocument();
    expect(screen.getByText(publicSummary)).toBeInTheDocument();
    expect(screen.queryByText(/SOUL\.md/)).not.toBeInTheDocument();
  });
});

describe("MessageList output summaries", () => {
  test("defers current-turn file summaries until streaming finishes", () => {
    const reportWithChange: AIMessage = {
      id: "assistant-report",
      type: "ai",
      content: `# NAS research report\n\n${"final report paragraph ".repeat(40)}`,
      tool_calls: [
        {
          id: "change-1",
          name: "file_change",
          args: {
            changes: [
              {
                path: "data/workspaces/thread-1/nas_market_research_plan.md",
                op: "update",
                diff: [
                  "--- a/data/workspaces/thread-1/nas_market_research_plan.md",
                  "+++ b/data/workspaces/thread-1/nas_market_research_plan.md",
                  "@@",
                  "-old",
                  "+new",
                  "+another",
                ].join("\n"),
              },
            ],
          },
        },
      ],
    };
    const messages: Message[] = [
      message("user-1", "human", "做一个 nas 调研"),
      reportWithChange,
    ];
    const loadingThread = mockThread({
      messages,
      streamingMessage: reportWithChange,
      isLoading: true,
    });

    const { rerender } = renderMessageList({
      thread: loadingThread,
      locale: "zh-CN",
    });

    expect(screen.getByText(/NAS research report/)).toBeInTheDocument();
    expect(
      screen.queryByText(/\u5df2\u7f16\u8f91 1 \u4e2a\u6587\u4ef6/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "data/workspaces/thread-1/nas_market_research_plan.md",
      ),
    ).not.toBeInTheDocument();

    const settledThread = mockThread({ messages });
    rerender(messageListTree({ thread: settledThread }));

    const summaryLabel = screen.getAllByText(
      /\u5df2\u7f16\u8f91 1 \u4e2a\u6587\u4ef6/,
    )[0]!;
    expect(summaryLabel).toBeInTheDocument();
    expect(summaryLabel.closest(".ml-11")).toBeInTheDocument();
    expect(
      screen.getByText("data/workspaces/thread-1/nas_market_research_plan.md"),
    ).toBeInTheDocument();
  });
});

describe("MessageList stalled-run warning", () => {
  test("renders verification-gate failures as an inline actionable banner", () => {
    const thread = mockThread({
      messages: [
        message("user-1", "human", "Edit the code"),
        message("assistant-1", "ai", "Updated the file."),
      ],
      error: new Error(
        "Code changes were produced but no verification step was recorded before final answer.",
      ),
    });

    renderMessageList({ thread });

    expect(
      screen.getByText(/Code changes need verification before Octopus/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/This reply was interrupted/i),
    ).not.toBeInTheDocument();
  });

  test("does not leave an orphan assistant avatar for hidden auto-verification steps", () => {
    const thread = mockThread({
      messages: [
        message("user-1", "human", "continue"),
        {
          id: "ai-verify",
          type: "ai",
          content: "",
          tool_calls: [
            {
              id: "verify-1",
              name: "verification",
              args: {},
            },
          ],
        } as AIMessage,
        {
          id: "tool-verify-1",
          type: "tool",
          content: "verification required",
          tool_call_id: "verify-1",
        },
      ],
    });

    renderMessageList({
      thread,
      currentAgent: {
        name: "general",
        display_name: "Octopus",
        avatar_url: "/api/agents/general/avatar",
        icon: null,
      },
    });

    expect(
      screen.queryByText(/verification required/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByAltText("Octopus")).not.toBeInTheDocument();
  });

  test("warns only after a loading run stops making visible progress", () => {
    vi.useFakeTimers();
    try {
      const messages = [
        message("user-1", "human", "Write a report"),
        message("assistant-1", "ai", "Planning"),
      ];
      const thread = mockThread({
        messages,
        streamingMessage: messages[1],
        isLoading: true,
      });

      renderMessageList({ thread });

      act(() => {
        vi.advanceTimersByTime(MESSAGE_LIST_TIMEOUT_WARNING_MS - 1_000);
      });
      expect(screen.queryByText(/No progress for/)).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(2_000);
      });
      expect(screen.getByText(/No progress for/)).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  test("resets the warning timer when streaming content advances", () => {
    vi.useFakeTimers();
    try {
      const firstMessages = [
        message("user-1", "human", "Write a report"),
        message("assistant-1", "ai", "Planning"),
      ];
      const firstThread = mockThread({
        messages: firstMessages,
        streamingMessage: firstMessages[1],
        isLoading: true,
      });
      const { rerender } = renderMessageList({ thread: firstThread });

      act(() => {
        vi.advanceTimersByTime(60_000);
      });

      const nextMessages = [
        firstMessages[0]!,
        message("assistant-1", "ai", "Planning\nCollecting sources"),
      ];
      const nextThread = mockThread({
        messages: nextMessages,
        streamingMessage: nextMessages[1],
        isLoading: true,
      });

      rerender(messageListTree({ thread: nextThread }));

      act(() => {
        vi.advanceTimersByTime(60_000);
      });
      expect(screen.queryByText(/No progress for/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
