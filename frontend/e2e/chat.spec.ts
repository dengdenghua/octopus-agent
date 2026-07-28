import { expect, test } from "./fixtures";

/**
 * E2E: public shell -> workspace chat surfaces.
 *
 * Prerequisites: backend on :8000, frontend on :3000.
 */

test.describe("Chat golden path", () => {
  test("root shell loads the workspace", async ({ authedPage: page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveTitle(/(?:^|\s-\s)Octopus$/);
    await expect(page.locator('a[aria-label="Octopus"]')).toBeVisible({
      timeout: 10_000,
    });
    await expect(
      page.getByRole("button", { name: "New task", exact: true }),
    ).toBeVisible();
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 10_000,
    });
  });

  test("can load the workspace chat route", async ({ authedPage: page }) => {
    await page.goto("/#/workspace/realtime/new?agent=general");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/#\/workspace\/realtime\/new\?agent=general/);
    await expect(page.locator("textarea").first()).toBeVisible({
      timeout: 15_000,
    });
  });

  test("workspace sidebar shows the chat entry", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/realtime/new");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/#\/workspace\/realtime\/new/);
    await expect(page.getByText("Octopus").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("textarea").first()).toBeVisible();
  });

  test("new chat page has a message input", async ({ authedPage: page }) => {
    await page.goto("/#/workspace/realtime/new");
    await page.waitForLoadState("domcontentloaded");

    const input = page
      .locator(
        "textarea, [contenteditable=true], [role=textbox], input[type=text]",
      )
      .first();
    await expect(input).toBeVisible({ timeout: 15_000 });
  });
});
