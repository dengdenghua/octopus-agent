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
  type MockMessageResponseProps = {
    children: string;
    components: {
      pre?: (props: { children?: React.ReactNode }) => React.ReactNode;
    };
    isAnimating?: boolean;
    "aria-busy"?: boolean;
  };
  const MessageResponse = React.memo(
    ({
      children,
      components,
      isAnimating,
      "aria-busy": ariaBusy,
    }: MockMessageResponseProps) => {
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
      return React.createElement(
        "div",
        {
          "aria-busy": ariaBusy,
          "data-is-animating": isAnimating ? "true" : "false",
        },
        children,
      );
    },
    // Streamdown memoizes parsed blocks by content. This reproduces the
    // completion edge where only the streaming state changes.
    (previous, next) => previous.children === next.children,
  );
  return {
    MessageResponse,
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

  it("remounts stable blocks once so streaming visuals can settle", async () => {
    const content = "```mermaid\ngraph TD\nA-->B\n```";
    const view = renderMarkdown(content, true);

    expect(await screen.findByText("mermaid")).toBeInTheDocument();
    expect(mermaidMock.render).not.toHaveBeenCalled();

    view.rerender(
      <MarkdownContent
        content={content}
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );

    await waitFor(() => {
      expect(mermaidMock.render).toHaveBeenCalledWith(
        expect.stringMatching(/^mermaid-chat-/),
        expect.stringContaining("graph TD"),
      );
    });
    expect(await screen.findByText("Rendered Mermaid")).toBeInTheDocument();
  });
});

describe("<MarkdownContent /> streaming state", () => {
  it("keeps markdown controls and assistive technology in the streaming state", () => {
    renderMarkdown("Answer in progress", true);

    const response = screen.getByText("Answer in progress");
    expect(response).toHaveAttribute("data-is-animating", "true");
    expect(response).toHaveAttribute("aria-busy", "true");
  });

  it("settles the markdown renderer when streaming completes", () => {
    renderMarkdown("Final answer");

    const response = screen.getByText("Final answer");
    expect(response).toHaveAttribute("data-is-animating", "false");
    expect(response).not.toHaveAttribute("aria-busy");
  });
});
