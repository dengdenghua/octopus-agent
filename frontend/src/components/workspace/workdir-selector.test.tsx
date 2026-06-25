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
    renderWithProviders(
      <WorkDirSelector
        workDir="F:/work/octopus-agent"
        onWorkDirChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTitle("Recent workspaces"));

    const openFolder = await screen.findByRole("button", {
      name: "Open folder",
    });
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

  it("maps a browser-picked folder name back to a recent absolute workspace", async () => {
    const onWorkDirChange = vi.fn();
    localStorage.setItem(
      "octopus:recentWorkdirs",
      JSON.stringify(["/Users/dangbei/Public"]),
    );
    vi.stubGlobal(
      "showDirectoryPicker",
      vi.fn().mockResolvedValue({ name: "Public" }),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    fireEvent.click(screen.getByTitle("Personal space"));

    await waitFor(() => {
      expect(onWorkDirChange).toHaveBeenCalledWith("/Users/dangbei/Public");
    });
  });

  it("falls back to manual path input when browser folder picker has no path match", async () => {
    const onWorkDirChange = vi.fn();
    vi.stubGlobal(
      "showDirectoryPicker",
      vi.fn().mockResolvedValue({ name: "UnknownFolder" }),
    );

    renderWithProviders(
      <WorkDirSelector
        workDir=""
        onWorkDirChange={onWorkDirChange}
        variant="muted"
      />,
    );

    fireEvent.click(screen.getByTitle("Personal space"));

    expect(
      await screen.findByPlaceholderText("Enter workspace directory path:"),
    ).toHaveValue("UnknownFolder");
    expect(onWorkDirChange).not.toHaveBeenCalled();
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

    fireEvent.click(
      screen.getByTitle("Choose workspace folder: F:/work/octopus-agent"),
    );

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

    fireEvent.click(screen.getByTitle("Recent workspaces"));
    await screen.findByText("F:");
    const chooseButtons = await screen.findAllByTitle(
      "Choose workspace folder",
    );
    fireEvent.click(chooseButtons[chooseButtons.length - 1]);

    expect(onWorkDirChange).toHaveBeenCalledWith("F:/");
  });

  it("keeps the muted empty state as personal space with one workspace action", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(
      <WorkDirSelector workDir="" onWorkDirChange={vi.fn()} variant="muted" />,
    );

    expect(screen.getByText("Personal space")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Choose workspace folder"));

    expect(
      await screen.findByText("Choose workspace folder"),
    ).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Enter workspace directory path:"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Recent workspaces")).not.toBeInTheDocument();
    expect(screen.queryByText("Browse current folder")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens the desktop folder picker from the muted workspace action", async () => {
    const onWorkDirChange = vi.fn();
    const open = vi.fn().mockResolvedValue({
      canceled: false,
      filePaths: ["F:\\picked\\space"],
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

    fireEvent.click(screen.getByTitle("Choose workspace folder"));
    fireEvent.click(await screen.findByText("Choose workspace folder"));

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({
        properties: ["openDirectory", "createDirectory"],
        defaultPath: "",
      });
      expect(onWorkDirChange).toHaveBeenCalledWith("F:\\picked\\space");
    });
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
