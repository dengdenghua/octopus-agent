import { describe, expect, it } from "vitest";

import {
  type PortfolioEntry,
  buildTodayQueue,
  countHealth,
  dayKey,
  daysFromNow,
  estimateRows,
  filterProjectRows,
  ganttLayout,
  normalizePortfolio,
  normalizePortfolioEntry,
  portfolioTotals,
  projectRowFromSummary,
  sortProjectRows,
  toProjectRow,
} from "./portfolio";

/** 「今天」固定成 2026-09-10，避免单测跟着真实时钟漂移。 */
const NOW = new Date("2026-09-10T09:00:00");

function entry(overrides: Partial<PortfolioEntry> = {}): PortfolioEntry {
  return {
    id: "p1",
    name: "投资",
    goal: "跑通投资闭环",
    status: "running",
    owner: "local:123",
    created_at: "2026-09-01T00:00:00",
    started_at: "",
    finished_at: "",
    execution_thread_id: "",
    health: "on_track",
    readable: true,
    progress: 0,
    done_tasks: 0,
    total_tasks: 0,
    total_estimate: 0,
    remaining_estimate: 0,
    counts: {
      milestones: 0,
      risks: 0,
      blockers: 0,
      overdue: 0,
      next_actions: 0,
    },
    milestones: [],
    overdue: [],
    next_actions: [],
    risks: [],
    ...overrides,
  };
}

describe("日期边界", () => {
  it("跨月：9 月 30 日 → 10 月 1 日算 1 天", () => {
    expect(
      daysFromNow(Date.parse("2026-10-01T00:00:00"), Date.parse("2026-09-30T00:00:00")),
    ).toBe(1);
  });

  it("跨年：12 月 31 日 → 1 月 1 日算 1 天", () => {
    expect(
      daysFromNow(Date.parse("2027-01-01T00:00:00"), Date.parse("2026-12-31T00:00:00")),
    ).toBe(1);
  });

  it("同日任意时刻都算 0 天（只看自然日）", () => {
    expect(
      daysFromNow(Date.parse("2026-09-10T23:59:00"), Date.parse("2026-09-10T00:01:00")),
    ).toBe(0);
  });

  it("dayKey 使用本地自然日", () => {
    expect(dayKey(Date.parse("2026-09-10T23:30:00"))).toBe("2026-09-10");
  });
});

describe("normalizePortfolio", () => {
  it("拒绝非列表与缺 id 的条目", () => {
    expect(normalizePortfolio(null)).toEqual([]);
    expect(normalizePortfolio({})).toEqual([]);
    expect(normalizePortfolio([{}, { name: "无 id" }])).toEqual([]);
  });

  it("接受 {projects: [...]} 包装并补齐缺省字段", () => {
    const [first] = normalizePortfolio({
      projects: [{ id: "p1" }],
    });
    expect(first).toBeDefined();
    expect(first!.name).toBe("p1");
    expect(first!.status).toBe("planning");
    expect(first!.health).toBe("on_track");
    expect(first!.counts.overdue).toBe(0);
    expect(first!.milestones).toEqual([]);
  });

  it("把未知 health 收敛为 on_track，并保留 readable=false", () => {
    const parsed = normalizePortfolioEntry({
      id: "p1",
      health: "exploded",
      readable: false,
      progress: 7,
    });
    expect(parsed!.health).toBe("on_track");
    expect(parsed!.readable).toBe(false);
    // progress 是 0–1 的比例，越界值必须夹紧。
    expect(parsed!.progress).toBe(1);
  });

  it("保留后端给出的 readable=true 默认语义", () => {
    expect(normalizePortfolioEntry({ id: "p1" })!.readable).toBe(true);
  });
});

