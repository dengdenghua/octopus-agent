import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { MarkdownContent } from "./markdown-content";

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(),
}));

vi.mock("mermaid-real", () => ({
  default: mermaidMock,
}));

vi.mock("@/components/ai-elements/message", async () => {
  const React = await import("react");
  return {
    MessageResponse: ({
      children,
      components,
    }: {
      children: string;
      components: {
        pre?: (props: { children?: React.ReactNode }) => React.ReactNode;
      };
    }) => {
      const match = /^```([\w-]+)\n([\s\S]*?)\n?```$/.exec(children.trim());
      if (match && components.pre) {
        const language = match[1] ?? "text";
        const code = match[2] ?? "";
        return React.createElement(
          React.Fragment,
          null,
          components.pre({
            children: React.createElement(
              "code",
              { className: `language-${language}` },
              code,
            ),
          }),
        );
      }
      return React.createElement("div", null, children);
    },
  };
});

function renderMarkdown(content: string, isLoading = false) {
  return renderWithProviders(
    <MarkdownContent
      content={content}
      isLoading={isLoading}
      remarkPlugins={[]}
      rehypePlugins={[]}
    />,
  );
}

describe("<MarkdownContent /> Mermaid", () => {
  beforeEach(() => {
    mermaidMock.initialize.mockReset();
    mermaidMock.render.mockReset();
    mermaidMock.render.mockResolvedValue({
      svg: '<svg role="img"><text>Rendered Mermaid</text></svg>',
    });
  });

  it("keeps Mermaid source visible while the message is streaming", async () => {
    renderMarkdown("```mermaid\ngraph TD\nA-->B\n```", true);

    expect(await screen.findByText("mermaid")).toBeInTheDocument();
    expect(screen.getByText(/graph TD/)).toBeInTheDocument();
    expect(mermaidMock.render).not.toHaveBeenCalled();
  });

  it("renders completed Mermaid fences as SVG", async () => {
    renderMarkdown("```mermaid\ngraph TD\nA-->B\n```");

    await waitFor(() => {
      expect(mermaidMock.render).toHaveBeenCalledWith(
        expect.stringMatching(/^mermaid-chat-/),
        expect.stringContaining("graph TD"),
      );
    });
    expect(await screen.findByText("Rendered Mermaid")).toBeInTheDocument();
  });
});

describe("<MarkdownContent /> Widget", () => {
  it("renders a ```widget fence in a sandboxed null-origin iframe", () => {
    renderMarkdown('```widget\n<div id="x">hi widget</div>\n```');

    const iframe = screen.getByTitle("interactive widget");
    // SECURITY: sandbox must be exactly "allow-scripts" — adding
    // allow-same-origin would let untrusted agent code escape the sandbox.
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    const srcdoc = iframe.getAttribute("srcdoc") ?? "";
    expect(srcdoc).toContain("hi widget");
    expect(srcdoc).not.toContain("allow-same-origin");
  });

  it("treats html-widget as an alias", () => {
    renderMarkdown("```html-widget\n<button>go</button>\n```");

    const iframe = screen.getByTitle("interactive widget");
    expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
    expect(iframe.getAttribute("srcdoc") ?? "").toContain("<button>go</button>");
  });
});
