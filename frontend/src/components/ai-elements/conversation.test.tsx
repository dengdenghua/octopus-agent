import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const stickState = vi.hoisted(() => ({
  isAtBottom: false,
  scrollToBottom: vi.fn(),
}));

vi.mock("use-stick-to-bottom", () => {
  const StickToBottom = Object.assign(
    ({ children }: { children: ReactNode }) => <div>{children}</div>,
    {
      Content: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    },
  );
  return {
    StickToBottom,
    useStickToBottomContext: () => stickState,
  };
});

import { ConversationScrollButton } from "./conversation";

describe("ConversationScrollButton", () => {
  beforeEach(() => {
    stickState.isAtBottom = false;
    stickState.scrollToBottom.mockReset();
  });

  it("keeps one unseen-content signal while the reader is away from the bottom", () => {
    const { rerender } = render(
      <ConversationScrollButton
        activityKey="step-1"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );

    expect(screen.getByRole("button")).toHaveTextContent("Latest");

    rerender(
      <ConversationScrollButton
        activityKey="step-2"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );
    expect(screen.getByRole("button")).toHaveTextContent("1 new");

    rerender(
      <ConversationScrollButton
        activityKey="step-3"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );
    expect(screen.getByRole("button")).toHaveTextContent("1 new");

    fireEvent.click(screen.getByRole("button"));
    expect(stickState.scrollToBottom).toHaveBeenCalledOnce();
    expect(screen.getByRole("button")).toHaveTextContent("Latest");
  });

  it("hides and clears the counter after returning to the bottom", () => {
    const { rerender } = render(
      <ConversationScrollButton
        activityKey="step-1"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );

    rerender(
      <ConversationScrollButton
        activityKey="step-2"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );
    expect(screen.getByRole("button")).toHaveTextContent("1 new");

    stickState.isAtBottom = true;
    rerender(
      <ConversationScrollButton
        activityKey="step-2"
        activityLabel={(count) => `${count} new`}
      >
        Latest
      </ConversationScrollButton>,
    );

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
