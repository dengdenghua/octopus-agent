import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { ConversationRosterStrip } from "./conversation-roster-strip";

describe("ConversationRosterStrip", () => {
  it("places the leader first and opens a member process directly", () => {
    const onOpenMemberProcess = vi.fn();
    renderWithProviders(
      <ConversationRosterStrip
        seats={[
          { id: "local", name: "Local", role: "群主", kind: "human" },
          {
            id: "zero",
            name: "Zero",
            role: "member",
            kind: "agent",
            description: "负责把多方结论汇总成可执行的方案。",
            model: "deepseek-v4",
            toolGroups: ["搜索", "文档"],
          },
          { id: "kane", name: "Kane", role: "tl", kind: "agent" },
        ]}
        onOpenMemberProcess={onOpenMemberProcess}
      />,
      { locale: "zh-CN" },
    );

    const strip = screen.getByTestId("conversation-roster-strip");
    const seats = strip.querySelectorAll("button");
    expect(seats[0]).toHaveAccessibleName("Kane · 群主 · 在场 · 查看执行过程");
    expect(seats[1]).toHaveAccessibleName("Zero · 协作 · 在场 · 查看执行过程");
    expect(screen.queryByText("Local")).toBeNull();
    expect(screen.getByText("★")).toBeInTheDocument();
    expect(screen.queryByText("群主")).toBeNull();

    fireEvent.click(seats[1]!);
    expect(onOpenMemberProcess).toHaveBeenCalledWith(
      expect.objectContaining({ id: "zero" }),
    );
  });
});
