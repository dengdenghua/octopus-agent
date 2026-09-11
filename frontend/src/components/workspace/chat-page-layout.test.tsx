import { useState } from "react";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { ChatPageLayout } from "./chat-page-layout";

function OverlayLifecycleHarness() {
  const [open, setOpen] = useState(false);
  const [revision, setRevision] = useState(0);

  return (
    <ChatPageLayout
      header={
        <button type="button" onClick={() => setOpen(true)}>
          Open workbench
        </button>
      }
      messageList={<div>Messages</div>}
      inputArea={<div>Composer</div>}
      secondaryPanel={
        open ? (
          <button
            type="button"
            onClick={() => setRevision((value) => value + 1)}
          >
            Panel action {revision}
          </button>
        ) : undefined
      }
      onSecondaryClose={() => setOpen(false)}
    />
  );
}

function OverlayRecoveryHarness() {
  const [showUtility, setShowUtility] = useState(true);
  const [revision, setRevision] = useState(0);

  return (
    <>
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={
          <div>
            {showUtility ? (
              <button type="button" onClick={() => setShowUtility(false)}>
                Unmount utility
              </button>
            ) : (
              <span>Utility removed</span>
            )}
            <span>Revision {revision}</span>
          </div>
        }
      />
      <div data-radix-portal="">
        <button type="button" onClick={() => setRevision((value) => value + 1)}>
          Portal action {revision}
        </button>
      </div>
    </>
  );
}

