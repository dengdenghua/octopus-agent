import { type APIRequestContext, type Page } from "@playwright/test";
import { expect, test } from "./fixtures";

/**
 * E2E regression lockdown · 2026-04-24
 *
 * Every spec here pins a real bug that was found by the manual
 * browser-tour regression pass and fixed. If one of these goes red
 * in CI, a past bug came back.
 *
 * The default full-stack Playwright config starts both the backend and
 * frontend on isolated test ports. Real-model checks stay opt-in so the local
 * production gate remains deterministic and offline.
 *
 * Bug index:
 *   #1 · Intelligence subscriptions use the real router and clean up test data
 *   #2 · Cost tab always 0 tokens · direct_llm path didn't emit budget_commit
 *   #5 · <Header> async Client Component warning (RSC code in SPA)
 *   #6 · Team invite page leaked hard-coded Chinese in en-US locale
 *   workflow-as-skill · workflow editor contract is intentionally gated off
 */

const backendHost = process.env.GATEWAY_HOST || "127.0.0.1";
const backendPort = process.env.GATEWAY_PORT || "18000";
const BACKEND = `http://${backendHost}:${backendPort}`;
// ═══════════════════════════════════════════════════════════
// Helpers
// ═══════════════════════════════════════════════════════════

/**
 * React-controlled inputs in this app don't always pick up
 * Playwright's ``fill()`` event sequence · the chat composer and
 * intel topic box both re-render from state so a value set via the
 * DOM alone leaves React thinking the field is still empty (send
 * button stays disabled, add handler sees "").
 *
 * Fix matches what the hand-rolled JS shim did during the manual
 * browser-regression pass: grab the native ``value`` setter off
 * ``HTMLTextAreaElement.prototype`` / ``HTMLInputElement.prototype``
 * and dispatch an ``input`` event so React's onChange fires.
 */
async function reactFill(
  page: Page,
  selector: string,
  text: string,
): Promise<void> {
  const el = page.locator(selector).filter({ visible: true }).first();
  await el.waitFor({ state: "visible", timeout: 10_000 });
  await el.evaluate((node: Element, value: string) => {
    const proto =
      node instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    if (!setter) throw new Error("no native value setter");
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  }, text);
}

async function deleteSubscriptionsByTopic(
  request: APIRequestContext,
  topic: string,
): Promise<void> {
  const listed = await request.get(`${BACKEND}/api/intelligence/subscriptions`);
  if (!listed.ok()) return;
  const body = await listed.json();
  const subscriptions = body.subscriptions ?? [];
  await Promise.all(
    subscriptions
      .filter((item: { topic?: string }) => item.topic === topic)
      .map((item: { id: string }) =>
        request.delete(
          `${BACKEND}/api/intelligence/subscriptions/${encodeURIComponent(item.id)}`,
        ),
      ),
  );
}

// ═══════════════════════════════════════════════════════════
// Bug #2 · Cost tab was always 0 tokens
// ═══════════════════════════════════════════════════════════

