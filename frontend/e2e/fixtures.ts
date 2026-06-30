import { expect, test as base } from "@playwright/test";

function apiPath(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.pathname.startsWith("/api/") ? parsed.pathname : null;
  } catch {
    return url.startsWith("/api/") ? url : null;
  }
}

function shouldIgnoreRequestFailure(errorText: string): boolean {
  return /net::ERR_ABORTED/i.test(errorText);
}

function shouldIgnoreConsoleError(text: string): boolean {
  if (
    /Failed to load resource: the server responded with a status of 404/i.test(
      text,
    )
  ) {
    return true;
  }
  return /ResizeObserver loop completed with undelivered notifications/i.test(
    text,
  );
}

export const test = base.extend({
  page: async ({ page }, run) => {
    const issues: string[] = [];

    page.on("pageerror", (error) => {
      issues.push(`pageerror: ${error.message}`);
    });

    page.on("console", (message) => {
      if (message.type() !== "error") {
        return;
      }
      const text = message.text();
      if (shouldIgnoreConsoleError(text)) {
        return;
      }
      const location = message.location();
      const where = location.url
        ? `${location.url}:${location.lineNumber}:${location.columnNumber}`
        : "unknown location";
      issues.push(`console error at ${where}: ${text}`);
    });

    page.on("requestfailed", (request) => {
      const path = apiPath(request.url());
      if (!path) {
        return;
      }
      const errorText = request.failure()?.errorText || "unknown failure";
      if (shouldIgnoreRequestFailure(errorText)) {
        return;
      }
      issues.push(`API request failed ${path}: ${errorText}`);
    });

    page.on("response", (response) => {
      const status = response.status();
      if (status < 500) {
        return;
      }
      const path = apiPath(response.url());
      if (!path) {
        return;
      }
      issues.push(`API ${status} response ${path}`);
    });

    await run(page);
    await page.waitForTimeout(100);
    expect(issues, issues.join("\n")).toEqual([]);
  },
});

export { expect };
