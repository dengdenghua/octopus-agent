import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AIMessage } from "@/core/api/types";
import { renderWithProviders } from "@/test/harness";

import { MessageGroup } from "./message-group";

vi.mock("../artifacts", () => ({
  useArtifacts: () => ({
    setOpen: vi.fn(),
    autoOpen: false,
    autoSelect: false,
    selectedArtifact: null,
    select: vi.fn(),
  }),
}));

describe("MessageGroup labelled ReAct trace rendering", () => {
  it("splits labelled traces into action and observation rows", () => {
    const hiddenTail = "UNIQUE_OBSERVATION_TAIL_SHOULD_BE_COMPACTED";
    const message: AIMessage = {
      id: "ai-1",
      type: "ai",
      content: "",
      additional_kwargs: {
        reasoning_content: [
          "Thought: I need fresh market evidence before choosing a track.",
          "",
          "Action:",
          '  web_search({"query":"silver economy market"})',
          '  fetch_url({"url":"https://example.com/report"})',
          "",
          "Observation: [1/2 web_search]",
          "(real tool execution succeeded) web_search",
          `{"results":[{"title":"Report","url":"https://example.com/report"}],"tail":"${"x ".repeat(80)}${hiddenTail}"}`,
          "",
          "Thought: Now I can compare the options.",
        ].join("\n"),
      },
    };

    renderWithProviders(<MessageGroup messages={[message]} isLoading />, {
      locale: "en-US",
    });

    expect(screen.getByText("Searching")).toBeInTheDocument();
    expect(screen.getByText("Search sources")).toBeInTheDocument();
    expect(screen.queryByText(/web_search/)).not.toBeInTheDocument();
    expect(screen.queryByText(/fetch_url/)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/real tool execution succeeded/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(hiddenTail))).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Replay 2 previous steps"));

    expect(
      screen.getAllByText("Search sources: silver economy market").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Read webpage: https://example.com/report").length,
    ).toBeGreaterThan(0);
  });
});