test.describe("Bug#2 regression · Cost tab reflects real chat cost", () => {
  test("offline probe run writes non-zero budget summary", async ({
    request,
  }) => {
    const before = await request.get(`${BACKEND}/api/budget/summary?limit=5`);
    expect(before.ok()).toBeTruthy();
    const beforeBody = await before.json();
    const beforeCommits = Number(beforeBody.commit_count ?? 0);
    const beforeTokens = Number(beforeBody.total_tokens ?? 0);

    const run = await request.post(`${BACKEND}/api/run`, {
      data: { goal: `offline budget probe ${Date.now()}` },
    });
    expect(run.ok()).toBeTruthy();
    const runBody = await run.json();
    expect(runBody.success).toBeTruthy();
    expect(Number(runBody.tokens_spent ?? 0)).toBeGreaterThan(0);

    const after = await request.get(`${BACKEND}/api/budget/summary?limit=5`);
    expect(after.ok()).toBeTruthy();
    const afterBody = await after.json();
    expect(Number(afterBody.commit_count ?? 0)).toBeGreaterThan(beforeCommits);
    expect(Number(afterBody.total_tokens ?? 0)).toBeGreaterThan(beforeTokens);
    expect(
      afterBody.tasks.some(
        (task: { tokens?: number; commit_count?: number }) =>
          Number(task.tokens ?? 0) > 0 && Number(task.commit_count ?? 0) > 0,
      ),
    ).toBeTruthy();
  });

  test("observability cost surface renders non-zero budget data", async ({
    page,
  }) => {
    const run = await page.request.post(`${BACKEND}/api/run`, {
      data: { goal: `cost surface probe ${Date.now()}` },
    });
    expect(run.ok()).toBeTruthy();

    await page.goto("/#/workspace/observability");
    await page.waitForLoadState("domcontentloaded");
    await page.getByRole("tab", { name: "Resources and cost" }).click();

    const tokenValue = page
      .getByTestId("cost-total-tokens")
      .locator("div")
      .last();
    const commitValue = page
      .getByTestId("cost-commit-count")
      .locator("div")
      .last();
    await expect
      .poll(async () =>
        Number((await tokenValue.textContent())?.replaceAll(",", "")),
      )
      .toBeGreaterThan(0);
    await expect
      .poll(async () =>
        Number((await commitValue.textContent())?.replaceAll(",", "")),
      )
      .toBeGreaterThan(0);

    const shellText = await page.locator("main section").first().innerText();
    expect(shellText).not.toMatch(/[\u4e00-\u9fff]/);
    await page.getByRole("tab", { name: "System" }).click();
    const receipts = page
      .getByText("External action receipts", { exact: true })
      .first()
      .locator("xpath=ancestor::*[@data-slot='card'][1]");
    await expect(receipts).toBeVisible();
    expect(await receipts.innerText()).not.toMatch(/[\u4e00-\u9fff]/);
  });
});

// ═══════════════════════════════════════════════════════════
// workflow-as-skill · UI save registers skill
// ═══════════════════════════════════════════════════════════

