import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ReasoningItem } from "@/core/realtime";
import { renderWithProviders } from "@/test/harness";

import { ReasoningView } from "./reasoning-view";

describe("ReasoningView", () => {
  it("hides raw ReAct labels in collapsed and expanded reasoning", () => {
    const item: ReasoningItem = {
      id: "reasoning-1",
      type: "reasoning",
      status: "completed",
      createdAt: "2026-05-29T00:00:00.000Z",
      summary: [],
      content: "Thought: inspect the project\nAction: list_cwd({\"path\":\".\"})",
    };

    renderWithProviders(<ReasoningView item={item} />, { locale: "en-US" });

    expect(screen.getByText(/inspect the project/)).toBeInTheDocument();
    expect(screen.queryByText(/Thought:/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Reasoning/i }));

    expect(screen.getByText(/list_cwd/)).toBeInTheDocument();
    expect(screen.queryByText(/Action:/)).not.toBeInTheDocument();
  });
});
