import { expect, test } from "./fixtures";

/**
 * E2E: Workflow Editor.
 *
 * Prerequisites: backend on :8000, frontend on :3000.
 */

test.describe("Workflow Editor", () => {
  test("workflows page shows maintenance state while backend contract is absent", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/workflows");
    await page.waitForLoadState("domcontentloaded");

    await expect(
      page.getByRole("heading", {
        name: /工作流编辑器暂不可用|Workflow editor temporarily unavailable/i,
      }),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("workflow-editor")).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: /新建实时任务|New realtime task/i,
      }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", {
        name: /^(?:查看技能|View skills)$/i,
      }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Run" })).not.toBeVisible();
  });
});
