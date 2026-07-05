import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AIMessage, Message, ToolMessage } from "@/core/api/types";
import type { BaseStream } from "@/core/api/use-stream-types";
import type { AgentThreadState } from "@/core/threads";
import { SubtasksProvider } from "@/core/tasks/context";
import { renderWithProviders } from "@/test/harness";

import { ThreadProviders } from "./context";
import { MessageList } from "./message-list";
import {
  extractResultUrl,
  MessageOutputSummary,
} from "./message-output-summary";

const selectArtifact = vi.fn();
const setArtifactsOpen = vi.fn();

vi.mock("../artifacts", () => ({
  useArtifacts: () => ({
    setOpen: setArtifactsOpen,
    autoOpen: false,
    autoSelect: false,
    selectedArtifact: null,
    select: selectArtifact,
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

function renderMessageList(
  thread: BaseStream<AgentThreadState>,
  locale: "en-US" | "zh-CN" = "zh-CN",
) {
  return renderWithProviders(
    <SubtasksProvider>
      <ThreadProviders thread={thread}>
        <MessageList
          threadId="thread-1"
          thread={thread}
          paddingBottom={0}
          mode="chat"
        />
      </ThreadProviders>
    </SubtasksProvider>,
    { locale, initialRoute: "/workspace/realtime/thread-1" },
  );
}

/** Realistic turn: human prompt → tool-call AI (verification) → tool
 *  result → plain assistant final answer. */
function verificationTurnMessages(): {
  human: Message;
  verificationAi: AIMessage;
  verificationResult: ToolMessage;
  finalAnswer: Message;
} {
  const human: Message = {
    id: "user-1",
    type: "human",
    content: [
      "修复登录页的报错",
      "<uploaded_files>",
      "- notes.txt (1 KB)",
      "  Path: /tmp/notes.txt",
      "</uploaded_files>",
    ].join("\n"),
  };
  const verificationAi: AIMessage = {
    id: "ai-tools",
    type: "ai",
    content: "",
    tool_calls: [{ id: "verify-1", name: "run_tests", args: {} }],
  };
  const verificationResult: ToolMessage = {
    id: "tool-verify-1",
    type: "tool",
    content: '{"success": true, "stdout": "12 passed"}',
    tool_call_id: "verify-1",
  };
  const finalAnswer: Message = {
    id: "ai-final",
    type: "ai",
    content: "已修复登录页报错，测试全部通过。",
  };
  return { human, verificationAi, verificationResult, finalAnswer };
}

describe("MessageOutputSummary", () => {
  beforeEach(() => {
    selectArtifact.mockClear();
    setArtifactsOpen.mockClear();
    vi.unstubAllGlobals();
  });

  it("renders generated artifacts and opens the artifact panel", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "Done",
      tool_calls: [
        {
          id: "artifact-1",
          name: "artifact",
          args: {
            path: "reports/README.md",
            title: "README.md",
            kind: "Markdown",
          },
        },
      ],
    };

    renderWithProviders(<MessageOutputSummary messages={[message]} />, {
      locale: "zh-CN",
    });

    fireEvent.click(screen.getByText("README.md"));

    expect(screen.getByText("产物汇总")).toBeInTheDocument();
    expect(screen.getByText("Markdown")).toBeInTheDocument();
    expect(selectArtifact).toHaveBeenCalledWith("reports/README.md");
    expect(setArtifactsOpen).toHaveBeenCalledWith(true);
  });

  it("summarizes file changes with diff counts", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "Done",
      tool_calls: [
        {
          id: "change-1",
          name: "file_change",
          args: {
            changes: [
              {
                path: "runtime/safety/regeneration/native_llm_replay.py",
                op: "update",
                diff: [
                  "--- a/runtime/safety/regeneration/native_llm_replay.py",
                  "+++ b/runtime/safety/regeneration/native_llm_replay.py",
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

    renderWithProviders(<MessageOutputSummary messages={[message]} />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("已编辑 1 个文件")).toBeInTheDocument();
    expect(
      screen.getByText("runtime/safety/regeneration/native_llm_replay.py"),
    ).toBeInTheDocument();
    expect(screen.getAllByText("+2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-1").length).toBeGreaterThan(0);
  });

  it("labels newly created files as generated artifacts", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "Done",
      tool_calls: [
        {
          id: "change-1",
          name: "file_change",
          args: {
            changes: [
              {
                path: "data/workspaces/thread-1/output/final/nas_market_research_plan.md",
                op: "create",
                diff: [
                  "--- /dev/null",
                  "+++ b/data/workspaces/thread-1/output/final/nas_market_research_plan.md",
                  "@@ -0,0 +1,2 @@",
                  "+# NAS市场调研计划",
                  "+正文",
                ].join("\n"),
              },
            ],
          },
        },
      ],
    };

    renderWithProviders(<MessageOutputSummary messages={[message]} />, {
      locale: "zh-CN",
    });

    expect(screen.getByText("已生成 1 个产物")).toBeInTheDocument();
    expect(screen.getByText("新建")).toBeInTheDocument();
    expect(screen.queryByText("已编辑 1 个文件")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "data/workspaces/thread-1/output/final/nas_market_research_plan.md",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("+2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-0").length).toBeGreaterThan(0);
  });

  it("renders audit notice on the diff summary with undo and review owner controls", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
      statusText: "OK",
    });
    vi.stubGlobal("fetch", fetchMock);
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "Done",
      tool_calls: [
        {
          id: "change-1",
          name: "file_change",
          args: {
            changes: [
              {
                path: "data/workspaces/thread-1/output/final/report.md",
                op: "create",
                diff: [
                  "--- /dev/null",
                  "+++ b/data/workspaces/thread-1/output/final/report.md",
                  "@@ -0,0 +1 @@",
                  "+# Report",
                ].join("\n"),
              },
            ],
          },
        },
      ],
    };

    renderWithProviders(
      <MessageOutputSummary
        auditNotice="需要先审核这次产物变更"
        messages={[message]}
        threadId="thread-1"
      />,
      { locale: "zh-CN" },
    );

    expect(
      screen.queryByText("需要先审核这次产物变更"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /撤销/ })).toBeInTheDocument();
    expect(screen.getByLabelText("审核交给")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /撤销/ }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/fs/revert-diff"),
      expect.objectContaining({
        method: "POST",
        body: expect.stringContaining('"thread_id":"thread-1"'),
      }),
    );
  });

  it("scans the turn slice for verifications and the original prompt", () => {
    const { human, verificationAi, verificationResult, finalAnswer } =
      verificationTurnMessages();

    renderWithProviders(
      <MessageOutputSummary
        messages={[finalAnswer]}
        turnMessages={[human, verificationAi, verificationResult, finalAnswer]}
      />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("验证")).toBeInTheDocument();
    expect(screen.getByText("测试通过")).toBeInTheDocument();
    expect(screen.getByText("通过")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /做同款/ }),
    ).toBeInTheDocument();
  });

  it("strips internal <uploaded_files> markup from the make-similar prompt", () => {
    const { human, verificationAi, verificationResult, finalAnswer } =
      verificationTurnMessages();
    window.location.hash = "";

    renderWithProviders(
      <MessageOutputSummary
        messages={[finalAnswer]}
        turnMessages={[human, verificationAi, verificationResult, finalAnswer]}
      />,
      { locale: "zh-CN" },
    );

    fireEvent.click(screen.getByRole("button", { name: /做同款/ }));

    expect(window.location.hash).toContain(
      encodeURIComponent("修复登录页的报错"),
    );
    expect(window.location.hash).not.toContain("uploaded_files");
    expect(window.location.hash).not.toContain("notes.txt");
  });
});

