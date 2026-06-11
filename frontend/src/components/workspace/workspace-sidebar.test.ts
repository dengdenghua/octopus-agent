import { describe, expect, test } from "vitest";

import { __testing } from "./workspace-sidebar";

describe("workspace sidebar route activation", () => {
  test("leaves primary nav inactive on agent-scoped chat threads", () => {
    const pathname = "/workspace/agents/general/chats/thread-1";

    expect(
      __testing.isNavRouteActive(pathname, "/workspace/realtime/new"),
    ).toBe(false);
    expect(__testing.isNavRouteActive(pathname, "/workspace/agents")).toBe(
      false,
    );
  });

  test("keeps primary chat active only on chat entry routes", () => {
    expect(
      __testing.isNavRouteActive(
        "/workspace/realtime/new",
        "/workspace/realtime/new",
      ),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive(
        "/workspace/agents/general/chats/new",
        "/workspace/realtime/new",
      ),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive(
        "/workspace/realtime/thread-1",
        "/workspace/realtime/new",
      ),
    ).toBe(false);
  });

  test("keeps the people pool active on normal agent routes", () => {
    expect(
      __testing.isNavRouteActive("/workspace/agents", "/workspace/agents"),
    ).toBe(true);
    expect(
      __testing.isNavRouteActive("/workspace/agents/new", "/workspace/agents"),
    ).toBe(true);
  });
});
