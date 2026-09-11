import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/harness";
import { AutomationCreateDialog } from "./automation-create-dialog";

afterEach(() => vi.unstubAllGlobals());

it("previews the execution context and sends the displayed timezone with hourly cadence", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const user = userEvent.setup();
  renderWithProviders(
    <AutomationCreateDialog
      open
      onOpenChange={() => {}}
      presetTemplate={{
        id: "test",
        title: "UX 预览",
        topic: "示例主题",
        description: "",
        tags: [],
        cadence: "hourly",
        schedule_time: "09:00",
      }}
    />,
    { locale: "zh-CN" },
  );
  expect(await screen.findByText(/执行时区/)).toHaveTextContent(
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  expect(screen.getByText(/结果保存在/)).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
  const buttons = screen.getAllByRole("button");
  const submit = buttons.find(
    (button) => button.textContent?.trim() === "创建任务",
  );
  expect(submit).toBeDefined();
  await user.click(submit!);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  const body = JSON.parse(fetchMock.mock.calls[0]![1].body);
  expect(body.cadence).toBe("hourly");
  expect(body.timezone).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone);
});

it("does not offer to submit a blank task", () => {
  renderWithProviders(<AutomationCreateDialog open onOpenChange={() => {}} />, {
    locale: "zh-CN",
  });
  expect(
    screen.getByRole("button", { name: "创建任务", exact: true }),
  ).toBeDisabled();
});
