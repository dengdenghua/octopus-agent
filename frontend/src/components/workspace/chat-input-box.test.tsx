import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";
import { queueComposerImageEntry } from "@/core/composer-image-inbox";

import type * as UploadsApiModule from "@/core/uploads/api";

import { ChatInputBox } from "./chat-input-box";
import type { GroupTaskStrategy } from "./group-task-strategy";

const uploadFilesMock = vi.fn();
const uploadWithProgressMock = vi.fn();
const modelCatalog = vi.hoisted(() => ({
  current: [] as Array<Record<string, unknown>>,
}));

// Only the transport is stubbed — ``useAttachmentUploads`` runs for real so the
// progress/gating tests exercise the actual state machine. The hook imports
// from ``./api`` directly, so that module is what has to be mocked; the barrel
// re-exports it.
vi.mock("@/core/uploads/api", async (importOriginal) => {
  const actual = await importOriginal<UploadsApiModule>();
  return {
    ...actual,
    uploadFiles: (...args: unknown[]) => uploadFilesMock(...args),
    uploadFilesWithProgress: (...args: unknown[]) =>
      uploadWithProgressMock(...args),
  };
});

vi.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: modelCatalog.current,
  }),
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    isLoading: false,
    authStatus: { enabled: false, allow_registration: false },
    user: null,
    isAuthenticated: false,
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
  const trigger = screen.getByLabelText("Insert into input");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByText("Research settings"));
}

async function openToolsMenu() {
  const trigger = screen.getByTestId("chat-tools-trigger");
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.click(trigger);
  return screen.findByRole("menu");
}

function uploadedInfo(file: File) {
  return {
    filename: file.name,
    size: file.size,
    path: `/artifacts/${file.name}`,
    virtual_path: `uploads/${file.name}`,
    artifact_url: `https://example.test/${file.name}`,
    content_type: file.type,
  };
}

beforeEach(() => {
  modelCatalog.current = [
    {
      id: "test-model",
      name: "test-model",
      model: "test-model",
      display_name: "Test Model",
    },
  ];
  uploadFilesMock.mockReset();
  uploadWithProgressMock.mockReset();
  // Attaching now uploads immediately, so every test needs a transport.
  // The default resolves at once; progress-specific tests override it.
  uploadWithProgressMock.mockImplementation(
    async (
      _threadId: string,
      files: File[],
      options?: { onProgress?: (p: number) => void },
    ) => {
      options?.onProgress?.(100);
      return { files: files.map(uploadedInfo) };
    },
  );
});

