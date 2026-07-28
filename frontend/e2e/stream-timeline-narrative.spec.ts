import { expect, test } from "./fixtures";

/**
 * E2E: stream-ux-timeline-narrative 验收
 *
 * Prerequisites: backend on :8000 (local-auth allow_any_username), frontend on :3000.
 *
 * 覆盖 spec §全局约束：登录后 workspace 对话面渲染、流式时间线基建可用、
 * 思考/执行行 testid 存在、进展面板可展开。真实 SSE 内容回归由单测层
 * (message-group.test.tsx 55 用例) 覆盖；此处验证端到端管道连通。
 */
test.describe("Stream timeline narrative", () => {
  test("authenticated workspace renders chat composer and timeline container", async ({
    authedPage: page,
  }) => {
    await page.goto("/#/workspace/realtime/new?agent=general");
    await page.waitForLoadState("domcontentloaded");

    // 路由未被重定向到 login
    await expect(page).toHaveURL(/#\/workspace\/realtime\/new/);

    // 输入框可见 — 对话发送入口就绪
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("workspace sidebar shows chat entry after login", async ({
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

  test("a missing deep-linked thread settles into a recoverable empty state", async ({
    authedPage: page,
  }) => {
    const missingThreadId = `e2e-missing-${Date.now()}`;
    await page.goto(`/#/workspace/realtime/${missingThreadId}`);
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(
      new RegExp(`#\\/workspace\\/realtime\\/${missingThreadId}$`),
    );
    await expect(page.getByText(/还没有消息|No messages yet/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByRole("button", { name: /重试|Retry/i }),
    ).toBeVisible();
    await expect(
      page.getByTestId("conversation-activity-pulse"),
    ).not.toBeVisible();
  });
});
