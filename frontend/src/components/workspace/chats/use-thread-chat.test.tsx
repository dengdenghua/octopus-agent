import { fireEvent, screen, waitFor } from "@testing-library/react";
import { useNavigate } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { useThreadChat } from "./use-thread-chat";

function ThreadChatProbe() {
  const navigate = useNavigate();
  const { isNewThread, threadId } = useThreadChat();
  return (
    <div>
      <output data-testid="thread-id">{threadId}</output>
      <output data-testid="is-new">{String(isNewThread)}</output>
      <button
        type="button"
        onClick={() =>
          navigate("/workspace/realtime/new", {
            state: { taskNonce: "second" },
          })
        }
      >
        New task
      </button>
    </div>
  );
}

describe("useThreadChat", () => {
  test("keeps the same local thread when re-entering the /new route", async () => {
    renderWithProviders(<ThreadChatProbe />, {
      initialRoute: "/workspace/realtime/new",
    });
    const firstThreadId = screen.getByTestId("thread-id").textContent;
    expect(screen.getByTestId("is-new")).toHaveTextContent("true");

    fireEvent.click(screen.getByRole("button", { name: "New task" }));

    // The /new route is now a stable identity (pathId = pathname|threadId),
    // so re-entering it does NOT allocate a fresh thread — the in-progress
    // draft is preserved instead of being discarded.
    await waitFor(() => {
      expect(screen.getByTestId("thread-id").textContent).toBe(firstThreadId);
    });
    expect(screen.getByTestId("is-new")).toHaveTextContent("true");
  });
});
