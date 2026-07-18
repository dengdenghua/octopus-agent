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
  it("hides leaked read-only control tags but preserves the answer", () => {
    renderMarkdown(
      "<read_only>\n</read_only>\n\nPython 与 TypeScript 定义一致。",
    );

    expect(screen.queryByText(/read_only/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Python 与 TypeScript 定义一致。"),
    ).toBeInTheDocument();
  });

  it("keeps read-only tags when they are shown as a code example", () => {
    renderMarkdown("```xml\n<read_only>\n</read_only>\n```");

    expect(screen.getByText(/<read_only>/)).toBeInTheDocument();
  });

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

  it("toggles from streaming to settled without losing content", () => {
    const content = "Hello world";
    const view = renderMarkdown(content, true);

    expect(screen.getByText(content)).toBeInTheDocument();
    expect(screen.getByText(content)).toHaveAttribute("data-is-animating", "true");

    view.rerender(
      <MarkdownContent
        content={content}
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );

    expect(screen.getByText(content)).toBeInTheDocument();
    expect(screen.getByText(content)).toHaveAttribute("data-is-animating", "false");
    expect(screen.getByText(content)).not.toHaveAttribute("aria-busy");
  });

  it("does not show aria-busy for completed messages", () => {
    renderMarkdown("Done", false);

    const response = screen.getByText("Done");
    expect(response).not.toHaveAttribute("aria-busy");
  });

  it("renders empty content as null", () => {
    const { container } = renderMarkdown("", false);
    expect(container.firstChild).toBeNull();
  });

  it("renders null content as null", () => {
    const { container } = renderWithProviders(
      <MarkdownContent
        content={null as unknown as string}
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("preserves content across streaming chunks (appending tokens)", () => {
    const view = renderMarkdown("Hel", true);
    expect(screen.getByText("Hel")).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="Hello"
        isLoading={true}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="Hello world"
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toHaveAttribute("data-is-animating", "false");
  });
});

describe("<MarkdownContent /> code block streaming", () => {
  it("shows code block content immediately during streaming", () => {
    renderMarkdown("```python\nprint('hello')\n```", true);
    expect(screen.getByText(/print\('hello'\)/)).toBeInTheDocument();
  });

  it("renders code language correctly", () => {
    renderMarkdown("```typescript\nconst x = 1;\n```", false);
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
  });

  it("handles incomplete code fence during streaming", () => {
    renderMarkdown("```javascript\nfunction test() {", true);
    expect(screen.getByText(/function test\(\)/)).toBeInTheDocument();
  });

  it("appends code content across streaming chunks", () => {
    const view = renderMarkdown("```typescript\nconst x = 1;", true);
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="```typescript\nconst x = 1;\nconst y = 2;"
        isLoading={true}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
    expect(screen.getByText(/const y = 2/)).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="```typescript\nconst x = 1;\nconst y = 2;\n```"
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText(/const x = 1/)).toBeInTheDocument();
    expect(screen.getByText(/const y = 2/)).toBeInTheDocument();
  });

  it("preserves code block from streaming to completion without remount flicker", () => {
    const content = "```python\ndef hello():\n    print('world')\n```";
    const view = renderMarkdown(content, true);
    const firstCode = screen.getByText(/print\('world'\)/);
    expect(firstCode).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content={content}
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText(/print\('world'\)/)).toBeInTheDocument();
  });
});

describe("<MarkdownContent /> streaming edge cases", () => {
  it("handles only whitespace content", () => {
    const { container } = renderMarkdown("   \n\n  ", true);
    expect(container.firstChild).not.toBeNull();
    const el = container.querySelector('[data-is-animating="true"]');
    expect(el).toBeInTheDocument();
  });

  it("handles content that grows from empty to full", () => {
    const view = renderMarkdown("", true);
    expect(view.container.firstChild).toBeNull();

    view.rerender(
      <MarkdownContent
        content="Hello"
        isLoading={true}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText("Hello")).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="Hello world"
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText("Hello world")).toBeInTheDocument();
    expect(screen.getByText("Hello world")).toHaveAttribute(
      "data-is-animating",
      "false",
    );
  });

  it("maintains streaming state across multiple rapid updates", () => {
    const view = renderMarkdown("Line 1", true);
    expect(screen.getByText("Line 1")).toHaveAttribute(
      "data-is-animating",
      "true",
    );

    view.rerender(
      <MarkdownContent
        content="Line 1\nLine 2"
        isLoading={true}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText(/Line 1/)).toBeInTheDocument();
    expect(screen.getByText(/Line 2/)).toBeInTheDocument();

    view.rerender(
      <MarkdownContent
        content="Line 1\nLine 2\nLine 3"
        isLoading={true}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    expect(screen.getByText(/Line 3/)).toBeInTheDocument();
    expect(screen.getByText(/Line 3/)).toHaveAttribute(
      "data-is-animating",
      "true",
    );
  });

  it("transitions from streaming aria-busy to settled cleanly", () => {
    const view = renderMarkdown("Loading...", true);
    const el = screen.getByText("Loading...");
    expect(el).toHaveAttribute("aria-busy", "true");

    view.rerender(
      <MarkdownContent
        content="Loading..."
        isLoading={false}
        remarkPlugins={[]}
        rehypePlugins={[]}
      />,
    );
    const settled = screen.getByText("Loading...");
    expect(settled).not.toHaveAttribute("aria-busy");
    expect(settled).toHaveAttribute("data-is-animating", "false");
  });
});
