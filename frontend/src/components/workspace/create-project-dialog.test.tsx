import { useState } from "react";
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/harness";

const mocks = vi.hoisted(() => ({
  createProject: vi.fn(),
}));

vi.mock("@/core/projects/hooks", () => ({
  useCreateProject: () => ({
    mutate: mocks.createProject,
    isPending: false,
  }),
}));

import { CreateProjectDialog } from "./create-project-dialog";

function DialogHarness() {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        reopen
      </button>
      <CreateProjectDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

describe("CreateProjectDialog", () => {
  it("clears an abandoned draft before the dialog is reopened", async () => {
    const user = userEvent.setup();
    renderWithProviders(<DialogHarness />, { locale: "zh-CN" });

    const name = screen.getByPlaceholderText("项目名称");
    await user.type(name, "不会创建的项目");
    await user.click(screen.getByRole("button", { name: "取消" }));
    await user.click(screen.getByRole("button", { name: "reopen" }));

    expect(screen.getByPlaceholderText("项目名称")).toHaveValue("");
  });

  it("does not submit an empty project from the Enter key", () => {
    renderWithProviders(<CreateProjectDialog open onOpenChange={vi.fn()} />, {
      locale: "zh-CN",
    });

    fireEvent.keyDown(screen.getByPlaceholderText("项目名称"), {
      key: "Enter",
    });

    expect(mocks.createProject).not.toHaveBeenCalled();
  });
});