describe("buildTodayQueue", () => {
  it("空项目列表不产生任何分组", () => {
    const queue = buildTodayQueue([], NOW);
    expect(queue.overdue).toEqual([]);
    expect(queue.dueToday).toEqual([]);
    expect(queue.atRisk).toEqual([]);
    expect(queue.total).toBe(0);
  });

  it("跨项目聚合逾期任务，并按优先级再按截止时间排序", () => {
    const queue = buildTodayQueue(
      [
        entry({
          id: "p1",
          name: "投资",
          counts: { milestones: 0, risks: 0, blockers: 0, overdue: 2, next_actions: 0 },
          overdue: [
            {
              milestone: "deliver",
              id: "t-p2",
              goal: "P2 后置任务",
              due_at: "2026-09-09T00:00:00",
              priority: "P2",
            },
            {
              milestone: "deliver",
              id: "t-p0",
              goal: "P0 阻塞任务",
              due_at: "2026-09-08T00:00:00",
              priority: "P0",
            },
          ],
        }),
        entry({
          id: "p2",
          name: "规格书",
          counts: { milestones: 0, risks: 0, blockers: 0, overdue: 1, next_actions: 0 },
          overdue: [
            {
              milestone: "spec",
              id: "t-p1",
              goal: "P1 任务",
              due_at: "2026-09-07T00:00:00",
              priority: "P1",
            },
          ],
        }),
      ],
      NOW,
    );

    expect(queue.overdue.map((item) => item.title)).toEqual([
      "P0 阻塞任务",
      "P1 任务",
      "P2 后置任务",
    ]);
    expect(queue.overdue[0]).toMatchObject({
      projectId: "p1",
      projectName: "投资",
      milestone: "deliver",
      scope: "task",
      kind: "overdue",
    });
    // 9/8 相对 9/10 是逾期 2 天。
    expect(queue.overdue[0]!.daysLeft).toBe(-2);
  });

  it("今天到期只收当天，明天与昨天都不进", () => {
    const queue = buildTodayQueue(
      [
        entry({
          next_actions: [
            {
              milestone: "deliver",
              task_id: "a-today",
              task: "今天做",
              priority: "P1",
              estimate: 1,
              due_at: "2026-09-10T18:00:00",
            },
            {
              milestone: "deliver",
              task_id: "a-tomorrow",
              task: "明天做",
              priority: "P1",
              estimate: 1,
              due_at: "2026-09-11T09:00:00",
            },
            {
              milestone: "deliver",
              task_id: "a-yesterday",
              task: "昨天就该做",
              priority: "P1",
              estimate: 1,
              due_at: "2026-09-09T09:00:00",
            },
          ],
        }),
      ],
      NOW,
    );

    expect(queue.dueToday.map((item) => item.taskId)).toEqual(["a-today"]);
    expect(queue.dueToday[0]!.daysLeft).toBe(0);
  });

  it("逾期的里程碑单独成条，任务仍各自成条", () => {
    const queue = buildTodayQueue(
      [
        entry({
          counts: { milestones: 1, risks: 0, blockers: 0, overdue: 1, next_actions: 0 },
          overdue: [
            {
              milestone: "deliver",
              id: "t1",
              goal: "任务级逾期",
              due_at: "2026-09-05T00:00:00",
              priority: "P1",
            },
          ],
          milestones: [
            {
              id: "m1",
              name: "deliver",
              status: "running",
              health: "overdue",
              priority: "P0",
              planned_start: "2026-09-01T00:00:00",
              due_at: "2026-09-05T00:00:00",
              done: 0,
              total: 1,
              failed: 0,
              progress: 0,
              remaining_estimate: 3,
              overdue_count: 1,
            },
          ],
        }),
      ],
      NOW,
    );

    expect(queue.overdue).toHaveLength(2);
    // P0 的里程碑条排在 P1 的任务前。
    expect(queue.overdue[0]!.scope).toBe("milestone");
    expect(queue.overdue[1]!.scope).toBe("task");
  });

  it("有风险与阻塞里程碑都进关注组，正常里程碑不进", () => {
    const queue = buildTodayQueue(
      [
        entry({
          milestones: [
            {
              id: "m1",
              name: "有风险",
              status: "running",
              health: "at_risk",
              priority: "P1",
              planned_start: "",
              due_at: "",
              done: 0,
              total: 0,
              failed: 0,
              progress: 0,
              remaining_estimate: 0,
              overdue_count: 0,
            },
            {
              id: "m2",
              name: "阻塞中",
              status: "blocked",
              health: "blocked",
              priority: "P0",
              planned_start: "",
              due_at: "",
              done: 0,
              total: 0,
              failed: 0,
              progress: 0,
              remaining_estimate: 0,
              overdue_count: 0,
            },
            {
              id: "m3",
              name: "一切正常",
              status: "running",
              health: "on_track",
              priority: "P3",
              planned_start: "",
              due_at: "",
              done: 0,
              total: 0,
              failed: 0,
              progress: 0,
              remaining_estimate: 0,
              overdue_count: 0,
            },
          ],
        }),
      ],
      NOW,
    );

    expect(queue.atRisk.map((item) => item.title)).toEqual(["阻塞中", "有风险"]);
  });

  it("同一项目出现重名任务时也会去重，不会重复计数", () => {
    const duplicated = {
      milestone: "deliver",
      id: "t1",
      goal: "同名任务",
      due_at: "2026-09-05T00:00:00",
      priority: "P1",
    };
    const queue = buildTodayQueue(
      [entry({ overdue: [duplicated, duplicated] })],
      NOW,
    );
    expect(queue.overdue).toHaveLength(1);
  });

  it("按后端真实总数记录被截断的隐藏条数", () => {
    const queue = buildTodayQueue(
      [
        entry({
          counts: { milestones: 0, risks: 0, blockers: 0, overdue: 25, next_actions: 12 },
          overdue: [
            {
              milestone: "deliver",
              id: "t1",
              goal: "唯一可见",
              due_at: "2026-09-05T00:00:00",
              priority: "P1",
            },
          ],
          next_actions: [],
        }),
      ],
      NOW,
    );
    expect(queue.hidden.overdue).toBe(24);
    expect(queue.hidden.nextActions).toBe(12);
  });

  it("无截止日的条目排在有时限的后面", () => {
    const queue = buildTodayQueue(
      [
        entry({
          overdue: [
            {
              milestone: "deliver",
              id: "no-due",
              goal: "没排期",
              due_at: "",
              priority: "P1",
            },
            {
              milestone: "deliver",
              id: "has-due",
              goal: "有排期",
              due_at: "2026-09-09T00:00:00",
              priority: "P1",
            },
          ],
        }),
      ],
      NOW,
    );
    expect(queue.overdue.map((item) => item.title)).toEqual(["有排期", "没排期"]);
    expect(queue.overdue[1]!.daysLeft).toBeNull();
  });

  it("跨月聚合：9 月 30 日看 10 月 1 日的到期项不算今天", () => {
    const queue = buildTodayQueue(
      [
        entry({
          next_actions: [
            {
              milestone: "deliver",
              task_id: "a1",
              task: "下月任务",
              priority: "P1",
              estimate: 1,
              due_at: "2026-10-01T09:00:00",
            },
          ],
        }),
      ],
      new Date("2026-09-30T09:00:00"),
    );
    expect(queue.dueToday).toEqual([]);
  });
});

