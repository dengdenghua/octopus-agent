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
  test("allocates a fresh local thread when navigating to /new again", async () => {
    renderWithProviders(<ThreadChatProbe />, {
      initialRoute: "/workspace/realtime/new",
    });
    const firstThreadId = screen.getByTestId("thread-id").textContent;

    fireEvent.click(screen.getByRole("button", { name: "New task" }));

    await waitFor(() => {
      expect(screen.getByTestId("thread-id").textContent).not.toBe(
        firstThreadId,
      );
    });
    expect(screen.getByTestId("is-new")).toHaveTextContent("true");
  });
});