describe("extractResultUrl", () => {
  it("matches Cloudflare Pages deploy URLs on *.pages.dev", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "Deployed to https://myapp.pages.dev/ for preview.",
    };
    expect(extractResultUrl([message])).toBe("https://myapp.pages.dev/");
  });

  it("ignores unrelated hosts", () => {
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "See https://example.com/docs for details.",
    };
    expect(extractResultUrl([message])).toBeNull();
  });
});

describe("MessageList receipt wiring", () => {
  it("renders the verification list and make-similar button through real grouping", () => {
    const { human, verificationAi, verificationResult, finalAnswer } =
      verificationTurnMessages();
    const thread = mockThread({
      messages: [human, verificationAi, verificationResult, finalAnswer],
    });

    renderMessageList(thread);

    expect(screen.getByText("测试通过")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /做同款/ }),
    ).toBeInTheDocument();
  });
});

describe("MessageList failure visibility", () => {
  it("falls back to the error banner when the failed turn ends in a processing group", () => {
    const messages: Message[] = [
      { id: "user-1", type: "human", content: "first request" },
      { id: "assistant-1", type: "ai", content: "Earlier assistant answer." },
      { id: "user-2", type: "human", content: "second request" },
      {
        id: "assistant-2",
        type: "ai",
        content: "",
        tool_calls: [{ id: "tc-1", name: "web_search", args: { query: "q" } }],
      } as AIMessage,
    ];
    const thread = mockThread({
      messages,
      error: new Error("beak step 3 failed"),
    });

    renderMessageList(thread, "en-US");

    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("beak step 3 failed");
  });

  it("mounts audit actions on the final assistant group when changes live in the processing group", () => {
    const human: Message = {
      id: "user-1",
      type: "human",
      content: "改一下配置",
    };
    // file_change lives on the tool-call message, which grouping puts into
    // the processing group — the plain assistant group only carries the
    // final answer text.
    const changeAi: AIMessage = {
      id: "ai-tools",
      type: "ai",
      content: "",
      tool_calls: [
        {
          id: "change-1",
          name: "file_change",
          args: {
            changes: [
              {
                path: "src/config.ts",
                op: "update",
                diff: [
                  "--- a/src/config.ts",
                  "+++ b/src/config.ts",
                  "@@",
                  "-old",
                  "+new",
                ].join("\n"),
              },
            ],
          },
        },
      ],
    };
    const changeResult: ToolMessage = {
      id: "tool-change-1",
      type: "tool",
      content: "ok",
      tool_call_id: "change-1",
    };
    const finalAnswer: Message = {
      id: "ai-final",
      type: "ai",
      content: "配置已经改好了，请审核。",
    };
    const thread = mockThread({
      messages: [human, changeAi, changeResult, finalAnswer],
      error: new Error(
        "Code changes were produced without a verification step",
      ),
    });

    renderMessageList(thread);

    expect(screen.getByRole("button", { name: /撤销/ })).toBeInTheDocument();
    expect(screen.getByLabelText("审核交给")).toBeInTheDocument();
    // The receipt owns the failure display; the fallback banner stays off.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the raw text when thread.error is a plain string", () => {
    const messages: Message[] = [
      { id: "user-1", type: "human", content: "first request" },
      { id: "assistant-1", type: "ai", content: "Earlier assistant answer." },
      { id: "user-2", type: "human", content: "second request" },
      {
        id: "assistant-2",
        type: "ai",
        content: "",
        tool_calls: [{ id: "tc-1", name: "web_search", args: { query: "q" } }],
      } as AIMessage,
    ];
    const thread = mockThread({
      messages,
      error: "boom exploded" as unknown as Error,
    });

    renderMessageList(thread, "en-US");

    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("boom exploded");
    expect(banner).not.toHaveTextContent(/This reply was interrupted/i);
  });
});