describe("portfolioTotals", () => {
  it("空列表给出全零且不产生 NaN", () => {
    const totals = portfolioTotals([]);
    expect(totals.projects).toBe(0);
    expect(totals.progress).toBe(0);
    expect(totals.healthCounts.on_track).toBe(0);
  });

  it("按任务数加权求整体进度，并统计不可读项目", () => {
    const totals = portfolioTotals([
      entry({ id: "p1", progress: 1, total_tasks: 3, done_tasks: 3, counts: { milestones: 0, risks: 0, blockers: 0, overdue: 0, next_actions: 0 } }),
      entry({ id: "p2", progress: 0, total_tasks: 1, done_tasks: 0, readable: false, counts: { milestones: 0, risks: 0, blockers: 0, overdue: 0, next_actions: 0 } }),
    ]);
    expect(totals.projects).toBe(2);
    expect(totals.unreadable).toBe(1);
    expect(totals.tasks).toBe(4);
    expect(totals.progress).toBeCloseTo(0.75, 5);
  });

  it("统计有风险与阻塞的里程碑个数", () => {
    const milestone = (id: string, health: PortfolioEntry["milestones"][number]["health"]) => ({
      id,
      name: id,
      status: "running",
      health,
      priority: "P2",
      planned_start: "",
      due_at: "",
      done: 0,
      total: 0,
      failed: 0,
      progress: 0,
      remaining_estimate: 0,
      overdue_count: 0,
    });
    const totals = portfolioTotals([
      entry({
        milestones: [
          milestone("a", "at_risk"),
          milestone("b", "blocked"),
          milestone("c", "on_track"),
        ],
      }),
    ]);
    expect(totals.atRisk).toBe(2);
    expect(totals.healthCounts.on_track).toBe(1);
  });
});

