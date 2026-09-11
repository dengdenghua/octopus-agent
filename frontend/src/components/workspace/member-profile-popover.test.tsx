import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { MemberProfilePopover } from "./member-profile-popover";

it("keeps the opened profile visible and lets Escape close it", async () => {
  const user = userEvent.setup();
  renderWithProviders(
    <MemberProfilePopover
      trigger={<button>查看成员</button>}
      name="Kane"
      roleLabel="开发"
      presenceLabel="空闲"
      summary="帮助完成开发任务"
    />,
    { locale: "zh-CN" },
  );
  await user.click(screen.getByRole("button", { name: "查看成员" }));
  expect(screen.getByRole("menu", { name: "Kane 的成员信息" })).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看成员" }));
  expect(screen.getByRole("menu")).toBeVisible();
});