describe("<ChatInputBox /> cowork materials", () => {
  it("replaces Inspiration with the response strategy in collaboration", () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-response-mode"
        showInspirationToggle
        responseModeControl={
          <div data-testid="response-mode-control">Conversation type</div>
        }
      />,
    );

    const control = screen.getByTestId("response-mode-control");
    expect(control.closest(".composer-footer")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-mode-toggle")).toBeNull();
    expect(screen.getByTestId("chat-send-button")).toBeInTheDocument();
  });

  it("moves group task strategy into the + menu and keeps the active choice visible", async () => {
    const onStrategyChange = vi.fn();
    const onSubmit = vi.fn();

    function ControlledGroupComposer() {
      const [strategy, setStrategy] = useState<GroupTaskStrategy>("auto");
      return (
        <ChatInputBox
          mode="react"
          threadId="thread-group-strategy"
          isGroupConversation
          groupTaskStrategy={strategy}
          onGroupTaskStrategyChange={(next) => {
            onStrategyChange(next);
            setStrategy(next);
          }}
          onSubmit={onSubmit}
        />
      );
    }

    renderWithProviders(<ControlledGroupComposer />);

    expect(
      screen.getByRole("button", { name: "Start a task or add content" }),
    ).toBeInTheDocument();
    const menu = await openToolsMenu();
    const research = within(menu).getByTestId("group-task-strategy-research");
    expect(
      within(menu).getByTestId("group-task-strategy-auto"),
    ).toHaveAttribute("aria-checked", "true");

    fireEvent.click(research);

    expect(onStrategyChange).toHaveBeenLastCalledWith("research");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByTestId("group-task-strategy-chip")).toHaveTextContent(
      "Task · Deep research",
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Return to automatic handling" }),
    );

    expect(onStrategyChange).toHaveBeenLastCalledWith("auto");
    expect(screen.queryByTestId("group-task-strategy-chip")).toBeNull();
  });

  it("offers create-deliverable without a folder and develop with a folder", async () => {
    const first = renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-group-personal"
        isGroupConversation
        groupTaskStrategy="auto"
        onGroupTaskStrategyChange={vi.fn()}
      />,
    );

    let menu = await openToolsMenu();
    expect(within(menu).getByText("Create deliverable")).toBeInTheDocument();
    expect(within(menu).queryByText("Develop")).toBeNull();
    first.unmount();

    renderWithProviders(
      <ChatInputBox
        mode="code"
        threadId="thread-group-project"
        workDir="/workspace/project"
        isGroupConversation
        groupTaskStrategy="auto"
        onGroupTaskStrategyChange={vi.fn()}
      />,
    );

    menu = await openToolsMenu();
    expect(within(menu).getByText("Develop")).toBeInTheDocument();
    expect(within(menu).queryByText("Create deliverable")).toBeNull();
  });

  it("hides personal/project status and default permission chrome in groups", () => {
    const group = renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-group-clean-footer"
        isGroupConversation
        showWorkDirSelector
        permissionMode="default"
      />,
    );

    expect(screen.queryByTestId("chat-status-strip")).toBeNull();
    expect(screen.queryByTestId("permission-mode-trigger")).toBeNull();
    group.unmount();

    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-group-risk-warning"
        isGroupConversation
        permissionMode="bypassPermissions"
      />,
    );

    expect(screen.getByTestId("permission-mode-trigger")).toHaveAccessibleName(
      "Permissions: Full access",
    );
  });

  it("keeps the existing private composer controls unchanged", async () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-private-controls"
        showWorkDirSelector
        permissionMode="default"
      />,
    );

    expect(screen.getByTestId("chat-status-strip")).toBeInTheDocument();
    expect(screen.getByTestId("permission-mode-trigger")).toHaveAccessibleName(
      "Permissions: Default",
    );
    expect(
      screen.getByRole("button", { name: "Insert into input" }),
    ).toBeInTheDocument();

    const menu = await openToolsMenu();
    expect(within(menu).queryByText("Start a task")).toBeNull();
    expect(within(menu).queryByTestId("group-task-strategy-auto")).toBeNull();
  });

  it("returns the selected row id when two endpoints share one wire model", async () => {
    modelCatalog.current = [
      {
        id: "deepseek-v4-flash",
        name: "deepseek-v4-flash",
        model: "deepseek-v4-flash",
        display_name: "DeepSeek primary",
        entry_id: "deepseek-primary",
        selection_id: "selection-deepseek-primary-default",
        reasoning_efforts: ["off", "high"],
        context_window: 256_000,
        context_profile: "default",
        supports_thinking: true,
        supports_vision: false,
        supports_tool_use: true,
      },
      {
        id: "deepseek-v4-flash",
        name: "deepseek-v4-flash",
        model: "deepseek-v4-flash",
        display_name: "DeepSeek backup",
        entry_id: "deepseek-backup",
        selection_id: "selection-deepseek-backup-default",
        reasoning_efforts: ["off", "high", "xhigh"],
        context_window: 128_000,
        context_profile: "default",
        supports_thinking: true,
        supports_vision: true,
        supports_tool_use: false,
      },
    ];
    const user = userEvent.setup();
    const onModelChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-duplicate-models"
        modelName="selection-deepseek-primary-default"
        onModelChange={onModelChange}
      />,
    );

    await user.click(screen.getByTestId("model-picker-trigger"));
    const menu = await screen.findByTestId("model-picker-menu");
    await user.click(
      within(menu).getByText("DeepSeek backup").closest("button")!,
    );

    expect(onModelChange).toHaveBeenCalledWith(
      "selection-deepseek-backup-default",
    );
  });

  it("gives the composer a persistent accessible name", () => {
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-accessible-name"
        onSubmit={vi.fn()}
        onDeepResearch={vi.fn()}
      />,
    );

    expect(screen.getByTestId("chat-composer-input")).toHaveAttribute(
      "aria-label",
      "How can I assist you today?",
    );
  });

  it("keeps prompt-only shortcuts out of the quick tools menu", async () => {
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={vi.fn()}
      />,
    );

    // Scope the negative assertions to the menu: the composer status strip
    // always renders a permission-mode label ("Default"), so a document-wide
    // queryByText would fail on chrome that has nothing to do with the menu.
    const menu = await openToolsMenu();
    const inMenu = within(menu);

    expect(screen.getByText("Research settings")).toBeInTheDocument();
    expect(screen.getByText("Insert Plan marker")).toBeInTheDocument();
    expect(screen.getByText("Insert Spec marker")).toBeInTheDocument();
    expect(screen.getByText("Insert Goal marker")).toBeInTheDocument();
    expect(screen.getByText("Insert Browser marker")).toBeInTheDocument();
    expect(screen.getByText("Insert Chrome marker")).toBeInTheDocument();
    expect(screen.getByText("Add material")).toBeInTheDocument();
    expect(
      screen.getByText("Add image (paste / drag / select)"),
    ).toBeInTheDocument();
    expect(inMenu.queryByText("Default")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Web search")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Create PPT")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Create page")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Format table")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Generate image")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Scheduled Task")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Project Files")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Research context")).not.toBeInTheDocument();
    expect(inMenu.queryByText("Web Search Research")).not.toBeInTheDocument();
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
    fireEvent.click(screen.getByText("Insert Plan marker"));

    expect(textarea().value).toBe("/mode plan\n");
    expect(onModeChange).not.toHaveBeenCalled();

    fireEvent.change(textarea(), {
      target: { value: "/mode plan\nAudit this repo" },
    });
    await openToolsMenu();
    fireEvent.click(screen.getByText("Insert Spec marker"));

    expect(textarea().value).toBe("/mode spec\nAudit this repo");
    expect(onModeChange).not.toHaveBeenCalled();

    await openToolsMenu();
    fireEvent.click(screen.getByText("Insert Goal marker"));

    expect(textarea().value).toBe("/mode goal\nAudit this repo");
    expect(onModeChange).not.toHaveBeenCalled();
  });

  it("inserts Browser surface marker into the draft without switching mode", async () => {
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
    fireEvent.click(screen.getByText("Insert Browser marker"));

    expect(textarea().value).toBe("@Browser\n");
    expect(onModeChange).not.toHaveBeenCalled();

    fireEvent.change(textarea(), {
      target: { value: "@Browser\nOpen the current page" },
    });
    await openToolsMenu();
    fireEvent.click(screen.getByText("Insert Browser marker"));

    expect(textarea().value).toBe("@Browser\nOpen the current page");
    expect(onModeChange).not.toHaveBeenCalled();
  });

  it("inserts Chrome surface marker into the draft without switching mode", async () => {
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
    fireEvent.click(screen.getByText("Insert Chrome marker"));

    expect(textarea().value).toBe("@Chrome\n");
    expect(onModeChange).not.toHaveBeenCalled();

    fireEvent.change(textarea(), {
      target: { value: "@Browser\nOpen the signed-in page" },
    });
    await openToolsMenu();
    fireEvent.click(screen.getByText("Insert Chrome marker"));

    expect(textarea().value).toBe("@Chrome\nOpen the signed-in page");
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

    fireEvent.change(textarea(), { target: { value: "/mode plan\n" } });

    expect(screen.getByTitle("Send")).toBeDisabled();
    fireEvent.click(screen.getByTitle("Send"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(textarea().value).toBe("/mode plan\n");
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

  it("suppresses duplicate submissions before the parent status updates", () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );

    fireEvent.change(textarea(), { target: { value: "Run once" } });
    const send = screen.getByTitle("Send");
    fireEvent.click(send);
    fireEvent.click(send);

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("preserves partner /model commands for the CLI adapter", () => {
    const onSubmit = vi.fn();
    const onModelChange = vi.fn();
    const onPartnerModelChange = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        partnerId="trae-cli"
        onSubmit={onSubmit}
        onModelChange={onModelChange}
        onPartnerModelChange={onPartnerModelChange}
      />,
    );

    fireEvent.change(textarea(), {
      target: { value: "/model doubao-seed\nInspect this repository" },
    });
    fireEvent.click(screen.getByTitle("Send"));

    expect(onSubmit).toHaveBeenCalledWith({
      text: "/model doubao-seed\nInspect this repository",
      images: undefined,
      files: undefined,
    });
    expect(onModelChange).not.toHaveBeenCalled();
    expect(onPartnerModelChange).not.toHaveBeenCalled();
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

    // Send stays blocked until the attachment finishes uploading.
    await waitFor(() => expect(screen.getByTitle("Send")).toBeEnabled());
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: "",
        images: [image],
        uploaded: [uploadedInfo(image)],
      }),
    );
  });

  it("adds clicked workspace files to the composer and sends them as turn context", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-1"
        workDir="/repo/octopus"
        onSubmit={onSubmit}
      />,
    );

    act(() => {
      window.dispatchEvent(
        new CustomEvent("octopus:open-file", {
          detail: {
            threadId: "thread-1",
            path: "src/app.tsx",
            workDir: "/repo/octopus",
          },
        }),
      );
    });

    expect(await screen.findByText("app.tsx")).toBeInTheDocument();
    expect(screen.getByTitle("Send")).toBeEnabled();
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: expect.stringContaining(
          "path=src/app.tsx workspace=/repo/octopus",
        ),
      }),
    );
  });

  it("sends selected local files through the normal attachment path", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );

    const file = new File(["brief"], "brief.md", { type: "text/markdown" });
    const inputs = document.querySelectorAll('input[type="file"]');
    const contextInput = inputs[inputs.length - 1] as HTMLInputElement;
    fireEvent.change(contextInput, {
      target: { files: [file] },
    });

    expect(await screen.findByText("brief.md")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTitle("Send")).toBeEnabled());
    fireEvent.click(screen.getByTitle("Send"));

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith({
        text: expect.stringContaining("upload=brief.md"),
        files: [file],
        uploaded: [uploadedInfo(file)],
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
    // Sending clears the optimistic draft asynchronously. Wait for that
    // contract before unmounting so the following test cannot observe a late
    // state write when the full suite is under load.
    await waitFor(() => expect(textarea().value).toBe(""));
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

  it("does not expose raw upload errors in the composer", async () => {
    uploadFilesMock.mockRejectedValueOnce(
      new Error("S3 credential token leaked from upstream"),
    );
    renderWithProviders(
      <ChatInputBox
        mode="deep"
        threadId="thread-1"
        allowAgentModes
        onDeepResearch={vi.fn()}
      />,
    );

    await openAgentSettings();
    const fileInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement;
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["hello"], "brief.md", { type: "text/markdown" })],
      },
    });

    expect(await screen.findByText("Upload failed")).toBeInTheDocument();
    expect(
      screen.queryByText("S3 credential token leaked from upstream"),
    ).not.toBeInTheDocument();
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

