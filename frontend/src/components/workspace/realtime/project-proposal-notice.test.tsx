import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { ProjectProposalNotice } from "./project-proposal-notice";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/core/api", () => ({ getAPIClient: () => ({ threads: { get: mocks.get } }) }));

describe("retained project proposal", () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.get.mockResolvedValue({ metadata: { project_initiation: {
      id: "draft-1", status: "approval_expired", proposal: { name: "内部演示" },
    } } });
  });
  it("reopens the exact proposal without approving, and suppresses double click", async () => {
    const review = vi.fn();
    renderWithProviders(<ProjectProposalNotice threadId="test" busy={false} onReview={review} />);
    const button = await screen.findByRole("button", { name: "重新提交审批" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(review).toHaveBeenCalledTimes(1);
    expect(review).toHaveBeenCalledWith("/project review draft-1");
  });
  it("does not offer a competing request while a turn is running", () => {
    renderWithProviders(<ProjectProposalNotice threadId="test" busy onReview={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(mocks.get).not.toHaveBeenCalled();
  });
});