describe("countHealth", () => {
  it("按五档归档并忽略未知值", () => {
    const counts = countHealth([
      "on_track",
      "on_track",
      "blocked",
      "overdue",
      "completed",
      "nonsense" as never,
    ]);
    expect(counts).toEqual({
      on_track: 3,
      at_risk: 0,
      overdue: 1,
      blocked: 1,
      completed: 1,
    });
  });
});

describe("ganttLayout", () => {
  const milestone = (
    id: string,
    planned_start: string,
    due_at: string,
    overrides: Record<string, unknown> = {},
  ) => ({
    id,
    name: id,
    status: "running",
    health: "on_track" as const,
    priority: "P2",
    planned_start,
    due_at,
    done: 0,
    total: 0,
    failed: 0,
    progress: 0,
    remaining_estimate: 0,
    overdue_count: 0,
    ...overrides,
  });

  it("全部缺日期时只输出未排期，不编造坐标", () => {
    const layout = ganttLayout([milestone("m1", "", "")], NOW);
    expect(layout.bars).toEqual([]);
    expect(layout.unscheduled).toHaveLength(1);
    expect(layout.todayPct).toBeNull();
  });

  it("按计划区间铺条，百分比落在 0–100 且宽度为正", () => {
    const layout = ganttLayout(
      [
        milestone("m1", "2026-09-01T00:00:00", "2026-09-05T00:00:00"),
        milestone("m2", "2026-09-06T00:00:00", "2026-09-12T00:00:00"),
      ],
      NOW,
    );
    expect(layout.bars).toHaveLength(2);
    for (const bar of layout.bars) {
      expect(bar.leftPct).toBeGreaterThanOrEqual(0);
      expect(bar.leftPct).toBeLessThanOrEqual(100);
      expect(bar.widthPct).toBeGreaterThan(0);
      expect(bar.leftPct + bar.widthPct).toBeLessThanOrEqual(100.001);
    }
    expect(layout.todayPct).not.toBeNull();
    expect(layout.ticks.length).toBeGreaterThan(0);
  });

  it("截止早于计划的脏数据收敛成最短单日条而不是负宽度", () => {
    const layout = ganttLayout(
      [milestone("m1", "2026-09-10T00:00:00", "2026-09-01T00:00:00")],
      NOW,
    );
    expect(layout.bars[0]!.widthPct).toBeGreaterThan(0);
    expect(layout.bars[0]!.endMs).toBeGreaterThan(layout.bars[0]!.startMs);
  });

  it("只有截止日期的里程碑也能画成单日条", () => {
    const layout = ganttLayout([milestone("m1", "", "2026-09-10T00:00:00")], NOW);
    expect(layout.bars).toHaveLength(1);
    expect(layout.unscheduled).toEqual([]);
  });

  it("今日基准线落在区间内，且优先级高的条排前面", () => {
    const layout = ganttLayout(
      [
        milestone("low", "2026-09-01T00:00:00", "2026-09-20T00:00:00", {
          priority: "P2",
        }),
        milestone("high", "2026-09-02T00:00:00", "2026-09-03T00:00:00", {
          priority: "P0",
        }),
      ],
      NOW,
    );
    expect(layout.bars.map((bar) => bar.id)).toEqual(["high", "low"]);
    expect(layout.todayPct!).toBeGreaterThanOrEqual(0);
    expect(layout.todayPct!).toBeLessThanOrEqual(100);
  });

  it("未来项目也会把今日线纳进跨度，避免今天线被挤出画布", () => {
    const layout = ganttLayout(
      [milestone("future", "2026-12-01T00:00:00", "2026-12-10T00:00:00")],
      NOW,
    );
    expect(layout.todayPct).not.toBeNull();
    // 今日线贴着左边缘（跨度从今天开始），但必须真的落在画布内。
    expect(layout.todayPct!).toBeLessThan(1);
    expect(layout.todayPct!).toBeGreaterThanOrEqual(0);
  });

  it("标记需要关注的条", () => {
    const layout = ganttLayout(
      [
        milestone("m1", "2026-09-01T00:00:00", "2026-09-05T00:00:00", {
          health: "overdue",
        }),
        milestone("m2", "2026-09-06T00:00:00", "2026-09-12T00:00:00", {
          health: "on_track",
        }),
      ],
      NOW,
    );
    expect(layout.bars.find((bar) => bar.id === "m1")!.flagged).toBe(true);
    expect(layout.bars.find((bar) => bar.id === "m2")!.flagged).toBe(false);
  });

  it("未知 health 归一为 on_track，不会漏进 undefined 分支", () => {
    const layout = ganttLayout(
      [
        milestone("m1", "2026-09-01T00:00:00", "2026-09-05T00:00:00", {
          health: "who-knows",
        }),
      ],
      NOW,
    );
    expect(layout.bars[0]!.health).toBe("on_track");
  });
});

