import { expect, test, type Locator, type Page } from "@playwright/test";

async function expectNoHorizontalOverflow(
  page: Page,
  locator: Locator,
  label: string,
) {
  const overflow = await locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      left: rect.left,
      right: rect.right,
      viewportWidth: window.innerWidth,
      bodyScrollWidth: document.documentElement.scrollWidth,
    };
  });

  expect(
    overflow.left,
    `${label} should not overflow left`,
  ).toBeGreaterThanOrEqual(-1);
  expect(
    overflow.right,
    `${label} should not overflow right`,
  ).toBeLessThanOrEqual(overflow.viewportWidth + 1);
  expect(
    overflow.bodyScrollWidth,
    `${label} should not create page-level horizontal scroll`,
  ).toBeLessThanOrEqual(overflow.viewportWidth + 1);
}

test.describe("Mobile workspace smoke", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("Team composer and workbench tabs fit mobile width", async ({
    page,
  }) => {
    await page.goto("/#/workspace/team/new");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForURL(/#\/workspace\/team\/[^/]+$/, {
      timeout: 15_000,
    });

    const composer = page.getByTestId("team-composer");
    await expect(composer).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("team-composer-input")).toBeVisible();
    await expectNoHorizontalOverflow(page, composer, "team composer");

    await page.getByTestId("team-workbench-toggle").click();
    const workbench = page.getByTestId("team-workbench-panel");
    await expect(workbench).toBeVisible();
    await expectNoHorizontalOverflow(page, workbench, "team workbench drawer");
  });

  test("Agents category chips scroll within the viewport", async ({ page }) => {
    await page.goto("/#/workspace/agents");
    await page.waitForLoadState("domcontentloaded");

    const search = page.getByTestId("agents-search-input");
    await expect(search).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("agents-loading-skeleton")).toBeHidden({
      timeout: 20_000,
    });
    const chips = page.getByTestId("agents-category-scroll");
    await expect(chips).toBeVisible();
    await expectNoHorizontalOverflow(page, chips, "agents category chips");
  });

  test("Skills list and search fit mobile width", async ({ page }) => {
    await page.goto("/#/workspace/skills");
    await page.waitForLoadState("domcontentloaded");

    const search = page.getByTestId("skills-search-input");
    await expect(search).toBeVisible({ timeout: 15_000 });
    const list = page.getByTestId("skills-category-list");
    await expect(list).toBeVisible();
    await expectNoHorizontalOverflow(page, search, "skills search");
  });
});
