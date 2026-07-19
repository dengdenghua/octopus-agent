import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { WorkDirSelector } from "./workdir-selector";

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
  });

  afterEach(() => {
    vi.unstubAllGlobals();
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
      JSON.stringify(["/Users/dangbei/Public"]),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    // Web mode: the trigger opens the menu (no OS picker); recents are listed
    // even in the muted variant so they can be rebound in one click.
    fireEvent.click(screen.getByTitle("Personal space"));
    fireEvent.click(await screen.findByText("Public"));

    expect(onWorkDirChange).toHaveBeenCalledWith("/Users/dangbei/Public");
  });

  it("opens a different recent workspace in a new task when the current thread is locked", async () => {
    const onWorkDirChange = vi.fn();
    const onOpenWorkDirInNewTask = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify([
        "/Users/dangbei/OtherProject",
        "/Users/dangbei/Public/octopus-agent",
      ]),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir="/Users/dangbei/Public/octopus-agent"
        onWorkDirChange={onWorkDirChange}
        lockToCurrentThread
        onOpenWorkDirInNewTask={onOpenWorkDirInNewTask}
        variant="muted"
      />,
    );

    fireEvent.click(
      screen.getByTitle(
        "Current task is bound to this workspace: /Users/dangbei/Public/octopus-agent",
      ),
    );
    fireEvent.click(await screen.findByText("OtherProject"));

    expect(onWorkDirChange).not.toHaveBeenCalled();
    expect(onOpenWorkDirInNewTask).toHaveBeenCalledWith(
      "/Users/dangbei/OtherProject",
    );
  });

  it("keeps an existing personal-space thread bound when a workspace is selected", async () => {
    const onWorkDirChange = vi.fn();
    const onOpenWorkDirInNewTask = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify(["/Users/dangbei/NewProject"]),
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
      "/Users/dangbei/NewProject",
    );
  });

  it("offers manual path entry in web mode and binds a pasted absolute path", async () => {
    const onWorkDirChange = vi.fn();

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    // Web mode: the trigger opens the menu with a manual-path field (no OS
    // picker that hands back an unusable folder name).
    fireEvent.click(screen.getByTitle("Personal space"));
    const input = await screen.findByPlaceholderText(
      "Enter workspace directory path:",
    );
    expect(input).toHaveValue("");
    fireEvent.change(input, { target: { value: "/Users/dangbei/proj" } });
    fireEvent.submit(input.closest("form")!);

    expect(onWorkDirChange).toHaveBeenCalledWith("/Users/dangbei/proj");
  });

  it("uses the Electron native folder picker when available", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal("octopus", {
      dialog: {
        open: vi.fn().mockResolvedValue({
          canceled: false,
          filePaths: ["F:\\picked\\project"],
        }),
      },
    });

    renderWithProviders(
      <WorkDirSelector
        workDir="F:/work/octopus-agent"
        onWorkDirChange={onWorkDirChange}
      />,
    );

    // A bound workDir trigger opens the menu; the folder-picker CTA inside
    // is what invokes the Electron native picker.
    fireEvent.click(
      screen.getByTitle("Choose workspace folder: F:/work/octopus-agent"),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Open folder" }));

    await waitFor(() => {
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

  it("opens the desktop folder picker from the muted primary trigger", async () => {
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

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({
        properties: ["openDirectory", "createDirectory"],
        defaultPath: "",
      });
      expect(onWorkDirChange).toHaveBeenCalledWith("F:\\picked\\primary");
    });
  });
});