describe("<ChatInputBox /> live steering", () => {
  it("keeps text input sendable while a turn is streaming", () => {
    const onSubmit = vi.fn();
    const onStop = vi.fn();
    renderWithProviders(
      <ChatInputBox
        mode="react"
        threadId="thread-live"
        status="streaming"
        onSubmit={onSubmit}
        onStop={onStop}
      />,
    );

    const input = screen.getByTestId("chat-composer-input");
    expect(input).not.toBeDisabled();
    fireEvent.change(input, { target: { value: "先暂停修改，核对根因" } });
    fireEvent.click(screen.getByTestId("chat-steer-button"));

    expect(onSubmit).toHaveBeenCalledWith({
      text: "先暂停修改，核对根因",
      images: undefined,
      files: undefined,
    });
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

// ── upload on attach · the chip is the upload, not a promise of one ─
//
// Attachments used to upload inside the send handler. Nothing was in flight
// while the chip sat in the composer, so a progress bar was impossible and the
// only completion signal was a toast that appeared, detached, after send.
describe("<ChatInputBox /> upload on attach", () => {
  /** aria-label is stable; the title explains *why* send is blocked. */
  const sendButton = () => screen.getByLabelText("Send");

  function pasteImage(name = "shot.png") {
    const image = new File(["img"], name, { type: "image/png" });
    fireEvent.paste(textarea(), {
      clipboardData: {
        items: [{ kind: "file", type: "image/png", getAsFile: () => image }],
      },
    });
    return image;
  }

  /** A transport whose completion and progress the test drives by hand. */
  function deferredTransport() {
    let resolve!: (value: { files: ReturnType<typeof uploadedInfo>[] }) => void;
    let reject!: (err: Error) => void;
    let emit: ((percent: number) => void) | undefined;
    uploadWithProgressMock.mockImplementation(
      (
        _threadId: string,
        _files: File[],
        options?: { onProgress?: (p: number) => void },
      ) => {
        emit = options?.onProgress;
        return new Promise((res, rej) => {
          resolve = res;
          reject = rej;
        });
      },
    );
    return {
      progress: (percent: number) => act(() => emit?.(percent)),
      finish: (files: File[]) =>
        act(async () => resolve({ files: files.map(uploadedInfo) })),
      fail: async (message: string) => {
        await act(async () => {
          reject(new Error(message));
        });
      },
    };
  }

  it("starts uploading as soon as an image is attached", async () => {
    renderWithProviders(<ChatInputBox mode="react" threadId="thread-1" />);
    const image = pasteImage();

    await waitFor(() =>
      expect(uploadWithProgressMock).toHaveBeenCalledTimes(1),
    );
    expect(uploadWithProgressMock.mock.calls[0][0]).toBe("thread-1");
    expect(uploadWithProgressMock.mock.calls[0][1]).toEqual([image]);
  });

  it("shows byte progress on the chip while the upload runs", async () => {
    const transport = deferredTransport();
    renderWithProviders(<ChatInputBox mode="react" threadId="thread-1" />);
    pasteImage();

    await waitFor(() => expect(uploadWithProgressMock).toHaveBeenCalled());
    transport.progress(42);

    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "42");
    expect(bar).toHaveAttribute("data-upload-status", "uploading");
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("blocks send until the progress bar completes", async () => {
    const transport = deferredTransport();
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );
    const image = pasteImage();

    await waitFor(() => expect(uploadWithProgressMock).toHaveBeenCalled());
    transport.progress(70);
    expect(sendButton()).toBeDisabled();
    // A disabled button that says nothing looks broken.
    expect(sendButton()).toHaveAttribute(
      "title",
      "Waiting for attachments to finish uploading",
    );
    fireEvent.click(sendButton());
    expect(onSubmit).not.toHaveBeenCalled();

    await transport.finish([image]);
    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("carries the server-side upload info into the sent message", async () => {
    const onSubmit = vi.fn();
    renderWithProviders(
      <ChatInputBox mode="react" threadId="thread-1" onSubmit={onSubmit} />,
    );
    const image = pasteImage("into-chat.png");

    await waitFor(() => expect(sendButton()).toBeEnabled());
    fireEvent.click(sendButton());

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          images: [image],
          uploaded: [uploadedInfo(image)],
        }),
      ),
    );
  });

  it("marks a failed attachment and keeps send blocked", async () => {
    const transport = deferredTransport();
    renderWithProviders(<ChatInputBox mode="react" threadId="thread-1" />);
    const image = pasteImage("broken.png");

    await waitFor(() => expect(uploadWithProgressMock).toHaveBeenCalled());
    await transport.fail("disk full");

    const bar = await screen.findByRole("progressbar");
    expect(bar).toHaveAttribute("data-upload-status", "error");
    expect(sendButton()).toBeDisabled();
    expect(screen.getByLabelText("Retry upload")).toBeInTheDocument();
    expect(bar).toHaveAttribute("aria-label", "Upload failed");
    expect(image.name).toBe("broken.png");
  });

  it("retries a failed upload from the chip", async () => {
    const transport = deferredTransport();
    renderWithProviders(<ChatInputBox mode="react" threadId="thread-1" />);
    const image = pasteImage("retry-me.png");

    await waitFor(() => expect(uploadWithProgressMock).toHaveBeenCalled());
    await transport.fail("network down");
    const retry = await screen.findByLabelText("Retry upload");
    expect(image.name).toBe("retry-me.png");

    uploadWithProgressMock.mockResolvedValue({ files: [uploadedInfo(image)] });
    fireEvent.click(retry);

    await waitFor(() => expect(sendButton()).toBeEnabled());
    expect(uploadWithProgressMock).toHaveBeenCalledTimes(2);
  });

  it("stops tracking an attachment that is removed mid-upload", async () => {
    deferredTransport();
    // Own thread id: the composer persists drafts per thread, and a leaked
    // draft from another test would keep Send enabled for the wrong reason.
    renderWithProviders(<ChatInputBox mode="react" threadId="thread-remove" />);
    pasteImage("discarded.png");

    await waitFor(() => expect(uploadWithProgressMock).toHaveBeenCalled());
    fireEvent.click(screen.getByTitle("Remove"));

    // Removing the chip must also clear its upload, or an abandoned transfer
    // would keep the send button disabled forever.
    await waitFor(() => expect(sendButton()).toBeDisabled());
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
