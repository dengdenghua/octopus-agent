import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProjectGroupHeaderBadge } from "./project-group-header-badge";

describe("ProjectGroupHeaderBadge", () => {
  it("presents the durable project identity and member count", () => {
    render(
      <ProjectGroupHeaderBadge
        name="品牌发布"
        status="running"
        memberCount={4}
      />,
    );

    expect(
      screen.getByLabelText("品牌发布 · 进行中 · 4 位成员"),
    ).toBeInTheDocument();
    expect(screen.getByText("品牌发布")).toBeInTheDocument();
  });

  it("uses safe fallbacks for an incomplete project projection", () => {
    render(
      <ProjectGroupHeaderBadge name="  " status="unknown" memberCount={0} />,
    );

    expect(
      screen.getByLabelText("项目群 · 项目群 · 1 位成员"),
    ).toBeInTheDocument();
  });
});
