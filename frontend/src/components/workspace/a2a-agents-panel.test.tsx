import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { renderWithProviders } from "@/test/harness";
import { A2AAgentsPanel } from "./a2a-agents-panel";

vi.mock("@/core/auth/api", () => ({
  authHeaders: () => ({}),
  jsonAuthHeaders: () => ({}),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("opens a saved remote result and downloads binary artifacts without rendering remote HTML", async () => {
  const agent = {
    agent_id: "workbuddy",
    name: "WorkBuddy",
    description: "Remote specialist",
    version: "1.0.0",
    base_url: "http://127.0.0.1:8321",
    status: "active",
    skills: [],
    capabilities: {
      streaming: true,
      pushNotifications: false,
      multiTurn: true,
    },
  };
  const result = {
    id: "remote1",
    status: { state: "3" },
    messages: [],
    artifacts: [
      {
        name: "report.html",
        parts: [
          {
            type: "file",
            filename: "../report.html",
            raw: btoa("<script>alert(1)</script>"),
            media_type: "text/html",
          },
        ],
      },
    ],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (input: string) =>
        new Response(
          JSON.stringify(
            String(input).includes("/api/a2a/tasks")
              ? {
                  tasks: [
                    {
                      local_task_id: "local1",
                      remote_task_id: "remote1",
                      status: "completed",
                      terminal_at: "now",
                      request: { text: "Saved task" },
                      result,
                    },
                  ],
                }
              : { agents: [agent], count: 1 },
          ),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
    ),
  );
  const createURL = vi.fn((_blob: Blob) => "blob:test-download");
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = createURL;
      static revokeObjectURL = vi.fn();
    },
  );
  let filename = "";
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    filename = this.download;
  });
  renderWithProviders(
    <TooltipProvider>
      <A2AAgentsPanel />
    </TooltipProvider>,
  );
  fireEvent.click(await screen.findByText("WorkBuddy"));
  fireEvent.click(await screen.findByRole("button", { name: "Saved task" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "↓ ../report.html" }),
  );
  expect(filename).toBe("report.html");
  expect(createURL.mock.calls[0]?.[0]).toBeInstanceOf(Blob);
  expect((createURL.mock.calls[0]?.[0] as Blob).type).toBe(
    "application/octet-stream",
  );
  expect(document.querySelector("script")).toBeNull();
});
