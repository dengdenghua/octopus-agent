/**
 * Portfolio（跨项目）读模型 · 项目管理驾驶舱的纯计算层
 *
 * 数据来源：`GET /api/projects/portfolio`
 * （后端见 runtime/sensing/gateway/projects_router.py::portfolio 与
 * runtime/projectos/pm.py::build_portfolio_entry）
 *
 * 本文件只放纯函数：不依赖 React、不发起请求、不触碰 DOM，
 * 因此「今天要处理」的聚合排序、甘特布局、日期边界都能被单测直接覆盖。
 */

export type ProjectHealth =
  | "on_track"
  | "at_risk"
  | "overdue"
  | "blocked"
  | "completed";

/** 严重度从高到低 —— 用于「取最差」与分组排序。 */
export const HEALTH_SEVERITY: readonly ProjectHealth[] = [
  "blocked",
  "overdue",
  "at_risk",
  "on_track",
  "completed",
];

const HEALTH_SET = new Set<string>(HEALTH_SEVERITY);

export function normalizeHealth(value: unknown): ProjectHealth {
  const key = typeof value === "string" ? value.trim() : "";
  return HEALTH_SET.has(key) ? (key as ProjectHealth) : "on_track";
}

export function severityRank(health: ProjectHealth): number {
  const index = HEALTH_SEVERITY.indexOf(health);
  return index < 0 ? HEALTH_SEVERITY.length : index;
}

/** 多个健康度取最差 —— 与后端 `_portfolio_health` 保持同一语义。 */
export function worstHealth(
  healths: readonly ProjectHealth[],
): ProjectHealth {
  if (healths.length === 0) return "on_track";
  return healths.reduce((worst, current) =>
    severityRank(current) < severityRank(worst) ? current : worst,
  );
}

const PRIORITY_RANK: Record<string, number> = {
  P0: 0,
  P1: 1,
  P2: 2,
  P3: 3,
};

/** 未知优先级排在 P3 之后，避免脏数据冲到最前面。 */
export function priorityRank(priority: string | null | undefined): number {
  const key = (priority ?? "").trim().toUpperCase();
  return PRIORITY_RANK[key] ?? PRIORITY_RANK.P3! + 1;
}

// ─── 后端返回结构 ────────────────────────────────────────────────────

/** 甘特布局真正会读到的字段。
 *
 * 抽出来是为了让「portfolio 精简里程碑」和「项目详情里的完整 PM 里程碑」
 * （runtime/projectos/pm.py::MilestonePM）都能直接喂给 `ganttLayout`，
 * 而不必在前端造一份中间结构。
 */
export interface GanttInput {
  id: string;
  name: string;
  /** portfolio 给的是收窄后的 health，项目详情给的是裸字符串。 */
  health: string;
  priority: string;
  planned_start: string;
  due_at: string;
  progress: number;
  done: number;
  total: number;
  remaining_estimate: number;
  /** 完整 PM 里程碑里逾期任务在 `overdue_tasks` 数组上，故此处可选。 */
  overdue_count?: number;
}

export interface PortfolioMilestone extends GanttInput {
  status: string;
  health: ProjectHealth;
  failed: number;
  overdue_count: number;
}

export interface PortfolioOverdueTask {
  milestone: string;
  id: string;
  goal: string;
  due_at: string;
  priority: string;
}

export interface PortfolioNextAction {
  milestone: string;
  task_id: string;
  task: string;
  priority: string;
  estimate: number;
  due_at: string;
}

export interface PortfolioRisk {
  type: "milestone" | "task";
  milestone?: string;
  task_id?: string;
  task?: string;
  health: string;
  detail: string;
}

export interface PortfolioCounts {
  milestones: number;
  risks: number;
  blockers: number;
  overdue: number;
  next_actions: number;
}

export interface PortfolioEntry {
  id: string;
  name: string;
  goal: string;
  status: string;
  owner: string;
  created_at: string;
  started_at: string;
  finished_at: string;
  execution_thread_id: string;
  health: ProjectHealth;
  readable: boolean;
  progress: number;
  done_tasks: number;
  total_tasks: number;
  total_estimate: number;
  remaining_estimate: number;
  counts: PortfolioCounts;
  milestones: PortfolioMilestone[];
  overdue: PortfolioOverdueTask[];
  next_actions: PortfolioNextAction[];
  risks: PortfolioRisk[];
}

