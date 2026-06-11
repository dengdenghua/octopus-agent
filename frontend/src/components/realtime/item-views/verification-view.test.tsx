import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { VerificationItem } from "@/core/realtime";
import { renderWithProviders } from "@/test/harness";

import { VerificationView } from "./verification-view";

describe("VerificationView", () => {
  it("renders status, related files, and related change count", () => {
    const item: VerificationItem = {
      id: "verification-1",
      type: "verification",
      status: "failed",
      createdAt: "2026-05-31T00:00:00.000Z",
      command: "python -m pytest tests",
      kind: "test",
      exitCode: 1,
      summary: "tests failed",
      stdoutTail: "1 failed",
      stderrTail: null,
      relatedFiles: ["src/app.ts", "src/utils.ts"],
      relatedChangeItemIds: ["file-change-1"],
    };

    renderWithProviders(<VerificationView item={item} />, { locale: "en-US" });

    expect(screen.getByText("Verification")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("exit 1")).toBeInTheDocument();
    expect(screen.getByText("2 related files")).toBeInTheDocument();
    expect(screen.getByText("1 related change")).toBeInTheDocument();
    expect(screen.getByText("tests failed")).toBeInTheDocument();
    expect(screen.getByText("src/app.ts")).toBeInTheDocument();
    expect(screen.getByText("src/utils.ts")).toBeInTheDocument();
  });
});
