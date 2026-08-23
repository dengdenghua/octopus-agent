import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";

import { renderWithProviders } from "@/test/harness";

import { ChatBox } from "./chat-box";

const mocks = vi.hoisted(() => ({
  deselect: vi.fn(),
  selectArtifact: vi.fn(),
  setArtifacts: vi.fn(),
  setArtifactsOpen: vi.fn(),
}));

vi.mock("@/core/artifacts/use-workspace-artifacts", () => ({
  useWorkspaceArtifacts: () => ({ data: ["workspace/report.md"] }),
}));

vi.mock("../artifacts", () => ({
  ArtifactPanel: () => <div>artifact drawer</div>,
  useArtifacts: () => ({
    artifacts: ["workspace/report.md"],
    open: false,
    autoOpen: true,
    selectedArtifact: null,
    setOpen: mocks.setArtifactsOpen,
    setArtifacts: mocks.setArtifacts,
    select: mocks.selectArtifact,
    deselect: mocks.deselect,
  }),
}));

vi.mock("../messages/context", () => ({
  useThread: () => ({
    thread: {
      isLoading: false,
      values: { artifacts: [] },
    },
  }),
}));

describe("ChatBox artifact panel ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not auto-open legacy artifact state in external mode", async () => {
    renderWithProviders(
      <ChatBox artifactPanelMode="external" threadId="thread-1">
        <div>conversation</div>
      </ChatBox>,
    );

    expect(screen.getByText("conversation")).toBeInTheDocument();
    await waitFor(() => expect(mocks.setArtifacts).toHaveBeenCalled());
    expect(mocks.setArtifactsOpen).not.toHaveBeenCalled();
    expect(screen.queryByText("artifact drawer")).not.toBeInTheDocument();
  });

  it("preserves auto-open behavior for the default drawer owner", async () => {
    renderWithProviders(
      <ChatBox threadId="thread-1">
        <div>conversation</div>
      </ChatBox>,
    );

    await waitFor(() =>
      expect(mocks.setArtifactsOpen).toHaveBeenCalledWith(true),
    );
    expect(screen.getByText("artifact drawer")).toBeInTheDocument();
  });
});