test.describe("workflow-as-skill · legacy route", () => {
  test("workspace workflow route redirects to the Hub skills tab", async ({
    page,
  }) => {
    await page.goto("/#/workspace/workflows");
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveURL(
      /#\/workspace\/agents\?surface=chat&tab=skills/,
    );
    await expect(page.getByRole("tab", { name: "Skills" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await expect(page.getByRole("textbox").first()).toBeVisible();
  });
});

// ═══════════════════════════════════════════════════════════
// Bug #1 · Intelligence subscriptions are real and self-cleaning
// ═══════════════════════════════════════════════════════════

test.describe("Bug#1 regression · Intelligence subscriptions", () => {
  test("POST creates a real subscription and deletes the E2E record", async ({
    request,
  }) => {
    const topic = `e2e-api-${Date.now()}`;
    try {
      const resp = await request.post(
        `${BACKEND}/api/intelligence/subscriptions`,
        {
          data: {
            topic,
            display_name: topic,
            keywords: ["e2e", "cleanup"],
            cadence: "daily",
            sources: ["web", "news"],
          },
        },
      );
      expect(resp.ok()).toBeTruthy();
      const body = await resp.json();
      expect(body._stub).not.toBe(true);
      expect(body.topic).toBe(topic);
      expect(body.id).toMatch(/^sub_/);

      const listed = await request.get(
        `${BACKEND}/api/intelligence/subscriptions`,
      );
      expect(listed.ok()).toBeTruthy();
      const listedBody = await listed.json();
      expect(
        (listedBody.subscriptions ?? []).some(
          (item: { topic?: string }) => item.topic === topic,
        ),
      ).toBe(true);
    } finally {
      await deleteSubscriptionsByTopic(request, topic);
    }
  });

  test("UI exposes the subscription draft or an explicit app-install gate", async ({
    page,
  }) => {
    const topic = `e2e-ui-${Date.now()}`;
    await page.goto("/#/workspace/intelligence");
    await page.waitForLoadState("domcontentloaded");

    try {
      const unavailable = page.getByText(
        /订阅暂时不可用|Subscriptions? (?:is|are) temporarily unavailable/i,
      );
      const draftInput = page
        .locator("textarea")
        .filter({ visible: true })
        .first();
      await expect(unavailable.or(draftInput)).toBeVisible({ timeout: 10_000 });
      if (await unavailable.isVisible()) {
        await expect(
          page.getByRole("button", { name: /前往应用中心|Go to App Center/i }),
        ).toBeVisible();
        await expect(
          page.getByRole("button", { name: /重新检查|Check again/i }),
        ).toBeVisible();
        return;
      }
      await reactFill(
        page,
        "textarea",
        `Create a temporary subscription named ${topic} for E2E cleanup verification.`,
      );
      await page
        .getByRole("button", { name: /生成订阅草案|Generate Draft/ })
        .click();

      const createButton = page.getByRole("button", {
        name: /创建这个订阅|Create Subscription/,
      });
      await expect(createButton).toBeVisible({ timeout: 10_000 });
      await reactFill(page, "input", topic);
      await createButton.click();

      await expect(
        page.getByText(/订阅添加成功|Subscription added/i),
      ).toBeVisible({ timeout: 5000 });

      const listed = await page.request.get(
        `${BACKEND}/api/intelligence/subscriptions`,
      );
      expect(listed.ok()).toBeTruthy();
      const listedBody = await listed.json();
      expect(
        (listedBody.subscriptions ?? []).some(
          (item: { topic?: string }) => item.topic === topic,
        ),
      ).toBe(true);
    } finally {
      await deleteSubscriptionsByTopic(page.request, topic);
    }
  });
});

// ═══════════════════════════════════════════════════════════
// Bug #6 · Team join page respects active locale
// ═══════════════════════════════════════════════════════════

test.describe("Bug#6 regression · Team join page i18n", () => {
  test("en-US invite error state does not leak hard-coded Chinese", async ({
    page,
  }) => {
    await page.goto("/#/workspace/team/join");
    await page.evaluate(() => {
      document.cookie = "locale=en-US; path=/; SameSite=Lax";
      document.documentElement.lang = "en";
    });
    await page.reload();
    await page.waitForLoadState("domcontentloaded");

    const heading = page.getByRole("heading", {
      name: "Join collaborative task",
    });
    await expect(heading).toBeVisible();
    await expect(
      page.getByText("The invite link is missing a token."),
    ).toBeVisible();

    const visibleText = await page
      .getByRole("heading", { name: "Join collaborative task" })
      .locator("xpath=ancestor::div[contains(@class, 'max-w-md')][1]")
      .innerText();
    expect(visibleText).not.toMatch(/[\u4e00-\u9fff]/);
  });
});

// ═══════════════════════════════════════════════════════════
// Bug #5 · /about no "async Client Component" warning
// ═══════════════════════════════════════════════════════════

test.describe("Bug#5 regression · /about free of async-RSC warnings", () => {
  test("console has no 'async Client Component' warning", async ({ page }) => {
    const warnings: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "warning" || msg.type() === "error") {
        warnings.push(msg.text());
      }
    });
    page.on("pageerror", (err) => warnings.push(err.message));

    await page.goto("/#/about");
    await page.waitForLoadState("networkidle");
    // Give React warnings a beat to surface during hydration
    await page.waitForTimeout(1500);

    const asyncWarnings = warnings.filter((w) =>
      /async Client Component|is an async Client/.test(w),
    );
    expect(asyncWarnings, asyncWarnings.join("\n\n")).toEqual([]);
  });
});
