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

  it("keeps the muted empty state as personal space with one folder action", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(
      <WorkDirSelector workDir="" onWorkDirChange={vi.fn()} variant="muted" />,
    );

    expect(screen.getByText("Personal space")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Choose folder"));

    expect(await screen.findByText("Choose folder")).toBeInTheDocument();
    expect(
      screen.queryByPlaceholderText("Enter workspace directory path:"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Recent workspaces")).not.toBeInTheDocument();
    expect(screen.queryByText("Browse current folder")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("opens the desktop folder picker from the muted folder action", async () => {
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

    fireEvent.click(screen.getByTitle("Choose folder"));
    fireEvent.click(await screen.findByText("Choose folder"));

    await waitFor(() => {
      expect(open).toHaveBeenCalledWith({
        properties: ["openDirectory"],
        defaultPath: "",
      });
      expect(onWorkDirChange).toHaveBeenCalledWith("F:\\picked\\space");
    });
  });
});
