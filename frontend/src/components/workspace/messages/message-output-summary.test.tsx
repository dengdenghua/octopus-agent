import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AIMessage } from "@/core/api/types";
import { renderWithProviders } from "@/test/harness";

import { MessageOutputSummary } from "./message-output-summary";

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
});
