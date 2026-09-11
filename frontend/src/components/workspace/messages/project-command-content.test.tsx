import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProjectCommandContent } from "./project-command-content";

describe("sent project commands", () => {
  it("shows an icon for a command-only message", () => {
    const { container } = render(
      <ProjectCommandContent content="/project run" renderBody={(body) => <p>{body}</p>} />,
    );
    expect(screen.getByText("/project run")).toBeInTheDocument();
    expect(container.querySelector("svg")).toBeInTheDocument();
    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });

  it("keeps command arguments available to the normal message renderer", () => {
    render(<ProjectCommandContent content={"/project run\n发布准备"} renderBody={(body) => <p>{body}</p>} />);
    expect(screen.getByText("发布准备")).toBeInTheDocument();
    expect(screen.getByText("/project run")).toBeInTheDocument();
  });

  it.each(["解释 /project run", "```\n/project run\n```", "/projects run"])(
    "leaves ordinary text and code unchanged: %s", (content) => {
      const { container } = render(<ProjectCommandContent content={content} renderBody={(body) => <p>{body}</p>} />);
      expect(container.querySelector("p")?.textContent).toBe(content);
      expect(container.querySelector("svg")).toBeNull();
    },
  );
});
