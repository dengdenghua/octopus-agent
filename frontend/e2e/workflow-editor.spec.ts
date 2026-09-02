import { expect, test } from "./fixtures";

/**
 * E2E: Workflow Editor.
 *
 * Prerequisites: backend on :8000, frontend on :3000.
 */

test.describe("Legacy workflow route", () => {
  test("workflows route redirects to Hub skills", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/workflows");
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveURL(
      /#\/workspace\/agents\?surface=chat&tab=skills/,
    );
    await expect(
      page.getByPlaceholder(
        /搜索角色、应用或 Skills|Search roles, apps or Skills/i,
      ),
    ).toBeVisible();
  });
});