const EMPTY_COUNTS: PortfolioCounts = {
  milestones: 0,
  risks: 0,
  blockers: 0,
  overdue: 0,
  next_actions: 0,
};

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function arr<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * 把后端（或任何不可信来源）的条目收窄成 `PortfolioEntry`。
 *
 * 页面拿到的可能是 `[]`、`{}`、或被网关改写的错误体；这里逐字段兜底，
 * 保证下游 `buildTodayQueue` / 甘特布局永远不会读到 `undefined.length`。
 */
export function normalizePortfolioEntry(raw: unknown): PortfolioEntry | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const id = str(value.id).trim();
  if (!id) return null;
  const counts = (value.counts ?? {}) as Record<string, unknown>;
  return {
    id,
    name: str(value.name).trim() || id,
    goal: str(value.goal),
    status: str(value.status, "planning"),
    owner: str(value.owner),
    created_at: str(value.created_at),
    started_at: str(value.started_at),
    finished_at: str(value.finished_at),
    execution_thread_id: str(value.execution_thread_id),
    health: normalizeHealth(value.health),
    readable: value.readable !== false,
    progress: clamp01(num(value.progress)),
    done_tasks: num(value.done_tasks),
    total_tasks: num(value.total_tasks),
    total_estimate: num(value.total_estimate),
    remaining_estimate: num(value.remaining_estimate),
    counts: {
      milestones: num(counts.milestones),
      risks: num(counts.risks),
      blockers: num(counts.blockers),
      overdue: num(counts.overdue),
      next_actions: num(counts.next_actions),
    },
    milestones: arr<Record<string, unknown>>(value.milestones).map((m) => ({
      id: str(m.id),
      name: str(m.name).trim() || str(m.id),
      status: str(m.status, "planned"),
      health: normalizeHealth(m.health),
      priority: str(m.priority, "P2"),
      planned_start: str(m.planned_start),
      due_at: str(m.due_at),
      done: num(m.done),
      total: num(m.total),
      failed: num(m.failed),
      progress: clamp01(num(m.progress)),
      remaining_estimate: num(m.remaining_estimate),
      overdue_count: num(m.overdue_count),
    })),
    overdue: arr<Record<string, unknown>>(value.overdue).map((t) => ({
      milestone: str(t.milestone),
      id: str(t.id),
      goal: str(t.goal),
      due_at: str(t.due_at),
      priority: str(t.priority, "P2"),
    })),
    next_actions: arr<Record<string, unknown>>(value.next_actions).map((a) => ({
      milestone: str(a.milestone),
      task_id: str(a.task_id),
      task: str(a.task),
      priority: str(a.priority, "P2"),
      estimate: num(a.estimate),
      due_at: str(a.due_at),
    })),
    risks: arr<Record<string, unknown>>(value.risks).map((r) => ({
      type: r.type === "milestone" ? "milestone" : "task",
      milestone: typeof r.milestone === "string" ? r.milestone : undefined,
      task_id: typeof r.task_id === "string" ? r.task_id : undefined,
      task: typeof r.task === "string" ? r.task : undefined,
      health: str(r.health),
      detail: str(r.detail),
    })),
  };
}

/** 接受数组或 `{projects: [...]}`，其余形态一律当空。 */
export function normalizePortfolio(raw: unknown): PortfolioEntry[] {
  const list = Array.isArray(raw)
    ? raw
    : raw && typeof raw === "object" && Array.isArray((raw as { projects?: unknown }).projects)
      ? ((raw as { projects: unknown[] }).projects)
      : [];
  const entries: PortfolioEntry[] = [];
  for (const item of list) {
    const entry = normalizePortfolioEntry(item);
    if (entry) entries.push(entry);
  }
  return entries;
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(0, value));
}

// ─── 日期工具（全部按本地自然日计算） ─────────────────────────────────

export const DAY_MS = 24 * 60 * 60 * 1000;

export function parseDateMs(value: string | null | undefined): number | null {
  const raw = (value ?? "").trim();
  if (!raw) return null;
  const ms = Date.parse(raw);
  return Number.isNaN(ms) ? null : ms;
}

