import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MessageTimestamp } from "./message-list-item";

describe("MessageTimestamp", () => {
  it("renders nothing when no timestamp is provided", () => {
    const { container } = render(<MessageTimestamp />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the timestamp is unparseable", () => {
    const { container } = render(<MessageTimestamp createdAt="not-a-date" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders a local HH:mm label", () => {
    render(
      <MessageTimestamp createdAt="2026-05-09T10:30:00Z" alwaysVisible />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/)).toBeInTheDocument();
  });

  it("is always visible when alwaysVisible is set, otherwise hover-revealed", () => {
    const { rerender } = render(
      <MessageTimestamp createdAt="2026-05-09T10:30:00Z" alwaysVisible />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("opacity-100");

    rerender(
      <MessageTimestamp createdAt="2026-05-09T10:30:00Z" alwaysVisible={false} />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("opacity-0");
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain(
      "group-hover/conversation-message:opacity-100",
    );
  });

  it("aligns to the end for user bubbles", () => {
    render(
      <MessageTimestamp createdAt="2026-05-09T10:30:00Z" align="end" />,
    );
    expect(screen.getByText(/\d{2}:\d{2}/).className).toContain("self-end");
  });
});
