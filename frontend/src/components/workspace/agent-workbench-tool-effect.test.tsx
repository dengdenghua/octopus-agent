import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { AGENT_WORKBENCH_LOCATE_EVENT } from "./agent-workbench-events";
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

  it("can locate the selected transcript event from the right rail", () => {
    const located: string[] = [];
    const listener = (event: Event) => {
      const detail = (event as CustomEvent<{ eventId?: string }>).detail;
      if (detail?.eventId) located.push(detail.eventId);
    };
    window.addEventListener(AGENT_WORKBENCH_LOCATE_EVENT, listener);

    try {
      renderWithProviders(
        <AgentWorkbenchPanel
          focusedEventId="thinking-7"
          focusedEventKind="thinking"
          focusedEventView="summary"
          focusedEventNonce={1}
          focusedProcessEvent={{
            kind: "thinking",
            summary: "已确认时间线顺序",
            detail: "公开进展留在主线，右侧只看细节。",
            status: "done",
          }}
          events={[]}
        />,
        { locale: "zh-CN" },
      );

      fireEvent.click(screen.getByRole("button", { name: "定位到主对话" }));
      expect(located).toEqual(["thinking-7"]);
    } finally {
      window.removeEventListener(AGENT_WORKBENCH_LOCATE_EVENT, listener);
    }
  });

  it("offers a panel-level close action when the parent provides one", () => {
    let closed = 0;
    renderWithProviders(
      <AgentWorkbenchPanel
        events={[
          {
            id: "call-read",
            name: "read_file",
            status: "running",
            startedAt: 1,
            iteration: 1,
            input: { path: "src/app.tsx" },
          },
        ]}
        onClose={() => {
          closed += 1;
        }}
      />,
      { locale: "zh-CN" },
    );

    fireEvent.click(screen.getByRole("button", { name: "收起工作台" }));
    expect(closed).toBe(1);
  });

  it("closes from Escape without stealing Escape from text inputs", () => {
    let closed = 0;
    renderWithProviders(
      <div>
        <input aria-label="draft" />
        <AgentWorkbenchPanel
          events={[
            {
              id: "call-read",
              name: "read_file",
              status: "running",
              startedAt: 1,
              iteration: 1,
              input: { path: "src/app.tsx" },
            },
          ]}
          onClose={() => {
            closed += 1;
          }}
        />
      </div>,
      { locale: "zh-CN" },
    );

    fireEvent.keyDown(screen.getByRole("textbox", { name: "draft" }), {
      key: "Escape",
    });
    expect(closed).toBe(0);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(closed).toBe(1);
  });
});
