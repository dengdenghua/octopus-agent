import { expect, test } from "@playwright/test";

const backendPort = process.env.GATEWAY_PORT || "18000";
const backendBase = `http://127.0.0.1:${backendPort}`;
const frontendPort = process.env.FRONTEND_PORT || "13000";
const frontendOrigins = [
  `http://127.0.0.1:${frontendPort}`,
  `http://localhost:${frontendPort}`,
];

async function fetchFromPage(
  page: import("@playwright/test").Page,
  path: string,
) {
  return page.evaluate(async (requestPath) => {
    const response = await fetch(requestPath);
    return {
      ok: response.ok,
      status: response.status,
      body: await response.json(),
    };
  }, path);
}

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

    const originSnapshots: Array<{
      origin: string;
      status: Record<string, unknown>;
      auth: Record<string, unknown>;
      agentNames: string[];
    }> = [];

    for (const origin of frontendOrigins) {
      const directProxyStatus = await request.get(`${origin}/api/status`);
      expect(directProxyStatus.ok()).toBeTruthy();
      const directProxyBody = await directProxyStatus.json();
      expect(directProxyBody.version).toBe(directBody.version);

      await page.goto(`${origin}/`);
      const proxiedStatus = await fetchFromPage(page, "/api/status");
      expect(proxiedStatus.ok).toBe(true);
      expect(proxiedStatus.body.version).toBe(directBody.version);

      const authStatus = await fetchFromPage(page, "/api/auth/status");
      expect(authStatus.ok).toBe(true);
      expect(typeof authStatus.body.enabled).toBe("boolean");

      const selfCheck = await fetchFromPage(page, "/api/runtime/self-check");
      expect(selfCheck.ok).toBe(true);
      expect(selfCheck.body.frontend).toMatchObject({
        canonical_origin: `http://localhost:${frontendPort}`,
        proxy_target: backendBase,
        proxy_targets_backend: true,
      });

      const agents = await fetchFromPage(page, "/api/agents");
      expect(agents.ok).toBe(true);
      expect(Array.isArray(agents.body)).toBe(true);
      expect(
        agents.body.some(
          (agent: { name?: string }) => agent.name === "general",
        ),
      ).toBe(true);
      originSnapshots.push({
        origin,
        status: proxiedStatus.body,
        auth: authStatus.body,
        agentNames: agents.body
          .map((agent: { name?: string }) => agent.name)
          .filter(Boolean)
          .sort(),
      });
    }
    expect(originSnapshots).toHaveLength(2);
    expect(originSnapshots[1].status).toMatchObject({
      version: originSnapshots[0].status.version,
    });
    expect(originSnapshots[1].auth).toEqual(originSnapshots[0].auth);
    expect(originSnapshots[1].agentNames).toEqual(
      originSnapshots[0].agentNames,
    );

    await page.goto(
      `${frontendOrigins[0]}/#/workspace/agents/general/chats/new`,
    );
    await page.waitForLoadState("domcontentloaded");
    await expect(page).toHaveURL(
      new RegExp(
        `^http://localhost:${frontendPort}/#\\/workspace\\/agents\\/general\\/chats\\/new`,
      ),
    );
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
