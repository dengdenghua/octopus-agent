import { expect, test } from "./fixtures";

/**
 * Visual regression: pixel-level baselines for the key workspace surfaces.
 *
 * This complements the DOM-behaviour tests (message-group / message-list
 * suites) by catching style drift that assertions cannot: accent colours,
 * pill badges, three-tier network cards, layout shifts.
 *
 * Baselines are committed under this spec's `-snapshots/` directory. To
 * refresh them after an intentional design change:
 *   npx playwright test visual-regression --update-snapshots
 *
 * Only chromium runs these: cross-browser font rasterisation produces
 * meaningless diffs; a stable platform baseline is what we want.
 */
test.skip(
  ({ browserName }) => browserName !== "chromium",
  "视觉回归仅 chromium:跨浏览器字体渲染差异会产生无意义 diff",
);

test.describe("Visual regression · workspace surfaces", () => {
  test("chat composer surface (new realtime thread)", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/realtime/new?agent=general");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/#\/workspace\/realtime\/new/);
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 15_000,
    });
    // Wait a beat for layout/theme to settle before freezing the frame.
    await expect
      .poll(async () => {
        const box = await page.getByTestId("chat-composer-input").boundingBox();
        return box?.y;
      }, { timeout: 5_000 })
      .toBeDefined();

    await expect(page).toHaveScreenshot("chat-composer.png", {
      maxDiffPixelRatio: 0.02,
      animations: "disabled",
    });
  });

  test("missing deep-linked thread settles into recoverable empty state", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/realtime/does-not-exist-thread");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 15_000,
    });

    await expect(page).toHaveScreenshot("recoverable-empty-state.png", {
      maxDiffPixelRatio: 0.02,
      animations: "disabled",
    });
  });

  test("workspace shell with sidebar navigation", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/realtime/new");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByText("Octopus").first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.locator("textarea").first()).toBeVisible();

    await expect(page).toHaveScreenshot("workspace-shell.png", {
      maxDiffPixelRatio: 0.02,
      animations: "disabled",
    });
  });
});
