import { afterEach, describe, expect, test, vi } from "vitest";

import {
  installHashRouterShellUrlNormalizer,
  normalizeHashRouterShellUrl,
  toHashRouterShellUrl,
} from "./hash-shell-url";

describe("hash router shell URL normalization", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.replaceState(null, "", "/");
  });

  test("strips stale pathname when a hash route is active", () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/chats/thread-1#/workspace/store",
    );

    normalizeHashRouterShellUrl();

    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#/workspace/store");
  });

  test("strips stale agent pathname when a hash agent route is active", () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/agents/general/chats/old#/workspace/agents/general/chats/new",
    );

    normalizeHashRouterShellUrl();

    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#/workspace/realtime/new?agent=general");
  });

  test("formats programmatic routes for the hash router shell", () => {
    expect(
      toHashRouterShellUrl("/workspace/agents/local%20codex/chats/abc"),
    ).toBe("/#/workspace/realtime/abc?agent=local+codex");
    expect(toHashRouterShellUrl("/workspace/team?surface=chat")).toBe(
      "/#/workspace/realtime/new?surface=chat",
    );
    expect(toHashRouterShellUrl("/workspace/realtime?agent=general")).toBe(
      "/#/workspace/realtime/new?agent=general",
    );
  });

  test("rewrites direct app path loads into hash routes", () => {
    window.history.replaceState(
      null,
      "",
      "/workspace/realtime/new?agent=general",
    );

    normalizeHashRouterShellUrl();

    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#/workspace/realtime/new?agent=general");
  });

  test("rewrites retired swarm entry into the realtime workspace", () => {
    window.history.replaceState(null, "", "/#/workspace/swarm");

    normalizeHashRouterShellUrl();

    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#/workspace/realtime/new");
  });

  test("rewrites workspace roots into the realtime coding screen", () => {
    window.history.replaceState(null, "", "/#/workspace");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/realtime/new");

    window.history.replaceState(null, "", "/#/workspace/realtime");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/realtime/new");
  });

  test("rewrites retired code entries into realtime threads", () => {
    window.history.replaceState(null, "", "/#/workspace/code/code-thread");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/realtime/code-thread");

    window.history.replaceState(
      null,
      "",
      "/#/workspace/code/code-thread?surface=chat",
    );

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe(
      "#/workspace/realtime/code-thread?surface=chat",
    );

    window.history.replaceState(null, "", "/#/workspace/realtime/rt-thread");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/realtime/rt-thread");
  });

  test("rewrites retired team entries into realtime tasks", () => {
    window.history.replaceState(null, "", "/#/workspace/team/team-thread");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/realtime/team-thread");

    window.history.replaceState(
      null,
      "",
      "/#/workspace/team/team%20thread?surface=chat",
    );

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe(
      "#/workspace/realtime/team%20thread?surface=chat",
    );
  });

  test("keeps team invite links on the join route", () => {
    window.history.replaceState(null, "", "/#/workspace/team/join?token=abc");

    normalizeHashRouterShellUrl();

    expect(window.location.hash).toBe("#/workspace/team/join?token=abc");
  });

  test("patches history writes so pathname routes become hash routes", () => {
    installHashRouterShellUrlNormalizer();
    window.history.replaceState(null, "", "/");
    window.history.pushState(null, "", "/workspace/agents/general/chats/abc");
    expect(window.location.pathname).toBe("/");
    expect(window.location.hash).toBe("#/workspace/realtime/abc?agent=general");
  });

  test("installs a hashchange listener so navigation keeps the URL canonical", () => {
    const spy = vi.spyOn(window, "addEventListener");

    installHashRouterShellUrlNormalizer();

    expect(spy).toHaveBeenCalledWith("hashchange", normalizeHashRouterShellUrl);
  });
});
