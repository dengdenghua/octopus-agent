import { expect, test, type Page } from "@playwright/test";

const backendPort = process.env.GATEWAY_PORT || "18000";
const backendBase = `http://127.0.0.1:${backendPort}`;
const frontendPort = process.env.FRONTEND_PORT || "13000";
const frontendOrigins = [
  `http://127.0.0.1:${frontendPort}`,
  `http://localhost:${frontendPort}`,
];

async function fetchFromPage(page: Page, path: string) {
  return page.evaluate(async (requestPath) => {
    const response = await fetch(requestPath);
    return {
      ok: response.ok,
      status: response.status,
      body: await response.json(),
    };
  }, path);
}

async function reactFill(page: Page, selector: string, text: string) {
  const el = page.locator(selector).filter({ visible: true }).first();
  await el.waitFor({ state: "visible", timeout: 15_000 });
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

async function waitForThreadState(
  page: Page,
  threadId: string,
  predicate: (state: Record<string, unknown>) => boolean,
) {
  return expect
    .poll(
      async () => {
        const response = await page.request.get(
          `${backendBase}/api/threads/${encodeURIComponent(threadId)}/state`,
        );
        if (!response.ok()) {
          return null;
        }
        const state = (await response.json()) as Record<string, unknown>;
        return predicate(state) ? state : null;
      },
      { intervals: [500, 1000, 1500, 2000], timeout: 30_000 },
    )
    .not.toBeNull();
}

function threadStateMessages(state: Record<string, unknown>): unknown[] {
  const values = state.values;
  if (
    values &&
    typeof values === "object" &&
    Array.isArray((values as { messages?: unknown }).messages)
  ) {
    return (values as { messages: unknown[] }).messages;
  }
  return Array.isArray(state.messages) ? state.messages : [];
}

function extractRealtimeThreadId(url: string): string {
  const match = /#\/workspace\/realtime\/([^/?#]+)/.exec(url);
  if (!match?.[1] || match[1] === "new") {
    throw new Error(`expected realtime thread URL, got ${url}`);
  }
  return decodeURIComponent(match[1]);
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
        `^http://localhost:${frontendPort}/#\\/workspace\\/realtime\\/new\\?agent=general`,
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

  test("realtime new thread sends, persists, and resumes after refresh", async ({
    page,
  }) => {
    const origin = frontendOrigins[0];
    const prompt = `Reply directly with one short sentence: full-stack realtime smoke ${Date.now()}`;

    await page.goto(`${origin}/#/workspace/realtime/new`);
    await page.waitForLoadState("domcontentloaded");
    const chatModeToggle = page.getByTestId("chat-mode-toggle");
    await expect(chatModeToggle).toBeVisible({ timeout: 20_000 });
    if ((await chatModeToggle.getAttribute("aria-pressed")) !== "true") {
      await chatModeToggle.click();
    }
    await expect(chatModeToggle).toHaveAttribute("aria-pressed", "true");

    await reactFill(page, '[data-testid="chat-composer-input"]', prompt);
    await expect(page.getByTestId("chat-send-button")).toBeEnabled({
      timeout: 10_000,
    });
    await page.getByTestId("chat-send-button").click();

    await page.waitForURL(/#\/workspace\/realtime\/(?!new)[^/]+$/, {
      timeout: 20_000,
    });
    const threadId = extractRealtimeThreadId(page.url());

    await waitForThreadState(page, threadId, (state) => {
      const messages = threadStateMessages(state);
      return messages.some((message) =>
        JSON.stringify(message).includes(prompt),
      );
    });

    await waitForThreadState(page, threadId, (state) => {
      const messages = threadStateMessages(state);
      return messages.length >= 2;
    });

    await page.reload();
    await page.waitForLoadState("domcontentloaded");
    await expect(page.getByTestId("chat-composer-input")).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText(prompt, { exact: true })).toBeVisible({
      timeout: 20_000,
    });
  });
});