describe("estimateRows", () => {
  it("已用 = 总量 − 剩余，且总量不小于剩余", () => {
    const [row] = estimateRows([
      {
        id: "m1",
        name: "deliver",
        health: "on_track",
        progress: 0.5,
        total_estimate: 10,
        remaining_estimate: 4,
      },
    ]);
    expect(row!.doneEstimate).toBe(6);
    expect(row!.remainingEstimate).toBe(4);
    expect(row!.totalEstimate).toBe(10);
  });

  it("剩余大于总量时以剩余为准，不产出负数已完成量", () => {
    const [row] = estimateRows([
      {
        id: "m1",
        name: "deliver",
        health: "at_risk",
        progress: 0,
        total_estimate: 2,
        remaining_estimate: 7,
      },
    ]);
    expect(row!.doneEstimate).toBe(0);
    expect(row!.totalEstimate).toBe(7);
  });
});

describe("filterProjectRows / sortProjectRows", () => {
  const rows = [
    toProjectRow(entry({ id: "p1", name: "投资", goal: "闭环", owner: "eve", health: "overdue", counts: { milestones: 0, risks: 0, blockers: 0, overdue: 3, next_actions: 0 } })),
    toProjectRow(entry({ id: "p2", name: "规格书", goal: "文档", owner: "adam", health: "on_track" })),
    toProjectRow(entry({ id: "p3", name: "归档", goal: "收尾", owner: "eve", status: "done", health: "completed" })),
  ];

  it("按名称 / 目标 / 负责人搜索", () => {
    expect(filterProjectRows(rows, "规格").map((row) => row.id)).toEqual(["p2"]);
    expect(filterProjectRows(rows, "闭环").map((row) => row.id)).toEqual(["p1"]);
    expect(filterProjectRows(rows, "eve").map((row) => row.id)).toEqual(["p1", "p3"]);
    expect(filterProjectRows(rows, "  ").map((row) => row.id)).toHaveLength(3);
  });

  it("需关注筛选只留有风险/逾期/阻塞的健康度", () => {
    expect(
      filterProjectRows(rows, "", "attention").map((row) => row.id),
    ).toEqual(["p1"]);
  });

  it("已结束筛选包含 done 与 failed", () => {
    expect(filterProjectRows(rows, "", "closed").map((row) => row.id)).toEqual([
      "p3",
    ]);
    expect(filterProjectRows(rows, "", "active").map((row) => row.id)).toEqual([
      "p1",
      "p2",
    ]);
  });

  it("排序把逾期放最前，其次按逾期条数", () => {
    expect(sortProjectRows(rows).map((row) => row.id)).toEqual([
      "p1",
      "p2",
      "p3",
    ]);
  });

  it("降级行不带进度且标记为不可读", () => {
    const fallback = projectRowFromSummary({ id: "px", name: "新项目" });
    expect(fallback.readable).toBe(false);
    expect(fallback.progress).toBe(0);
    expect(fallback.overdue).toBe(0);
    // 降级行仍然可被搜索到，否则接口故障时导航会失效。
    expect(filterProjectRows([fallback], "新项目")).toHaveLength(1);
  });
});
