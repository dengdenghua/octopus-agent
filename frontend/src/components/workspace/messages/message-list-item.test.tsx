import { render, screen } from "@testing-library/react";
import type { Message } from "@/core/api/types";
import { describe, expect, it } from "vitest";

import {
  containsProtocolMarkers,
  messageClipboardText,
  MessageTimestamp,
} from "./message-list-item";

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

describe("protocol cleaning bail-out", () => {
  it("does not skip the bare legacy sub-agent placeholder", () => {
    // The legacy placeholder may appear WITHOUT the optional `[...]`
    // prefix; its ASCII `(` must therefore be a first-mark so the
    // streaming fast path still runs the cleaning chain.
    expect(containsProtocolMarkers("(sub-agent exceeded token budget 100/200)")).toBe(
      true,
    );
  });

  it("empties a bare legacy sub-agent placeholder from clipboard text", () => {
    const message = {
      type: "ai",
      content: "(sub-agent exceeded token budget 100/200)",
    } as unknown as Message;
    expect(messageClipboardText(message)).toBe("");
  });

  it("still skips plain prose without protocol markers", () => {
    expect(
      containsProtocolMarkers("这是一段普通的流式回答，没有任何协议标记。"),
    ).toBe(false);
    expect(containsProtocolMarkers("plain english prose here")).toBe(false);
  });
});
