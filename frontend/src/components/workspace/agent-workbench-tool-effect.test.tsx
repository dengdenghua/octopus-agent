import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AgentWorkbenchPanel } from "./agent-workbench-panel";

describe("AgentWorkbenchPanel tool-effect focus", () => {
  it("uses the right rail for the selected receipt and can return to execution", () => {
    renderWithProviders(
      <AgentWorkbenchPanel
        focusedEffectKey="effect:risky-write"
        focusedEventNonce={1}
        events={[
          {
            id: "call-risk",
            name: "write_file",
            status: "error",
            startedAt: 1,
            iteration: 1,
            input: { path: "result.txt" },
          },
        ]}
      />,
      { locale: "zh-CN" },
    );

    expect(screen.getByText("外部动作核对")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回执行详情" }));
    expect(screen.queryByText("外部动作核对")).not.toBeInTheDocument();
    expect(screen.getByText("概要")).toBeInTheDocument();
  });
});
