import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { WorkDirSelector } from "./workdir-selector";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    authStatus: { enabled: false },
    isAuthenticated: false,
    isLoading: false,
  }),
}));

describe("<WorkDirSelector />", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn((key: string) => store.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => store.set(key, value)),
      removeItem: vi.fn((key: string) => store.delete(key)),
      clear: vi.fn(() => store.clear()),
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: vi.fn().mockResolvedValue({
          success: false,
          path: null,
          canceled: true,
          error: null,
        }),
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("switches to personal space through the dropdown without opening a picker", async () => {
    const onWorkDirChange = vi.fn();
    const open = vi.fn();
    vi.stubGlobal("octopus", { dialog: { open } });
    renderWithProviders(
      <WorkDirSelector
        workDir="C:/Users/Administrator"
        variant="muted"
        onWorkDirChange={onWorkDirChange}
      />,
    );
    const trigger = screen.getByTitle(
      "Choose workspace folder: C:/Users/Administrator",
    );
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(
      await screen.findByRole("button", { name: "Personal space" }),
    );
    expect(onWorkDirChange).toHaveBeenCalledWith("");
    expect(open).not.toHaveBeenCalled();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the portaled menu open when pressing an action inside it", async () => {
    // The "Open folder" CTA only renders with a native picker (Electron).
    vi.stubGlobal("octopus", { dialog: { open: vi.fn() } });
    renderWithProviders(
      <WorkDirSelector
        workDir="F:/work/octopus-agent"
        onWorkDirChange={vi.fn()}
      />,
    );

    // A bound workDir trigger opens the portaled menu (handleMenuToggle).
    fireEvent.click(
      screen.getByTitle("Choose workspace folder: F:/work/octopus-agent"),
    );

    const openFolder = await screen.findByRole("button", {
      name: "Open folder",
    });
    // mouseDown inside the menu is stopPropagation'd, so the menu stays open.
    fireEvent.mouseDown(openFolder);

    expect(
      screen.getByRole("button", { name: "Open folder" }),
    ).toBeInTheDocument();
  });

  it("opens the in-app folder browser when no native picker bridge exists", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: vi.fn().mockResolvedValue({
          entries: [
            { name: "F:", path: "F:/", type: "dir", depth: 0, size: null },
            { name: "F:", path: "F:\\", type: "dir", depth: 0, size: null },
            {
              name: "C:",
              path: "C:\\Users\\12035",
              type: "dir",
              depth: 0,
              size: null,
            },
          ],
        }),
      }),
    );

    renderWithProviders(
      <WorkDirSelector workDir="" onWorkDirChange={onWorkDirChange} />,
    );

    fireEvent.click(screen.getByTitle("Choose workspace folder"));
    await screen.findByText("Browse current folder");
    await screen.findByText("F:");
    await screen.findByText("12035");
    expect(screen.getAllByText("F:")).toHaveLength(1);
    expect(onWorkDirChange).not.toHaveBeenCalled();
  });

  it("binds a recent workspace from the menu in web mode (no native picker)", async () => {
    const onWorkDirChange = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify(["/Users/example/Public"]),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    // An unavailable system picker reveals recent workspaces as the fallback.
    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(await screen.findByText("Public"));

    expect(onWorkDirChange).toHaveBeenCalledWith("/Users/example/Public");
  });

  it("opens a different recent workspace in a new task when the current thread is locked", async () => {
    const onWorkDirChange = vi.fn();
    const onOpenWorkDirInNewTask = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify([
        "/Users/example/OtherProject",
        "/Users/example/Public/octopus-agent",
      ]),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir="/Users/example/Public/octopus-agent"
        onWorkDirChange={onWorkDirChange}
        lockToCurrentThread
        onOpenWorkDirInNewTask={onOpenWorkDirInNewTask}
        variant="muted"
      />,
    );

    fireEvent.click(
      screen.getByTitle(
        "Current task is bound to this workspace: /Users/example/Public/octopus-agent",
      ),
    );
    fireEvent.click(await screen.findByText("OtherProject"));

    expect(onWorkDirChange).not.toHaveBeenCalled();
    expect(onOpenWorkDirInNewTask).toHaveBeenCalledWith(
      "/Users/example/OtherProject",
    );
  });

  it("keeps an existing personal-space thread bound when a workspace is selected", async () => {
    const onWorkDirChange = vi.fn();
    const onOpenWorkDirInNewTask = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify(["/Users/example/NewProject"]),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        lockToCurrentThread
        onOpenWorkDirInNewTask={onOpenWorkDirInNewTask}
        variant="muted"
      />,
    );

    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(await screen.findByText("NewProject"));

    expect(onWorkDirChange).not.toHaveBeenCalled();
    expect(onOpenWorkDirInNewTask).toHaveBeenCalledWith(
      "/Users/example/NewProject",
    );
  });

  it("offers manual path entry in web mode and binds a pasted absolute path", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          success: false,
          path: null,
          canceled: false,
          error: "picker unavailable",
        }),
      }),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    // A picker failure keeps manual path entry available.
    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose workspace folder" }),
    );
    const input = await screen.findByPlaceholderText(
      "Enter workspace directory path:",
    );
    expect(screen.getByText("Browse current folder")).toBeInTheDocument();
    expect(input).toHaveValue("");
    fireEvent.change(input, { target: { value: "/Users/example/proj" } });
    fireEvent.submit(input.closest("form")!);

    expect(onWorkDirChange).toHaveBeenCalledWith("/Users/example/proj");
  });

  it("binds the absolute path returned by the local backend picker", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          success: true,
          path: "/Users/example/PickedProject",
          canceled: false,
          error: null,
        }),
      }),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose workspace folder" }),
    );

    await waitFor(() => {
      expect(onWorkDirChange).toHaveBeenCalledWith(
        "/Users/example/PickedProject",
      );
    });
  });

  it("uses the Electron native folder picker when available", async () => {
    const onWorkDirChange = vi.fn();
    const open = vi.fn().mockResolvedValue({
      canceled: false,
      filePaths: ["F:\\picked\\project"],
    });
    vi.stubGlobal("octopus", {
      dialog: { open },
    });

    renderWithProviders(
      <WorkDirSelector
        workDir="F:/work/octopus-agent"
        onWorkDirChange={onWorkDirChange}
      />,
    );

    // The dropdown opens first; choosing Open folder invokes the native picker
    fireEvent.click(
      screen.getByTitle("Choose workspace folder: F:/work/octopus-agent"),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Open folder" }));
    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({
        title: "选择工作区文件夹",
        buttonLabel: "选取",
        message: "请选择一个文件夹作为工作区",
        properties: ["openDirectory", "createDirectory"],
        defaultPath: "F:/work/octopus-agent",
      });
      expect(onWorkDirChange).toHaveBeenCalledWith("F:\\picked\\project");
    });
  });

  it("can choose a workspace from filesystem roots when no folder is active", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        json: vi.fn().mockResolvedValue({
          entries: [
            { name: "F:", path: "F:/", type: "dir", depth: 0, size: null },
          ],
        }),
      }),
    );

    renderWithProviders(
      <WorkDirSelector workDir="" onWorkDirChange={onWorkDirChange} />,
    );

    // Empty default trigger opens the in-app folder browser menu.
    fireEvent.click(screen.getByTitle("Choose workspace folder"));
    await screen.findByText("F:");
    // Each browsed entry has a ✓ "choose this folder" button titled
    // "Choose workspace folder". The last one is the entry's choose button.
    const chooseButtons = await screen.findAllByTitle(
      "Choose workspace folder",
    );
    fireEvent.click(chooseButtons[chooseButtons.length - 1]);

    expect(onWorkDirChange).toHaveBeenCalledWith("F:/");
  });

  it("opens the desktop folder picker from the dropdown action", async () => {
    const onWorkDirChange = vi.fn();
    const open = vi.fn().mockResolvedValue({
      canceled: false,
      filePaths: ["F:\\picked\\primary"],
    });
    vi.stubGlobal("octopus", {
      dialog: {
        open,
      },
    });

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose workspace folder" }),
    );

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({
        title: "选择工作区文件夹",
        buttonLabel: "选取",
        message: "请选择一个文件夹作为工作区",
        properties: ["openDirectory", "createDirectory"],
        defaultPath: "",
      });
      expect(onWorkDirChange).toHaveBeenCalledWith("F:\\picked\\primary");
    });
  });

  it("discards a late native result after the user clicks outside", async () => {
    let resolvePicker!: (value: {
      canceled: boolean;
      filePaths: string[];
    }) => void;
    const open = vi.fn(
      () =>
        new Promise((resolve) => {
          resolvePicker = resolve;
        }),
    );
    vi.stubGlobal("octopus", { dialog: { open } });
    const onWorkDirChange = vi.fn();
    renderWithProviders(
      <>
        <button>Other action</button>
        <WorkDirSelector
          workDir=""
          variant="muted"
          onWorkDirChange={onWorkDirChange}
        />
      </>,
    );
    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose workspace folder" }),
    );
    expect(screen.getByTitle("Cancel")).toBeInTheDocument();
    const other = screen.getByRole("button", { name: "Other action" });
    fireEvent.mouseDown(other);
    other.focus();
    await act(async () =>
      resolvePicker({ canceled: false, filePaths: ["F:/late"] }),
    );
    expect(onWorkDirChange).not.toHaveBeenCalled();
    expect(screen.queryByText("Browse current folder")).toBeNull();
    expect(other).toHaveFocus();
  });

  it("keeps the fallback closed when the native dialog is canceled", async () => {
    const open = vi.fn().mockResolvedValue({ canceled: true, filePaths: [] });
    vi.stubGlobal("octopus", { dialog: { open } });
    renderWithProviders(
      <WorkDirSelector workDir="" variant="muted" onWorkDirChange={vi.fn()} />,
    );
    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Choose workspace folder" }),
    );
    await waitFor(() =>
      expect(screen.getByTitle("Personal space")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Browse current folder")).toBeNull();
  });
});
