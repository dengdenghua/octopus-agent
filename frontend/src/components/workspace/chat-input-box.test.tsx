import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";
import { queueComposerImageEntry } from "@/core/composer-image-inbox";

import { ChatInputBox } from "./chat-input-box";

const uploadFilesMock = vi.fn();

vi.mock("@/core/uploads", () => ({
  uploadFiles: (...args: unknown[]) => uploadFilesMock(...args),
}));

vi.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [{ id: "test-model", display_name: "Test Model" }],
  }),
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    isLoading: false,
    authStatus: { enabled: false, allow_registration: false },
    user: null,
    isAuthenticated: false,
    isGuest: true,
    login: vi.fn(),
    smsLogin: vi.fn(),
    guestLogin: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.mock("./evolution-indicator", () => ({
  EvolutionIndicator: () => null,
}));

vi.mock("./file-activity-indicator", () => ({
  FileActivityIndicator: () => null,
}));

vi.mock("./preview-refresh-indicator", () => ({
  PreviewRefreshIndicator: () => null,
}));

function textarea(): HTMLTextAreaElement {
  const el = document.querySelector("textarea");
  if (!el) throw new Error("textarea not found");
  return el as HTMLTextAreaElement;
}

async function openAgentSettings() {
  const trigger = screen.getByLabelText("Tools");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByText("Research settings"));
}

async function openToolsMenu() {
  const trigger = screen.getByLabelText("Tools");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
  return screen.findByRole("menu");
}

