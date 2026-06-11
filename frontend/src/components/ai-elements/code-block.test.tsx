import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/harness";

import { CodeBlock, CodeBlockCopyButton } from "./code-block";

describe("CodeBlockCopyButton", () => {
  it("does not show copy actions while the code block is still streaming", () => {
    const { container } = renderWithProviders(
      <CodeBlock code={'console.log("half")'} language="ts" isStreaming>
        <CodeBlockCopyButton />
      </CodeBlock>,
    );

    expect(screen.getByText("ts")).toBeInTheDocument();
    expect(container.querySelector("button")).toBeNull();
  });

  it("shows copy actions once the code block is complete", () => {
    const { container } = renderWithProviders(
      <CodeBlock code={'console.log("done")'} language="ts">
        <CodeBlockCopyButton />
      </CodeBlock>,
    );

    expect(container.querySelector("button")).not.toBeNull();
  });
});
