import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { BrowserStoreProvider, useBrowserStore } from "./browser-store";

function StoreHarness() {
  const { state, activeTab, openTab, closeTab, restoreClosedTab } =
    useBrowserStore();
  return (
    <div>
      <div data-testid="open-count">{state.tabs.length}</div>
      <div data-testid="closed-count">{state.closedTabs.length}</div>
      <div data-testid="active-url">{activeTab?.url}</div>
      <div data-testid="active-loading">{String(activeTab?.isLoading)}</div>
      <button onClick={() => openTab("https://example.com/path")}>open</button>
      <button onClick={() => activeTab && closeTab(activeTab.id)}>close</button>
      <button onClick={() => restoreClosedTab()}>restore</button>
      <button
        onClick={() =>
          openTab("https://example.com/task", {
            taskPreview: { threadId: "task-1", sessionId: "session-1" },
          })
        }
      >
        task
      </button>
      <div data-testid="task-session">{activeTab?.taskPreview?.sessionId}</div>
    </div>
  );
}

describe("browser tab recovery", () => {
  beforeEach(() => window.localStorage.clear());

  it("reuses a task session tab and preserves its identity after closing and restoring", () => {
    renderWithProviders(
      <BrowserStoreProvider>
        <StoreHarness />
      </BrowserStoreProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "task", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "open", exact: true }));
    fireEvent.click(screen.getByRole("button", { name: "task", exact: true }));
    expect(screen.getByTestId("open-count")).toHaveTextContent("3");
    expect(screen.getByTestId("task-session")).toHaveTextContent("session-1");
    fireEvent.click(screen.getByRole("button", { name: "close", exact: true }));
    fireEvent.click(
      screen.getByRole("button", { name: "restore", exact: true }),
    );
    expect(screen.getByTestId("task-session")).toHaveTextContent("session-1");
  });

  it("keeps recently closed tabs and restores the latest one", () => {
    renderWithProviders(
      <BrowserStoreProvider>
        <StoreHarness />
      </BrowserStoreProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "open" }));
    expect(screen.getByTestId("open-count")).toHaveTextContent("2");
    expect(screen.getByTestId("active-url")).toHaveTextContent(
      "https://example.com/path",
    );

    fireEvent.click(screen.getByRole("button", { name: "close" }));
    expect(screen.getByTestId("open-count")).toHaveTextContent("1");
    expect(screen.getByTestId("closed-count")).toHaveTextContent("1");

    fireEvent.click(screen.getByRole("button", { name: "restore" }));
    expect(screen.getByTestId("open-count")).toHaveTextContent("2");
    expect(screen.getByTestId("closed-count")).toHaveTextContent("0");
    expect(screen.getByTestId("active-url")).toHaveTextContent(
      "https://example.com/path",
    );
  });

  it("loads a previous unclean session without resuming a loading spinner", () => {
    window.localStorage.setItem(
      "octopus:browser-state",
      JSON.stringify({
        tabs: [
          {
            id: "saved-tab",
            url: "https://example.com/saved",
            title: "Saved",
            isLoading: true,
            device: "desktop",
          },
        ],
        closedTabs: [],
        activeId: "saved-tab",
        copilotOpen: false,
        copilotWidth: 380,
        homeSeeded: true,
      }),
    );

    renderWithProviders(
      <BrowserStoreProvider>
        <StoreHarness />
      </BrowserStoreProvider>,
    );

    expect(screen.getByTestId("open-count")).toHaveTextContent("1");
    expect(screen.getByTestId("active-url")).toHaveTextContent(
      "https://example.com/saved",
    );
    expect(screen.getByTestId("active-loading")).toHaveTextContent("false");
  });
});
