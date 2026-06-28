import { expect, test } from "@playwright/test";

const backendPort = process.env.GATEWAY_PORT || "8000";
const backendBase = `http://127.0.0.1:${backendPort}`;

test.describe("Full-stack golden smoke", () => {
  test("backend, Vite proxy, and workspace shell are all live", async ({
    page,
    request,
  }) => {
    const directStatus = await request.get(`${backendBase}/api/status`);
    expect(directStatus.ok()).toBeTruthy();
    const directBody = await directStatus.json();
    expect(directBody.version).toBeTruthy();
    expect(directBody.capabilities.fastapi).toBe(true);

    await page.goto("/");
    const proxiedStatus = await page.evaluate(async () => {
      const response = await fetch("/api/status");
      return {
        ok: response.ok,
        status: response.status,
        body: await response.json(),
      };
    });
    expect(proxiedStatus.ok).toBe(true);
    expect(proxiedStatus.body.version).toBe(directBody.version);

    await page.goto("/#/workspace/agents/general/chats/new");
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveURL(/#\/workspace\/agents\/general\/chats\/new/);
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 20_000,
    });

    const agents = await request.get(`${backendBase}/api/agents`);
    expect(agents.ok()).toBeTruthy();
    const agentsBody = await agents.json();
    expect(Array.isArray(agentsBody)).toBe(true);
    expect(
      agentsBody.some((agent: { name?: string }) => agent.name === "general"),
    ).toBe(true);
  });
});
