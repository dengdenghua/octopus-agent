/**
 * Smoke tests for workspace panels that used to be easy to orphan:
 *
 *   - /workspace/intelligence -> <intelligence-panel.tsx>
 *   - agent collaboration status -> <swarm-panel.tsx>
 *   - /workspace/knowledge    -> <knowledge-graph-panel.tsx>
 *
 * What we verify
 * --------------
 *
 * 1. Each panel mounts without throwing (catches Rules-of-Hooks
 *    violations like the one in ``SwarmPanel`` where ``useMemo`` was
 *    called after an ``if (loading) return`` · that bug was silent
 *    under ``tsc`` + all the other tests · the only way to catch
 *    it is to actually render).
 * 2. After the loading indicator resolves, the empty-state content
 *    we added this sprint is visible.
 * 3. Console error count stays at zero · React surfaces hook-order
 *    mismatches as ``console.error`` · this assertion is the
 *    tripwire for silent regressions.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

// ArenaPanel uses useI18n heavily (``t.arena.title`` / ``t.arena.prompt``
// etc.). Build a stub ``t`` where the top level is a plain object
// (no render-a-Proxy-as-child hazard) · each top-level key is itself
// a Proxy that returns its own property NAME as a string on any read ·
// so ``t.arena.XYZ`` JSX just shows "XYZ" instead of throwing.
vi.mock("@/core/i18n/hooks", () => {
  const overrides: Record<string, Record<string, unknown>> = {
    swarmPanel: {
      noSwarmTasksTitle: "暂无并行任务",
      noSwarmTasksHint: "需要并行协作时会显示实时状态",
      statTotal: "总任务",
    },
    knowledgeGraph: {
      emptyStateTitle: "知识图谱为空",
      emptyStateHint: "KG 尚未抽取出实体",
    },
    intelligence: {
      noSubscriptionsHint: (keywordExample: string) =>
        `还没有情报订阅 · ${keywordExample}`,
      exampleKeyword: "多 agent 编排",
      lastRunPrefix: (value: string) => `上次运行 ${value}`,
      itemsCount: (count: number) => `${count} 条`,
      reportGenerated: (count: number) => `${count} 条情报已生成`,
      reportsGenerated: (count: number) => `${count} 份报告已生成`,
    },
    intelligencePanel: {
      examplePrompts: [
        "每天跟踪 Octopus Agent 相关 GitHub release、issue 和竞品动态",
        "每周汇总 AI Agent、浏览器自动化、多智能体框架的新论文",
      ],
      goalPlaceholder: "描述你想持续追踪的情报目标",
      noSubscriptionsYet: "还没有自动订阅",
      scheduleHighFrequency: (timezone: string) => `高频检查 · ${timezone}`,
      scheduleWeekly: (weekday: string, time: string, timezone: string) =>
        `每周 ${weekday} ${time} · ${timezone}`,
      scheduleMonthly: (day: string, time: string, timezone: string) =>
        `每月 ${day} 号 ${time} · ${timezone}`,
      scheduleDaily: (time: string, timezone: string) =>
        `每天 ${time} · ${timezone}`,
      itemsCount: (count: number) => `${count} 条情报`,
      skillsCount: (count: number) => `${count} 个能力`,
      expectedRun: (schedule: string) => `预计执行：${schedule}`,
      monthDayLabel: (day: string) => `${day} 号`,
    },
  };
  const makeLeaf = (section: string) =>
    new Proxy({} as Record<string, unknown>, {
      get(_t, prop) {
        if (typeof prop !== "string") return "";
        if (prop === "then") return undefined; // avoid thenable
        if (prop in (overrides[section] ?? {})) {
          return overrides[section][prop];
        }
        return prop;
      },
    });
  const tStub = new Proxy({} as Record<string, unknown>, {
    get(_t, prop) {
      if (typeof prop !== "string") return makeLeaf("");
      return makeLeaf(prop);
    },
  });
  return {
    useI18n: () => ({
      t: tStub,
      locale: "zh",
      setLocale: () => Promise.resolve(),
    }),
  };
});

vi.mock("./messages/markdown-content", () => ({
  MarkdownContent: ({
    content,
    className,
  }: {
    content: string;
    className?: string;
  }) => <div className={className}>{content}</div>,
}));

import { ArenaPanel } from "./arena-panel";
import EvolutionDashboard from "./evolution-dashboard";
import { IntelligencePanel } from "./intelligence-panel";
import { KnowledgeGraphPanel } from "./knowledge-graph-panel";
import { SwarmPanel } from "./swarm-panel";
import { WikiPanel } from "./wiki-panel";

// ─── Global fetch stub ───────────────────────────────────────────
//
// Each panel hits one or more /api/* endpoints on mount. We stub
// with empty/idle payloads so the loading indicator resolves fast
// and the empty-state branches get exercised.
const JSON_RESPONSES: Record<string, unknown> = {
  "/api/swarm/status": { status: "idle", tasks: [] },
  "/api/intelligence/subscriptions": { subscriptions: [] },
  "/api/intelligence/reports": { reports: [] },
  "/api/knowledge/graph": { entities: [], relationships: [] },
  "/api/knowledge/stats": {
    total_entities: 0,
    total_relationships: 0,
    entity_types: {},
  },
  "/api/arena/leaderboard": { entries: [] },
  "/api/arena/battles": { battle_id: "b-stub", prompt: "", responses: [] },
  "/api/arena/vote": { winner_model: "", loser_model: "", elo_change: 0 },
  // Evolution dashboard hits these in parallel on mount. Stub every
  // endpoint with a minimal empty-but-structured payload so the
  // panel's fallback rendering paths all get exercised.
  "/api/evolution/overview": {
    skills: {
      total: 0,
      auto_extracted: 0,
      manual: 0,
      avg_success_rate: 0,
    },
    memory: {
      total_facts: 0,
      categories: {},
    },
    knowledge_graph: {
      entities: 0,
      relationships: 0,
      communities: 0,
    },
    learning_events: 0,
    improvement_score: 0,
    proactive_learning: 0,
  },
  "/api/evolution/skills/history": [],
  "/api/evolution/skills/performance": [],
  "/api/evolution/memory/growth": [],
  "/api/evolution/learning-curve": [],
  "/api/evolution/recommendations": [],
  // WikiPanel · pristine workspace (no wiki generated, no legacy
  // docs present at workDir). 8 parallel fs-read calls for legacy
  // candidates (CLAUDE.md / README.md / ...) resolve to empty
  // content · status returns "not generated" so the panel lands
  // on its "Generate Wiki" CTA branch.
  "/api/wiki/status": {
    exists: false,
    status: "not_generated",
    languages: [],
    generated_files: [],
    changes_pending: null,
  },
  "/api/wiki/docs": { docs: [] },
  "/api/fs/read": { content: "", binary: false },
};

function pickFixture(url: string): unknown {
  for (const key of Object.keys(JSON_RESPONSES)) {
    if (url.includes(key)) return JSON_RESPONSES[key];
  }
  return {};
}

let consoleErrorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : String(input);
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => pickFixture(url),
      });
    }),
  );
});

afterEach(() => {
  JSON_RESPONSES["/api/intelligence/subscriptions"] = { subscriptions: [] };
  JSON_RESPONSES["/api/intelligence/reports"] = { reports: [] };
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function withProviders(node: React.ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

describe("SwarmPanel", () => {
  it("mounts without throwing (hook-order regression guard)", async () => {
    render(withProviders(<SwarmPanel />));
    await waitFor(() => {
      // Either the empty state OR the stats grid rendered · both
      // are proof the post-loading code path ran without the
      // "Rendered more hooks than during the previous render" crash.
      expect(
        screen.queryByText(/暂无并行任务/) ?? screen.queryByText(/总任务/),
      ).toBeTruthy();
    });
    // React prints hook-order mismatches to console.error · assert
    // we saw none.
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});

describe("KnowledgeGraphPanel", () => {
  it("renders empty-state content when KG is empty", async () => {
    render(withProviders(<KnowledgeGraphPanel />));
    await waitFor(() => {
      expect(screen.getByText(/知识图谱为空/)).toBeInTheDocument();
    });
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});

describe("IntelligencePanel", () => {
  it("renders empty subscription prompt when no subs configured", async () => {
    render(withProviders(<IntelligencePanel />));
    await waitFor(() => {
      expect(screen.getByText(/还没有情报订阅/)).toBeInTheDocument();
    });
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("renders report cards and opens the selected report as an article", async () => {
    const user = userEvent.setup();
    JSON_RESPONSES["/api/intelligence/subscriptions"] = {
      subscriptions: [
        {
          id: "sub-browser",
          topic: "browser-automation",
          display_name: "浏览器自动化",
          keywords: ["browser", "regression"],
          enabled: true,
          cadence: "daily",
          last_run: "2026-05-27T08:00:00Z",
        },
      ],
    };
    JSON_RESPONSES["/api/intelligence/reports"] = {
      reports: [
        {
          id: "report-old",
          topic: "legacy",
          title: "旧周报",
          summary: "旧报告摘要",
          markdown: "## 旧结论\n旧内容",
          created_at: "2026-05-26T08:00:00Z",
        },
        {
          id: "report-browser",
          topic: "browser-automation",
          title: "AI 浏览器自动化周报",
          summary: "验证浏览器回归测试交互是否更自然。",
          markdown:
            "## 核心结论\n浏览器回归应放在预览面板内，报告详情像文章一样阅读。",
          created_at: "2026-05-27T08:00:00Z",
          items_analyzed: 3,
          findings: ["预览内开关比顶栏按钮更轻量"],
          items: [
            {
              id: "source-1",
              title: "UI regression note",
              url: "https://example.com/ui-regression",
              source: "web",
              snippet: "把回归测试放进预览区，减少主工作台噪音。",
            },
          ],
        },
      ],
    };

    render(withProviders(<IntelligencePanel />));

    await waitFor(() => {
      expect(screen.getAllByText("旧周报").length).toBeGreaterThan(0);
      expect(screen.getByText("AI 浏览器自动化周报")).toBeInTheDocument();
    });
    expect(screen.getByText(/旧内容/)).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /AI 浏览器自动化周报/ }),
    );

    await waitFor(() => {
      expect(
        screen.getByText(
          /浏览器回归应放在预览面板内，报告详情像文章一样阅读。/,
        ),
      ).toBeInTheDocument();
    });
    expect(screen.getByText("预览内开关比顶栏按钮更轻量")).toBeInTheDocument();
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});

describe("ArenaPanel", () => {
  it("mounts in idle phase without throwing (hook-order regression guard)", async () => {
    render(withProviders(<ArenaPanel />));
    // Idle phase renders the prompt form first · the battle flow
    // only starts after user submits · so we don't wait for any
    // specific text, just for the next microtask to drain so any
    // fetch-on-mount has had a chance to blow up.
    await waitFor(() => {
      // ArenaPanel has NO fetch-on-mount in idle phase · so the
      // mount itself is the assertion. Just confirm React didn't
      // emit any error during the sync render + microtask flush.
      expect(consoleErrorSpy).not.toHaveBeenCalled();
    });
  });
});

describe("EvolutionDashboard", () => {
  it("mounts + fetches in parallel without hook-order or render errors", async () => {
    render(withProviders(<EvolutionDashboard />));
    // Six parallel fetches on mount via Promise.allSettled · by the
    // time that resolves, the loading branch has flipped off and the
    // main render path has run. Wait for the loading spinner to
    // disappear (overview is still null so OverviewCards won't render
    // content, but the outer shell does).
    await waitFor(() => {
      // Dashboard title renders in the main non-loading branch ·
      // its presence confirms we got past the loading early return.
      // Use Proxy-stubbed t so the actual text is "title".
      expect(
        screen.queryByText("title") ?? screen.queryByText(/loading/i),
      ).toBeTruthy();
    });
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});

describe("WikiPanel", () => {
  it("mounts and clears loading without render errors", async () => {
    // WikiPanel does a lot on mount: /api/wiki/status + /api/wiki/docs
    // + 8 parallel /api/fs/read calls for LEGACY_CANDIDATES. All stubs
    // above resolve fast · the panel should land on a non-loading
    // branch (either generate-wiki CTA when no docs exist, or the
    // content shell when legacyDocs populated).
    render(withProviders(<WikiPanel workDir="/tmp/mock-project" />));
    await waitFor(() => {
      // Loading path renders ``t.wiki.loadingWiki`` ("loadingWiki"
      // under our i18n Proxy). Once the 10 parallel fetches settle,
      // the loading branch should give way to either "noWikiYet" /
      // "generateWiki" / the docs shell ("repoWiki" / "docs"). Any
      // of these indicates successful mount; we just assert we're
      // out of the loading spinner.
      const loading = screen.queryByText("loadingWiki");
      expect(loading).toBeNull();
    });
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });
});
