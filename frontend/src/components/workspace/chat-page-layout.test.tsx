import { fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { ChatPageLayout } from "./chat-page-layout";

describe("ChatPageLayout input overlay measurement", () => {
  let overlayHeight = 148;
  const originalResizeObserver = globalThis.ResizeObserver;

  beforeEach(() => {
    overlayHeight = 148;
    Object.assign(globalThis, { ResizeObserver: undefined });

    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
      function () {
        const height = this.hasAttribute("data-chat-input-overlay")
          ? overlayHeight
          : 0;
        return {
          x: 0,
          y: 0,
          top: 0,
          right: 0,
          bottom: height,
          left: 0,
          width: 0,
          height,
          toJSON: () => ({}),
        };
      },
    );
  });

  afterEach(() => {
    Object.assign(globalThis, { ResizeObserver: originalResizeObserver });
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

    overlayHeight = 284;
    fireEvent(window, new Event("resize"));

    expect(workspace).toHaveStyle({
      "--chat-input-overlay-height": "284px",
    });
  });
});