describe("<ChatInputBox /> cowork materials", () => {
  it("keeps prompt-only shortcuts out of the quick tools menu", async () => {
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={vi.fn()}
      />,
    );

    await openToolsMenu();

    expect(screen.getByText("Research settings")).toBeInTheDocument();
    expect(screen.getByText("Plan")).toBeInTheDocument();
    expect(screen.getByText("Spec")).toBeInTheDocument();
    expect(screen.getByText("Goal")).toBeInTheDocument();
    expect(screen.getByText("Add material")).toBeInTheDocument();
    expect(
      screen.getByText("Add image (paste / drag / select)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Default")).not.toBeInTheDocument();
    expect(screen.queryByText("Web search")).not.toBeInTheDocument();
    expect(screen.queryByText("Create PPT")).not.toBeInTheDocument();
    expect(screen.queryByText("Create page")).not.toBeInTheDocument();
    expect(screen.queryByText("Format table")).not.toBeInTheDocument();
    expect(screen.queryByText("Generate image")).not.toBeInTheDocument();
    expect(screen.queryByText("Scheduled Task")).not.toBeInTheDocument();
    expect(screen.queryByText("Project Files")).not.toBeInTheDocument();
    expect(screen.queryByText("Research context")).not.toBeInTheDocument();
    expect(screen.queryByText("Web Search Research")).not.toBeInTheDocument();
  });

  it("inserts Codex mode markers into the draft without switching mode", async () => {
    const onModeChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        allowAgentModes
        onModeChange={onModeChange}
        onDeepResearch={vi.fn()}
      />,
    );

    await openToolsMenu();
    fireEvent.click(screen.getByText("Plan"));

    expect(textarea().value).toBe("/codex plan\n");
    expect(onModeChange).not.toHaveBeenCalled();

    fireEvent.change(textarea(), {
      target: { value: "/codex plan\nAudit this repo" },
    });
    await openToolsMenu();
    fireEvent.click(screen.getByText("Goal"));

    expect(textarea().value).toBe("/codex goal\nAudit this repo");
    expect(onModeChange).not.toHaveBeenCalled();
  });

  it("keeps marker-only Codex drafts unsent until the task is written", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={onSubmit}
        onDeepResearch={vi.fn()}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "/codex plan\n" } });

    expect(screen.getByTitle("Send")).toBeDisabled();
    fireEvent.click(screen.getByTitle("Send"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea().value).toBe("/codex plan\n");
  });

  it("sends default execution mode through the normal message path", async () => {
    const onSubmit = vi.fn();
    const onDeepResearch = vi.fn().mockResolvedValue(true);
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={onSubmit}
        onDeepResearch={onDeepResearch}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "Run the agent" } });
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({ text: "Run the agent" }),
    );
    expect(onDeepResearch).not.toHaveBeenCalled();
  });

  it("sends vague tasks through so the model can decide whether to clarify", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );

    fireEvent.change(textarea(), {
      target: { value: "Research a promising niche market" },
    });
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: "Research a promising niche market",
      }),
    );
    expect(textarea().value).toBe("");
  });

  it("allows sending a pasted image without typed text", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );

    const image = new File(["img"], "screen.png", { type: "image/png" });
    fireEvent.paste(textarea(), {
      clipboardData: {
        items: [
          {
            kind: "file",
            type: "image/png",
            getAsFile: () => image,
          },
        ],
      },
    });

    expect(screen.getByTitle("Send")).toBeEnabled();
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: "",
        images: [image],
      }),
    );
  });

  it("treats legacy deep Agent state as a normal message until research settings open", async () => {
    const onSubmit = vi.fn();
    const onDeepResearch = vi.fn().mockResolvedValue(true);
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        onSubmit={onSubmit}
        onDeepResearch={onDeepResearch}
      />,
    );

    fireEvent.change(textarea(), {
      target: { value: "Continue in agent mode" },
    });
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: "Continue in agent mode",
      }),
    );
    expect(onDeepResearch).not.toHaveBeenCalled();
  });

  it("prefills the composer and switches to cowork from a thinking plan event", async () => {
    const onModeChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        allowAgentModes
        onModeChange={onModeChange}
        onDeepResearch={vi.fn()}
      />,
    );

    window.dispatchEvent(
      new CustomEvent("octopus:start-deep-research", {
        detail: { threadId: "other-thread", topic: "wrong topic" },
      }),
    );
    expect(textarea().value).toBe("");

    await act(async () => {
      window.dispatchEvent(
        new CustomEvent("octopus:start-deep-research", {
          detail: { threadId: "thread-1", topic: "NAS market research" },
        }),
      );
    });

    await waitFor(() => {
      expect(textarea().value).toBe("NAS market research");
    });
    expect(onModeChange).toHaveBeenCalledWith("deep");
  });

  it("can expose Inspiration as a right-side toggle without an Agent menu", async () => {
    const onModeChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onModeChange={onModeChange}
        showInspirationToggle
        onDeepResearch={vi.fn()}
      />,
    );

    window.dispatchEvent(
      new CustomEvent("octopus:start-deep-research", {
        detail: { threadId: "thread-1", topic: "NAS market research" },
      }),
    );

    await waitFor(() => {
      expect(textarea().value).toBe("NAS market research");
    });
    expect(onModeChange).not.toHaveBeenCalled();

    expect(screen.queryByText("Swarm")).toBeNull();
    expect(screen.queryByText("Add Research Material")).toBeNull();
    expect(screen.queryByTestId("reasoning-mode-trigger")).toBeNull();

    const inspiration = screen.getByRole("button", {
      name: "Discuss ideas without running tools",
    });
    expect(inspiration).toHaveAttribute("aria-pressed", "false");
    expect(inspiration).toHaveAttribute(
      "title",
      "Discuss ideas without running tools",
    );
    expect(inspiration).not.toHaveTextContent("Inspiration");

    fireEvent.click(inspiration);

    expect(onModeChange).toHaveBeenCalledWith("chat", "NAS market research");
  });

  it("marks the Inspiration toggle active in discussion-only mode", () => {
    renderWithProviders(
      <ChatInputBox
        mode="chat"
        threadId="thread-1"
        showInspirationToggle
        onModeChange={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", {
        name: "Discuss ideas without running tools",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("lets users select the reasoning effort", async () => {
    const onReasoningEffortChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        reasoningEffort="medium"
        onReasoningEffortChange={onReasoningEffortChange}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Select Model" });
    fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
    fireEvent.click(trigger);
    expect(
      await screen.findByRole("radiogroup", { name: "Reasoning effort" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Ultra" }));

    expect(onReasoningEffortChange).toHaveBeenCalledWith("xhigh");
  });

  it("shows the context compressor as a persistent input control", () => {
    const { rerender } = renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        contextTokens={500}
        maxContextTokens={1000}
      />,
    );

    expect(screen.getByLabelText(/Context Usage: 50%/)).toBeInTheDocument();

    rerender(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        contextTokens={600}
        maxContextTokens={1000}
      />,
    );

    expect(screen.getByLabelText(/Context Usage: 60%/)).toBeInTheDocument();
  });

  it("submits only enabled URL/text materials", async () => {
    const onDeepResearch = vi.fn().mockResolvedValue(true);
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={onDeepResearch}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "Research NAS market" } });
    await openAgentSettings();
    fireEvent.change(
      screen.getByPlaceholderText("https://example.com, https://..."),
      {
        target: { value: "https://www.synology.com/" },
      },
    );
    fireEvent.change(screen.getByPlaceholderText("Material Note"), {
      target: { value: "official site" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^URL$/i }));

    fireEvent.change(screen.getByPlaceholderText("Text Title"), {
      target: { value: "Internal notes" },
    });
    fireEvent.change(screen.getByPlaceholderText("Paste text material"), {
      target: { value: "Users care about backup." },
    });
    fireEvent.click(screen.getByRole("button", { name: /^Text$/i }));

    fireEvent.click(screen.getAllByTitle("Toggle Material")[0]);
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() => expect(onDeepResearch).toHaveBeenCalledTimes(1));
    const [, options] = onDeepResearch.mock.calls[0];
    expect(options.materials).toEqual([
      expect.objectContaining({
        kind: "text",
        title: "Internal notes",
        text: "Users care about backup.",
      }),
    ]);
  });

  it("uploads files and submits them as file materials", async () => {
    uploadFilesMock.mockResolvedValue({
      success: true,
      message: "ok",
      files: [
        {
          filename: "brief.md",
          path: "F:/uploads/thread-1/brief.md",
          virtual_path: "/uploads/brief.md",
          artifact_url: "/api/artifacts/brief.md",
          size: 123,
          modified: 1,
          extension: ".md",
        },
      ],
    });
    const onDeepResearch = vi.fn().mockResolvedValue(true);
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={onDeepResearch}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "Research NAS market" } });
    await openAgentSettings();
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["hello"], "brief.md", { type: "text/markdown" })],
      },
    });

    await screen.findByText("brief.md");
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() => expect(onDeepResearch).toHaveBeenCalledTimes(1));
    const [, options] = onDeepResearch.mock.calls[0];
    expect(uploadFilesMock).toHaveBeenCalledWith("thread-1", [
      expect.objectContaining({ name: "brief.md" }),
    ]);
    expect(options.materials).toEqual([
      expect.objectContaining({
        kind: "file",
        title: "brief.md",
        path: "F:/uploads/thread-1/brief.md",
      }),
    ]);
  });

  it("lets the planner choose research roles instead of sending a fixed template", async () => {
    const onDeepResearch = vi.fn().mockResolvedValue(true);
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={onDeepResearch}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "Research NAS market" } });
    await openAgentSettings();
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() => expect(onDeepResearch).toHaveBeenCalledTimes(1));
    const [, options] = onDeepResearch.mock.calls[0];
    expect(options.roles).toBeUndefined();
    expect(options.maxSubagents).toBeUndefined();
  });
});