export function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function dayKey(ms: number): string {
  const d = new Date(ms);
  const month = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${d.getFullYear()}-${month}-${day}`;
}

/** 日历天数差：今天 → 明天 = 1，今天 → 昨天 = -1。跨月跨年天然正确。 */
export function daysFromNow(dueMs: number, nowMs: number): number {
  return Math.round((startOfDay(dueMs) - startOfDay(nowMs)) / DAY_MS);
}

// ─── 「今天要处理」聚合 ───────────────────────────────────────────────

export type TodayKind = "overdue" | "due_today" | "at_risk";

export interface TodayItem {
  key: string;
  kind: TodayKind;
  scope: "task" | "milestone";
  projectId: string;
  projectName: string;
  milestone: string;
  taskId: string;
  title: string;
  dueAt: string;
  priority: string;
  /** 负数为已逾期天数；无截止日为 null。 */
  daysLeft: number | null;
  health: ProjectHealth;
}

export interface TodayQueue {
  overdue: TodayItem[];
  dueToday: TodayItem[];
  atRisk: TodayItem[];
  total: number;
  /** 各分组被后端限流截断的隐藏条数（0 表示全部可见）。 */
  hidden: { overdue: number; nextActions: number };
}

function compareTodayItems(a: TodayItem, b: TodayItem): number {
  const byPriority = priorityRank(a.priority) - priorityRank(b.priority);
  if (byPriority !== 0) return byPriority;
  const aDue = parseDateMs(a.dueAt);
  const bDue = parseDateMs(b.dueAt);
  if (aDue !== null && bDue !== null && aDue !== bDue) return aDue - bDue;
  if (aDue === null && bDue !== null) return 1;
  if (aDue !== null && bDue === null) return -1;
  const byProject = a.projectName.localeCompare(b.projectName, "zh-CN");
  if (byProject !== 0) return byProject;
  return a.title.localeCompare(b.title, "zh-CN");
}

/**
 * 把 N 个项目的逾期 / 今日到期 / 有风险里程碑压成三组「现在就该看的条目」。
 *
 * 这是现有页面最大的空白：跨项目风险此前只能逐个点进项目才能发现。
 */
export function buildTodayQueue(
  entries: readonly PortfolioEntry[],
  now: Date | number = new Date(),
): TodayQueue {
  const nowMs = typeof now === "number" ? now : now.getTime();
  const today = dayKey(nowMs);
  const overdue: TodayItem[] = [];
  const dueToday: TodayItem[] = [];
  const atRisk: TodayItem[] = [];
  const seen = new Set<string>();
  let hiddenOverdue = 0;
  let hiddenNextActions = 0;

  const push = (bucket: TodayItem[], item: TodayItem) => {
    if (seen.has(item.key)) return;
    seen.add(item.key);
    bucket.push(item);
  };

  for (const entry of entries) {
    const base = { projectId: entry.id, projectName: entry.name };

    for (const task of entry.overdue) {
      const dueMs = parseDateMs(task.due_at);
      push(overdue, {
        ...base,
        key: `overdue:${entry.id}:${task.id || task.milestone}:${task.goal}`,
        kind: "overdue",
        scope: "task",
        milestone: task.milestone,
        taskId: task.id,
        title: task.goal || "未命名任务",
        dueAt: task.due_at,
        priority: task.priority,
        daysLeft: dueMs === null ? null : daysFromNow(dueMs, nowMs),
        health: "overdue",
      });
    }

    for (const milestone of entry.milestones) {
      if (milestone.health === "overdue") {
        const dueMs = parseDateMs(milestone.due_at);
        push(overdue, {
          ...base,
          key: `overdue-milestone:${entry.id}:${milestone.id}`,
          kind: "overdue",
          scope: "milestone",
          milestone: milestone.name,
          taskId: "",
          title: milestone.name,
          dueAt: milestone.due_at,
          priority: milestone.priority,
          daysLeft: dueMs === null ? null : daysFromNow(dueMs, nowMs),
          health: "overdue",
        });
        continue;
      }
      if (milestone.health === "at_risk" || milestone.health === "blocked") {
        const dueMs = parseDateMs(milestone.due_at);
        push(atRisk, {
          ...base,
          key: `risk:${entry.id}:${milestone.id}`,
          kind: "at_risk",
          scope: "milestone",
          milestone: milestone.name,
          taskId: "",
          title: milestone.name,
          dueAt: milestone.due_at,
          priority: milestone.priority,
          daysLeft: dueMs === null ? null : daysFromNow(dueMs, nowMs),
          health: milestone.health,
        });
      }
      if (milestone.due_at && dayKey(startOfDay(parseDateMs(milestone.due_at)!)) === today) {
        push(dueToday, {
          ...base,
          key: `due-milestone:${entry.id}:${milestone.id}`,
          kind: "due_today",
          scope: "milestone",
          milestone: milestone.name,
          taskId: "",
          title: milestone.name,
          dueAt: milestone.due_at,
          priority: milestone.priority,
          daysLeft: 0,
          health: milestone.health,
        });
      }
    }

    for (const action of entry.next_actions) {
      const dueMs = parseDateMs(action.due_at);
      if (dueMs === null || dayKey(dueMs) !== today) continue;
      push(dueToday, {
        ...base,
        key: `due:${entry.id}:${action.task_id || action.task}`,
        kind: "due_today",
        scope: "task",
        milestone: action.milestone,
        taskId: action.task_id,
        title: action.task || "未命名任务",
        dueAt: action.due_at,
        priority: action.priority,
        daysLeft: daysFromNow(dueMs, nowMs),
        health: "on_track",
      });
    }

    hiddenOverdue += Math.max(0, entry.counts.overdue - entry.overdue.length);
    hiddenNextActions += Math.max(
      0,
      entry.counts.next_actions - entry.next_actions.length,
    );
  }

  overdue.sort(compareTodayItems);
  dueToday.sort(compareTodayItems);
  atRisk.sort(compareTodayItems);

  return {
    overdue,
    dueToday,
    atRisk,
    total: overdue.length + dueToday.length + atRisk.length,
    hidden: { overdue: hiddenOverdue, nextActions: hiddenNextActions },
  };
}

// ─── 全局统计 ────────────────────────────────────────────────────────

export interface PortfolioTotals {
  projects: number;
  unreadable: number;
  milestones: number;
  tasks: number;
  doneTasks: number;
  overdue: number;
  atRisk: number;
  risks: number;
  remainingEstimate: number;
  progress: number;
  healthCounts: Record<ProjectHealth, number>;
}

export function countHealth(
  healths: readonly ProjectHealth[],
): Record<ProjectHealth, number> {
  const counts: Record<ProjectHealth, number> = {
    on_track: 0,
    at_risk: 0,
    overdue: 0,
    blocked: 0,
    completed: 0,
  };
  for (const health of healths) counts[normalizeHealth(health)] += 1;
  return counts;
}

export function portfolioTotals(
  entries: readonly PortfolioEntry[],
): PortfolioTotals {
  let milestones = 0;
  let tasks = 0;
  let doneTasks = 0;
  let overdue = 0;
  let atRisk = 0;
  let risks = 0;
  let remainingEstimate = 0;
  let weightedDone = 0;
  let unreadable = 0;
  const healths: ProjectHealth[] = [];

  for (const entry of entries) {
    if (!entry.readable) unreadable += 1;
    milestones += entry.counts.milestones || entry.milestones.length;
    tasks += entry.total_tasks;
    doneTasks += entry.done_tasks;
    overdue += entry.counts.overdue;
    risks += entry.counts.risks;
    remainingEstimate += entry.remaining_estimate;
    weightedDone += entry.progress * entry.total_tasks;
    for (const milestone of entry.milestones) {
      healths.push(milestone.health);
      if (milestone.health === "at_risk" || milestone.health === "blocked") {
        atRisk += 1;
      }
    }
  }

  return {
    projects: entries.length,
    unreadable,
    milestones,
    tasks,
    doneTasks,
    overdue,
    atRisk,
    risks,
    remainingEstimate: Math.round(remainingEstimate * 100) / 100,
    progress: tasks > 0 ? weightedDone / tasks : 0,
    healthCounts: countHealth(healths),
  };
}

// ─── 项目列表行模型 ──────────────────────────────────────────────────

/**
 * 列表行需要的字段。
 *
 * 抽成独立结构的原因：`/api/projects/portfolio` 挂掉时页面必须还能列出项目
 * （降级用 `/api/projects` 的裸列表），否则一个统计接口的故障会连带把导航
 * 也清空。两种来源都收敛成 `ProjectRow`，列表组件只认这一种。
 */
export interface ProjectRow {
  id: string;
  name: string;
  goal: string;
  status: string;
  owner: string;
  health: ProjectHealth;
  readable: boolean;
  progress: number;
  doneTasks: number;
  totalTasks: number;
  remainingEstimate: number;
  overdue: number;
  risks: number;
}

export function toProjectRow(entry: PortfolioEntry): ProjectRow {
  return {
    id: entry.id,
    name: entry.name,
    goal: entry.goal,
    status: entry.status,
    owner: entry.owner,
    health: entry.health,
    readable: entry.readable,
    progress: entry.progress,
    doneTasks: entry.done_tasks,
    totalTasks: entry.total_tasks,
    remainingEstimate: entry.remaining_estimate,
    overdue: entry.counts.overdue,
    risks: entry.counts.risks,
  };
}

/** 降级行：只有 `/api/projects` 的元数据，没有进度与健康度。 */
export function projectRowFromSummary(summary: {
  id: string;
  name?: string;
  goal?: string;
  status?: string;
}): ProjectRow {
  return {
    id: summary.id,
    name: summary.name?.trim() || summary.id,
    goal: summary.goal ?? "",
    status: summary.status ?? "planning",
    owner: "",
    health: "on_track",
    readable: false,
    progress: 0,
    doneTasks: 0,
    totalTasks: 0,
    remainingEstimate: 0,
    overdue: 0,
    risks: 0,
  };
}

export type ProjectStatusFilter = "all" | "active" | "attention" | "closed";

const CLOSED_STATUSES = new Set(["done", "failed"]);
const ATTENTION_HEALTH = new Set<ProjectHealth>([
  "at_risk",
  "overdue",
  "blocked",
]);

export function matchesStatusFilter(
  row: Pick<ProjectRow, "status" | "health">,
  filter: ProjectStatusFilter,
): boolean {
  if (filter === "all") return true;
  if (filter === "closed") return CLOSED_STATUSES.has(row.status);
  if (filter === "attention") return ATTENTION_HEALTH.has(row.health);
  return !CLOSED_STATUSES.has(row.status);
}

export function filterProjectRows(
  rows: readonly ProjectRow[],
  query: string,
  filter: ProjectStatusFilter = "all",
): ProjectRow[] {
  const needle = query.trim().toLowerCase();
  return rows.filter((row) => {
    if (!matchesStatusFilter(row, filter)) return false;
    if (!needle) return true;
    return (
      row.name.toLowerCase().includes(needle) ||
      row.goal.toLowerCase().includes(needle) ||
      row.owner.toLowerCase().includes(needle)
    );
  });
}

/** 需要关注的项目排在前面，其余按创建时间倒序由调用方保证顺序。 */
export function sortProjectRows(rows: readonly ProjectRow[]): ProjectRow[] {
  return [...rows].sort(
    (a, b) =>
      severityRank(a.health) - severityRank(b.health) ||
      b.overdue - a.overdue ||
      b.risks - a.risks ||
      a.name.localeCompare(b.name, "zh-CN"),
  );
}

// ─── 甘特布局 ────────────────────────────────────────────────────────

export interface GanttBar {
  id: string;
  name: string;
  health: ProjectHealth;
  priority: string;
  startMs: number;
  endMs: number;
  /** 相对时间轴的百分比（0–100）。 */
  leftPct: number;
  widthPct: number;
  progress: number;
  done: number;
  total: number;
  remainingEstimate: number;
  overdueCount: number;
  flagged: boolean;
}

export interface GanttTick {
  key: string;
  label: string;
  leftPct: number;
}

export interface GanttLayout {
  bars: GanttBar[];
  unscheduled: Array<{ id: string; name: string; health: ProjectHealth }>;
  ticks: GanttTick[];
  todayPct: number | null;
  spanMs: number;
}

const EMPTY_GANTT: GanttLayout = {
  bars: [],
  unscheduled: [],
  ticks: [],
  todayPct: null,
  spanMs: 0,
};

const TARGET_TICKS = 6;

/**
 * 里程碑 → 时间轴坐标。
 *
 * 只有同时拿到 `planned_start` / `due_at` 的里程碑才进图；缺日期的进
 * `unscheduled`，由 UI 用文字列出而不是硬塞到坐标轴上（那会伪造出排期）。
 */
export function ganttLayout(
  milestones: readonly GanttInput[],
  now: Date | number = new Date(),
): GanttLayout {
  const nowMs = typeof now === "number" ? now : now.getTime();
  const scheduled: Array<{
    milestone: GanttInput;
    startMs: number;
    endMs: number;
  }> = [];
  const unscheduled: GanttLayout["unscheduled"] = [];

  for (const milestone of milestones) {
    const health = normalizeHealth(milestone.health);
    const startRaw = parseDateMs(milestone.planned_start);
    const dueRaw = parseDateMs(milestone.due_at);
    if (startRaw === null && dueRaw === null) {
      unscheduled.push({
        id: milestone.id,
        name: milestone.name,
        health,
      });
      continue;
    }
    const startMs = startRaw ?? dueRaw!;
    // 脏数据（截止早于计划）收敛成单日条，不要产出负宽度。
    const endMs = dueRaw === null || dueRaw < startMs ? startMs : dueRaw;
    scheduled.push({ milestone, startMs, endMs: endExclusive(endMs) });
  }

  if (scheduled.length === 0) {
    return { ...EMPTY_GANTT, unscheduled };
  }

  let rangeStart = startOfDay(
    Math.min(...scheduled.map((item) => item.startMs), nowMs),
  );
  let rangeEnd = Math.max(
    ...scheduled.map((item) => item.endMs),
    startOfDay(nowMs) + DAY_MS,
  );
  if (rangeEnd <= rangeStart) rangeEnd = rangeStart + DAY_MS;
  const spanMs = rangeEnd - rangeStart;

  const bars: GanttBar[] = scheduled
    .map(({ milestone, startMs, endMs }) => {
      const health = normalizeHealth(milestone.health);
      const leftPct = ((startMs - rangeStart) / spanMs) * 100;
      const rawWidth = ((endMs - startMs) / spanMs) * 100;
      return {
        id: milestone.id,
        name: milestone.name,
        health,
        priority: milestone.priority,
        startMs,
        endMs,
        leftPct: clampPct(leftPct),
        // 单日条至少 1.5%，否则在长跨度项目里彻底看不见。
        widthPct: clampPct(Math.max(rawWidth, 1.5)),
        progress: milestone.progress,
        done: milestone.done,
        total: milestone.total,
        remainingEstimate: milestone.remaining_estimate,
        overdueCount: milestone.overdue_count ?? 0,
        flagged:
          health === "at_risk" || health === "overdue" || health === "blocked",
      };
    })
    .sort(
      (a, b) =>
        priorityRank(a.priority) - priorityRank(b.priority) ||
        a.startMs - b.startMs ||
        a.name.localeCompare(b.name, "zh-CN"),
    );

  const totalDays = Math.max(1, Math.round(spanMs / DAY_MS));
  const step = Math.max(1, Math.ceil(totalDays / TARGET_TICKS));
  const ticks: GanttTick[] = [];
  for (let offsetDays = 0; offsetDays <= totalDays; offsetDays += step) {
    const ms = rangeStart + offsetDays * DAY_MS;
    ticks.push({
      key: dayKey(ms),
      label: `${new Date(ms).getMonth() + 1}/${new Date(ms).getDate()}`,
      leftPct: clampPct(((ms - rangeStart) / spanMs) * 100),
    });
  }

  const nowClamped = Math.min(Math.max(nowMs, rangeStart), rangeEnd);
  return {
    bars,
    unscheduled,
    ticks,
    todayPct: clampPct(((nowClamped - rangeStart) / spanMs) * 100),
    spanMs,
  };
}

/** 截止日按「当天结束」算，避免当日条宽度为 0。 */
function endExclusive(endMs: number): number {
  return startOfDay(endMs) + DAY_MS;
}

function clampPct(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, value));
}

// ─── 里程碑估时（替代原先「假燃尽」的进度条） ─────────────────────────

export interface EstimateRow {
  id: string;
  name: string;
  health: ProjectHealth;
  doneEstimate: number;
  remainingEstimate: number;
  totalEstimate: number;
  progress: number;
}

export interface EstimateLike {
  id: string;
  name: string;
  health: string;
  progress: number;
  total_estimate: number;
  remaining_estimate: number;
}

export function estimateRows(
  milestones: readonly EstimateLike[],
): EstimateRow[] {
  return milestones.map((milestone) => {
    const remaining = Math.max(0, milestone.remaining_estimate);
    const total = Math.max(remaining, milestone.total_estimate);
    return {
      id: milestone.id,
      name: milestone.name,
      health: normalizeHealth(milestone.health),
      doneEstimate: Math.max(0, round2(total - remaining)),
      remainingEstimate: round2(remaining),
      totalEstimate: round2(total),
      progress: clamp01(milestone.progress),
    };
  });
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