describe("ChatPageLayout", () => {
  let overlayHeight = 148;
  let layoutWidth = 1400;
  const originalResizeObserver = globalThis.ResizeObserver;
  const originalInnerWidth = window.innerWidth;

  beforeEach(() => {
    overlayHeight = 148;
    layoutWidth = 1400;
    window.localStorage.removeItem("octopus:chatSidebarWidth");
    window.localStorage.removeItem("octopus:chatSecondaryPanelWidth");
    Object.assign(globalThis, { ResizeObserver: undefined });

    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function () {
        const height = this.hasAttribute("data-chat-input-overlay")
          ? overlayHeight
          : 0;
        const width = this.hasAttribute("data-chat-page-layout-root")
          ? layoutWidth
          : 0;
        return {
          x: 0,
          y: 0,
          top: 0,
          right: width,
          bottom: height,
          left: 0,
          width,
          height,
          toJSON: () => ({}),
        };
      },
    );
  });

  afterEach(() => {
    Object.assign(globalThis, { ResizeObserver: originalResizeObserver });
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: originalInnerWidth,
    });
    vi.restoreAllMocks();
  });

  test("publishes live composer height for floating conversation controls", () => {
    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
      />,
    );

    const workspace = screen.getByRole("region", {
      name: "Conversation workspace",
    });
    expect(workspace).toHaveStyle({
      "--chat-input-overlay-height": "148px",
    });

    overlayHeight = 149;
    fireEvent(window, new Event("resize"));

    expect(workspace).toHaveStyle({
      "--chat-input-overlay-height": "148px",
    });

    overlayHeight = 284;
    fireEvent(window, new Event("resize"));

    expect(workspace).toHaveStyle({
      "--chat-input-overlay-height": "284px",
    });
  });

  test("owns exactly one page-level heading", () => {
    const { container } = renderWithProviders(
      <ChatPageLayout
        pageTitle="New task"
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<h2>Welcome</h2>}
      />,
    );

    expect(
      screen.getByRole("heading", { level: 1, name: "New task" }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });

  test("uses a layout-local right drawer when a desktop container cannot fit the workbench", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 900;

    const onSecondaryClose = vi.fn();
    const { container } = renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={<div>Workbench</div>}
        onSecondaryClose={onSecondaryClose}
      />,
    );

    const workbench = screen.getByRole("dialog", {
      name: "Agent workbench",
    });
    expect(workbench).toHaveAttribute("aria-modal", "true");
    expect(workbench).toHaveFocus();
    expect(workbench).toHaveAttribute(
      "data-secondary-panel-presentation",
      "desktop-drawer",
    );
    expect(workbench).toHaveClass("absolute", "inset-y-0", "right-0");
    expect(workbench).not.toHaveClass("fixed", "bottom-0", "left-0");
    expect(
      screen.queryByRole("button", {
        name: "Expand or collapse the agent workbench drawer",
      }),
    ).not.toBeInTheDocument();

    const backdrop = container.querySelector(
      '[data-secondary-panel-backdrop="desktop-drawer"]',
    );
    expect(backdrop).toHaveClass("absolute", "inset-0");
    fireEvent.click(backdrop!);
    expect(onSecondaryClose).toHaveBeenCalledOnce();
  });

  test("manages modal focus, inert background, Escape close, and focus restoration", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 900;

    const { container } = renderWithProviders(<OverlayLifecycleHarness />);
    const opener = screen.getByRole("button", { name: "Open workbench" });
    const mainColumn = container.querySelector(
      '[data-chat-page-main-column="true"]',
    );

    opener.focus();
    fireEvent.click(opener);

    const dialog = screen.getByRole("dialog", { name: "Agent workbench" });
    expect(dialog).toHaveFocus();
    expect(mainColumn).toHaveAttribute("inert");
    expect(mainColumn).toHaveAttribute("aria-hidden", "true");

    // A normal panel render must not steal focus back from its active control.
    const panelAction = screen.getByRole("button", { name: "Panel action 0" });
    panelAction.focus();
    fireEvent.click(panelAction);
    expect(
      screen.getByRole("button", { name: "Panel action 1" }),
    ).toHaveFocus();
    expect(dialog).not.toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(
      screen.queryByRole("dialog", { name: "Agent workbench" }),
    ).not.toBeInTheDocument();
    expect(mainColumn).not.toHaveAttribute("inert");
    expect(mainColumn).not.toHaveAttribute("aria-hidden");
    expect(opener).toHaveFocus();
  });

  test("returns to the composer when a responsive transition lost the opener", () => {
    layoutWidth = 900;
    const content = {
      header: <div>Header</div>,
      messageList: <div>Messages</div>,
      inputArea: <textarea aria-label="Draft" />,
    };
    const { rerender } = renderWithProviders(
      <ChatPageLayout {...content} secondaryPanel={<div>Workbench</div>} />,
    );
    expect(
      screen.getByRole("dialog", { name: "Agent workbench" }),
    ).toHaveFocus();
    rerender(<ChatPageLayout {...content} />);
    expect(screen.getByRole("textbox", { name: "Draft" })).toHaveFocus();
  });

  test("lets editable controls and nested popup surfaces consume Escape", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 900;
    const onSecondaryClose = vi.fn();

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={
          <div>
            <input aria-label="Guarded input" />
            <textarea aria-label="Guarded textarea" />
            <select aria-label="Guarded select" defaultValue="one">
              <option value="one">One</option>
            </select>
            <div
              contentEditable
              suppressContentEditableWarning
              role="textbox"
              aria-label="Guarded editor"
            >
              Editable
            </div>
            <div role="menu" aria-label="Nested menu">
              <button type="button" role="menuitem">
                Menu action
              </button>
            </div>
            <button type="button" onKeyDown={(event) => event.preventDefault()}>
              Handled Escape
            </button>
            <button type="button">Close with Escape</button>
          </div>
        }
        onSecondaryClose={onSecondaryClose}
      />,
    );

    const guardedControls = [
      screen.getByRole("textbox", { name: "Guarded input" }),
      screen.getByRole("textbox", { name: "Guarded textarea" }),
      screen.getByRole("combobox", { name: "Guarded select" }),
      screen.getByRole("textbox", { name: "Guarded editor" }),
      screen.getByRole("menuitem", { name: "Menu action" }),
      screen.getByRole("button", { name: "Handled Escape" }),
    ];
    for (const control of guardedControls) {
      control.focus();
      fireEvent.keyDown(control, { key: "Escape" });
    }
    expect(onSecondaryClose).not.toHaveBeenCalled();

    const closeControl = screen.getByRole("button", {
      name: "Close with Escape",
    });
    closeControl.focus();
    fireEvent.keyDown(closeControl, { key: "Escape" });
    expect(onSecondaryClose).toHaveBeenCalledOnce();
  });

  test("recovers focus after active utility unmount without stealing Radix portal focus", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 900;

    renderWithProviders(<OverlayRecoveryHarness />);
    const dialog = screen.getByRole("dialog", { name: "Agent workbench" });
    const utility = screen.getByRole("button", { name: "Unmount utility" });

    utility.focus();
    fireEvent.click(utility);
    expect(screen.getByText("Utility removed")).toBeInTheDocument();
    expect(dialog).toHaveFocus();

    const portalAction = screen.getByRole("button", {
      name: "Portal action 0",
    });
    portalAction.focus();
    fireEvent.click(portalAction);
    expect(
      screen.getByRole("button", { name: "Portal action 1" }),
    ).toHaveFocus();
    expect(dialog).not.toHaveFocus();
  });

  test("keeps the header in the conversation column while inline panels span the full shell", () => {
    layoutWidth = 1400;

    const { container } = renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        sidebar={<div>Utility</div>}
        showSidebar
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    const root = container.querySelector('[data-chat-page-layout-root="true"]');
    const mainColumn = container.querySelector(
      '[data-chat-page-main-column="true"]',
    );
    const header = container.querySelector('[data-chat-page-header="true"]');
    const utility = screen.getByRole("complementary", {
      name: "Artifacts, plan, and research panel",
    });
    const workbench = screen.getByRole("complementary", {
      name: "Agent workbench",
    });

    expect(header?.parentElement).toBe(mainColumn);
    expect(mainColumn?.parentElement).toBe(root);
    expect(utility.parentElement).toBe(root);
    expect(workbench.parentElement).toBe(root);
    expect(mainColumn).not.toHaveAttribute("aria-hidden");
    expect(mainColumn).not.toHaveAttribute("inert");
    expect(workbench).not.toHaveAttribute("aria-modal");
    expect(utility).toHaveClass("border-l", "bg-background");
    expect(workbench).toHaveClass("border-l", "bg-background");
    expect(utility).not.toHaveClass(
      "backdrop-blur-[10px]",
      "shadow-[-12px_0_32px_-16px_rgba(0,0,0,0.12)]",
    );
    expect(workbench).not.toHaveClass(
      "backdrop-blur-[10px]",
      "shadow-[-12px_0_32px_-16px_rgba(0,0,0,0.12)]",
    );
  });

  test("keeps the workbench inline below the old viewport breakpoint when its container has room", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1024,
    });
    layoutWidth = 1000;

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    const workbench = screen.getByRole("complementary", {
      name: "Agent workbench",
    });
    expect(workbench).toHaveAttribute(
      "data-secondary-panel-presentation",
      "inline",
    );
    expect(workbench).not.toHaveClass("fixed");
    expect(workbench).toHaveStyle({ width: "360px" });
    expect(workbench.querySelector('[role="separator"]')).toHaveAttribute(
      "aria-valuemin",
      "360",
    );
    expect(workbench.querySelector('[role="separator"]')).toHaveAttribute(
      "aria-valuemax",
      "800",
    );
  });

  test("preserves the mobile workbench drawer behavior", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 767,
    });
    // Deliberately wider than a real mobile root so the assertion proves the
    // mobile viewport rule remains independent from the container-fit rule.
    layoutWidth = 1300;

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    expect(
      screen.getByRole("dialog", { name: "Agent workbench" }),
    ).toHaveAttribute("data-secondary-panel-presentation", "bottom-sheet");
    expect(screen.getByRole("dialog", { name: "Agent workbench" })).toHaveClass(
      "fixed",
      "right-0",
      "bottom-0",
      "left-0",
    );
    expect(
      screen.getByRole("dialog", { name: "Agent workbench" }),
    ).toHaveAttribute("aria-modal", "true");
    expect(
      screen.getByRole("dialog", { name: "Agent workbench" }),
    ).toHaveFocus();
  });

  test("reacts to container-only resizes through ResizeObserver", () => {
    const resizeCallbacks: Array<() => void> = [];
    class MockResizeObserver {
      constructor(callback: ResizeObserverCallback) {
        resizeCallbacks.push(() =>
          callback([], this as unknown as ResizeObserver),
        );
      }

      observe() {}
      unobserve() {}
      disconnect() {}
    }
    Object.assign(globalThis, { ResizeObserver: MockResizeObserver });
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 1300;

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    expect(
      screen.getByRole("complementary", { name: "Agent workbench" }),
    ).not.toHaveClass("fixed");

    layoutWidth = 900;
    act(() => resizeCallbacks.forEach((notify) => notify()));

    expect(
      screen.getByRole("dialog", { name: "Agent workbench" }),
    ).toHaveAttribute("data-secondary-panel-presentation", "desktop-drawer");
  });

  test("temporarily clamps a persisted width without overwriting it", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    window.localStorage.setItem("octopus:chatSecondaryPanelWidth", "500");
    layoutWidth = 1200;

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    const workbench = screen.getByRole("complementary", {
      name: "Agent workbench",
    });
    expect(workbench).toHaveStyle({ width: "500px" });

    layoutWidth = 1050;
    fireEvent(window, new Event("resize"));
    expect(workbench).toHaveStyle({ width: "430px" });
    expect(window.localStorage.getItem("octopus:chatSecondaryPanelWidth")).toBe(
      "500",
    );

    layoutWidth = 1200;
    fireEvent(window, new Event("resize"));
    expect(workbench).toHaveStyle({ width: "500px" });
  });

  test("clamps two inline panels to preserve a 620px conversation column", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 1300;

    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<div>Composer</div>}
        sidebar={<div>Utility</div>}
        showSidebar
        secondaryPanel={<div>Workbench</div>}
      />,
    );

    expect(
      screen.getByRole("complementary", {
        name: "Artifacts, plan, and research panel",
      }),
    ).toHaveStyle({ width: "300px" });
    expect(
      screen.getByRole("complementary", { name: "Agent workbench" }),
    ).toHaveStyle({ width: "380px" });
  });
  test("expands content without remounting the editor or panel and restores split width", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    const { container } = renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<textarea aria-label="Draft" defaultValue="Keep my draft" />}
        secondaryPanel={
          <input
            aria-label="Browser address"
            defaultValue="https://example.com"
          />
        }
      />,
    );
    const editor = screen.getByRole("textbox", { name: "Draft" });
    const address = screen.getByRole("textbox", { name: "Browser address" });
    const panel = screen.getByRole("complementary", {
      name: "Agent workbench",
    });
    const width = panel.style.width;
    fireEvent.change(editor, { target: { value: "Edited draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand workbench" }));
    expect(panel).toHaveAttribute("data-secondary-panel-presentation", "full");
    expect(screen.getByRole("textbox", { name: "Draft" })).toBe(editor);
    expect(screen.getByRole("textbox", { name: "Browser address" })).toBe(
      address,
    );
    expect(editor).toHaveValue("Edited draft");
    expect(
      container.querySelector('[data-composer-placement="floating"]'),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse composer" }));
    expect(editor).toBeInTheDocument();
    expect(editor).not.toBeVisible();
    expect(panel.style.paddingBottom).toBe("");
    fireEvent.click(
      screen.getByRole("button", { name: "Continue conversation" }),
    );
    expect(screen.getByRole("textbox", { name: "Draft" })).toBe(editor);
    expect(editor).toHaveValue("Edited draft");
    fireEvent.click(screen.getByRole("button", { name: "Restore split view" }));
    expect(panel.style.width).toBe(width);
    expect(editor).toHaveValue("Edited draft");
    expect(
      container.querySelector('[data-composer-placement="docked"]'),
    ).toBeInTheDocument();
  });

  test("pending approvals reveal a compact composer and prevent collapsing it", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    function AttentionHarness() {
      const [attention, setAttention] = useState(false);
      return (
        <ChatPageLayout
          header={<div>Header</div>}
          messageList={<div>Messages</div>}
          composerNeedsAttention={attention}
          inputArea={
            <textarea aria-label="Approval draft" defaultValue="Retained" />
          }
          secondaryPanel={
            <button onClick={() => setAttention(true)}>Request approval</button>
          }
        />
      );
    }
    renderWithProviders(<AttentionHarness />);
    const editor = screen.getByRole("textbox", { name: "Approval draft" });
    fireEvent.click(screen.getByRole("button", { name: "Expand workbench" }));
    fireEvent.compositionStart(editor);
    fireEvent.click(screen.getByRole("button", { name: "Collapse composer" }));
    expect(editor).toBeVisible();
    fireEvent.compositionEnd(editor);
    fireEvent.click(screen.getByRole("button", { name: "Collapse composer" }));
    expect(editor).not.toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Request approval" }));
    expect(editor).toBeVisible();
    expect(editor).toHaveValue("Retained");
    expect(
      screen.getByRole("button", { name: "Collapse composer" }),
    ).toBeDisabled();
  });

  test("keeps the desktop drawer content mounted when expanding into full view", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1200,
    });
    layoutWidth = 900;
    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<textarea aria-label="Draft" />}
        secondaryPanel={<input aria-label="Browser address" />}
      />,
    );
    const address = screen.getByRole("textbox", { name: "Browser address" });
    fireEvent.click(screen.getByRole("button", { name: "Expand workbench" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Browser address" })).toBe(
      address,
    );
    expect(screen.getByRole("textbox", { name: "Draft" })).toBeInTheDocument();
  });
  test("dragging beyond the conversation threshold enters full view without overwriting split width", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    window.localStorage.setItem("octopus:chatSecondaryPanelWidth", "500");
    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<textarea aria-label="Draft" />}
        secondaryPanel={<div>Workbench</div>}
      />,
    );
    const panel = screen.getByRole("complementary", {
      name: "Agent workbench",
    });
    vi.spyOn(panel, "getBoundingClientRect").mockReturnValue({
      width: 500,
    } as DOMRect);
    const separator = screen.getByRole("separator", {
      name: "Resize agent workbench width",
    });
    fireEvent.mouseDown(separator, { clientX: 900 });
    fireEvent.mouseMove(document, { clientX: 100 });
    fireEvent.mouseUp(document);
    expect(panel).toHaveAttribute("data-secondary-panel-presentation", "full");
    expect(window.localStorage.getItem("octopus:chatSecondaryPanelWidth")).toBe(
      "500",
    );
    expect(document.body.style.cursor).toBe("");
    fireEvent.click(screen.getByRole("button", { name: "Restore split view" }));
    expect(panel).toHaveStyle({ width: "500px" });
    // Crossing the threshold and then moving back before release must not expand.
    fireEvent.mouseDown(separator, { clientX: 900 });
    fireEvent.mouseMove(document, { clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 850 });
    fireEvent.mouseUp(document);
    expect(panel).toHaveAttribute(
      "data-secondary-panel-presentation",
      "inline",
    );
    expect(panel).toHaveStyle({ width: "550px" });
  });

  test("full view yields to the mobile sheet and returns without remounting the composer", () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    renderWithProviders(
      <ChatPageLayout
        header={<div>Header</div>}
        messageList={<div>Messages</div>}
        inputArea={<textarea aria-label="Draft" defaultValue="Keep" />}
        secondaryPanel={<div>Workbench</div>}
      />,
    );
    const editor = screen.getByRole("textbox", { name: "Draft" });
    fireEvent.click(screen.getByRole("button", { name: "Expand workbench" }));
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 500,
    });
    layoutWidth = 500;
    fireEvent(window, new Event("resize"));
    expect(screen.getByRole("dialog")).toHaveAttribute(
      "data-secondary-panel-presentation",
      "bottom-sheet",
    );
    expect(editor).toBeInTheDocument();
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    });
    layoutWidth = 1400;
    fireEvent(window, new Event("resize"));
    expect(
      screen.getByRole("complementary", { name: "Agent workbench" }),
    ).toHaveAttribute("data-secondary-panel-presentation", "full");
    expect(screen.getByRole("textbox", { name: "Draft" })).toBe(editor);
    expect(editor).toHaveValue("Keep");
  });
});