describe("<ChatInputBox /> send-failure draft restore", () => {
  function dispatchSendFailed(detail: {
    threadId?: string | null;
    text?: string | null;
    images?: File[] | null;
    sourceLabel?: string | null;
  }) {
    act(() => {
      window.dispatchEvent(new CustomEvent("octopus:send-failed", { detail }));
    });
  }

  it("restores the draft when a send fails after optimistic clear", async () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "hello agent" } });
    fireEvent.click(screen.getByTitle("Send"));
    await waitFor(() => expect(textarea().value).toBe(""));

    dispatchSendFailed({ threadId: "thread-1", text: "hello agent" });

    await waitFor(() => expect(textarea().value).toBe("hello agent"));
  });

  it("ignores failures from other threads", () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    dispatchSendFailed({ threadId: "thread-other", text: "not mine" });

    expect(textarea().value).toBe("");
  });

  it("does not clobber text the user already retyped", () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    fireEvent.change(textarea(), { target: { value: "new attempt" } });
    dispatchSendFailed({ threadId: "thread-1", text: "old failed text" });

    expect(textarea().value).toBe("new attempt");
  });

  it("restores failed screenshots when the composer had been cleared", async () => {
    const image = new File(["img"], "failed-shot.png", { type: "image/png" });
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    dispatchSendFailed({
      threadId: "thread-1",
      images: [image],
      sourceLabel: "浏览器截图",
    });

    await waitFor(() =>
      expect(
        document.querySelector('img[alt="failed-shot.png"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByTitle("Send")).toBeEnabled();
    expect(screen.getByText("浏览器截图")).toBeInTheDocument();
  });

  it("accepts externally injected browser screenshots for the active thread", async () => {
    const image = new File(["img"], "browser-shot.png", { type: "image/png" });
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent("octopus:inject-composer-images", {
          detail: {
            threadId: "thread-1",
            images: [image],
            sourceLabel: "浏览器截图",
          },
        }),
      );
    });

    await waitFor(() =>
      expect(
        document.querySelector('img[alt="browser-shot.png"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("浏览器截图")).toBeInTheDocument();
  });

  it("hydrates queued browser screenshots when the composer mounts", async () => {
    const pngDataUrl =
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnR5WQAAAAASUVORK5CYII=";
    queueComposerImageEntry({
      dataUrl: pngDataUrl,
      filename: "queued-browser-shot.png",
      sourceLabel: "浏览器截图",
    });

    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    await waitFor(() =>
      expect(
        document.querySelector('img[alt="queued-browser-shot.png"]'),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("浏览器截图")).toBeInTheDocument();
  });
});
