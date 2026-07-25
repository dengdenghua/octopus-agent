import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Agent } from "@/core/agents";

import { AgentAvatar } from "./sidebar-footer";

describe("AgentAvatar", () => {
  it("keeps bundled partner logos on the frontend origin", () => {
    const agent: Agent = {
      name: "local_claude_code",
      display_name: "Claude Code",
      description: "Local CLI partner",
      avatar_url: "/assets/claude-code.png",
      icon: "CC",
      model: null,
      tool_groups: null,
    };

    const { container } = render(<AgentAvatar agent={agent} />);

    expect(container.querySelector("img")).toHaveAttribute(
      "src",
      "/assets/claude-code.png",
    );
  });

  it("falls back to the provider icon when a remote CLI logo fails", () => {
    const agent: Agent = {
      name: "local_trae_cli",
      display_name: "Trae CLI",
      description: "Local CLI partner",
      avatar_url: "https://invalid.example/trae.svg",
      icon: "🟦",
      model: null,
      tool_groups: null,
    };

    const { container } = render(<AgentAvatar agent={agent} />);
    const image = container.querySelector("img");
    expect(image).not.toBeNull();
    fireEvent.error(image!);

    expect(container.querySelector("img")).not.toBeInTheDocument();
    expect(screen.getByText("🟦")).toBeInTheDocument();
  });
});
