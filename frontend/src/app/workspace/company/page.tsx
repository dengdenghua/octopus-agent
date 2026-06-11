import {
  AlertTriangleIcon,
  ArrowRightIcon,
  BellIcon,
  BotIcon,
  BriefcaseBusinessIcon,
  CalendarDaysIcon,
  ChevronRightIcon,
  ClipboardListIcon,
  FileTextIcon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  PlusIcon,
  SearchIcon,
  SparklesIcon,
  Trash2Icon,
  UsersRoundIcon,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";

import { Button } from "@/components/ui/button";
import {
  useCompanyProjects,
  useCreateProjectBlueprint,
  useDeleteCompanyProject,
  useProjectArtifacts,
  useProjectGantt,
  useProjectInsights,
  useProjectMilestones,
  useProjectTasks,
} from "@/core/company";
import type {
  CompanyProject,
  GanttTaskView,
  ProjectArtifact,
  ProjectBudgetTier,
  ProjectInsight,
  ProjectMilestone,
  ProjectTask,
} from "@/core/company";
import { cn } from "@/lib/utils";

const QUICK_PROMPTS = [
  "从一个智能硬件产品想法开始，帮我拆解市场验证、样机研发、供应链试产和上市发布。",
  "把一个企业客户需求变成可执行项目，生成里程碑、任务看板、协作团队和交付物。",
  "为现有项目补齐 PRD、甘特图、风险项和 AI Agent 协作流程。",
];

const BUDGET_OPTIONS: Array<{
  value: ProjectBudgetTier;
  label: string;
}> = [
  { value: "lean", label: "精简" },
  { value: "standard", label: "标准" },
  { value: "premium", label: "旗舰" },
  { value: "enterprise", label: "企业" },
];

const HORIZON_OPTIONS = [
  { value: 90, label: "90 天" },
  { value: 180, label: "180 天" },
  { value: 365, label: "1 年" },
];

const STAGE_LABELS: Record<CompanyProject["stage"], string> = {
  idea: "想法",
  validation: "验证",
  prototype: "原型",
  pilot: "试点",
  commercial: "商业化",
};

const STATUS_LABELS: Record<CompanyProject["status"], string> = {
  active: "进行中",
  paused: "暂停",
  completed: "完成",
  cancelled: "取消",
};

const TASK_STATUS_LABELS: Record<ProjectTask["status"], string> = {
  todo: "待处理",
  doing: "进行中",
  blocked: "等待确认",
  done: "已完成",
  cancelled: "已取消",
};

type DashboardTask = {
  id: string;
  title: string;
  description: string;
  status: ProjectTask["status"];
  priority: ProjectTask["priority"];
  dueLabel: string;
  owner: string;
  progress: number;
  source: string;
};

type DashboardMilestone = {
  id: string;
  title: string;
  dateLabel: string;
  status: string;
  owner: string;
  progress: number;
};

type DashboardGanttItem = {
  id: string;
  title: string;
  owner: string;
  dateRange: string;
  progress: number;
  status: string;
  critical: boolean;
  isMilestone: boolean;
};

type DashboardInsight = {
  id: string;
  title: string;
  detail: string;
  tone: "success" | "warning" | "danger" | "primary";
  time: string;
};

type DashboardArtifact = {
  id: string;
  title: string;
  type: string;
};

const DEMO_TASKS: DashboardTask[] = [
  {
    id: "demo-task-1",
    title: "PRD 文档编写",
    description: "梳理智能硬件核心功能、产品需求和交互边界。",
    status: "doing",
    priority: "urgent",
    dueLabel: "12-25",
    owner: "张晓明",
    progress: 60,
    source: "AI Agent",
  },
  {
    id: "demo-task-2",
    title: "竞品分析报告",
    description: "覆盖价格、功能、供应链能力和目标客群。",
    status: "todo",
    priority: "medium",
    dueLabel: "12-18",
    owner: "李华",
    progress: 18,
    source: "市场研究",
  },
  {
    id: "demo-task-3",
    title: "技术方案确认",
    description: "确认芯片方案、传感器选型和云端协议。",
    status: "blocked",
    priority: "high",
    dueLabel: "12-19",
    owner: "陈晨",
    progress: 76,
    source: "研发评审",
  },
  {
    id: "demo-task-4",
    title: "样机外观评审",
    description: "完成三套工业设计稿的内部评审。",
    status: "done",
    priority: "low",
    dueLabel: "12-01",
    owner: "刘菲",
    progress: 100,
    source: "设计",
  },
  {
    id: "demo-task-5",
    title: "接口开发",
    description: "设备侧上报、App 配置和告警链路。",
    status: "doing",
    priority: "high",
    dueLabel: "01-05",
    owner: "周成",
    progress: 44,
    source: "工程",
  },
  {
    id: "demo-task-6",
    title: "上市物料准备",
    description: "官网、售前资料、演示视频和发布节奏。",
    status: "todo",
    priority: "medium",
    dueLabel: "02-08",
    owner: "市场团队",
    progress: 8,
    source: "增长",
  },
];

const DEMO_MILESTONES: DashboardMilestone[] = [
  {
    id: "demo-ms-1",
    title: "项目启动",
    dateLabel: "2024-11-01",
    status: "已完成",
    owner: "张晓明",
    progress: 100,
  },
  {
    id: "demo-ms-2",
    title: "需求确认",
    dateLabel: "2024-11-15",
    status: "已完成",
    owner: "李华",
    progress: 100,
  },
  {
    id: "demo-ms-3",
    title: "方案评审",
    dateLabel: "2024-12-20",
    status: "进行中",
    owner: "陈晨",
    progress: 68,
  },
  {
    id: "demo-ms-4",
    title: "测试验证",
    dateLabel: "2025-01-15",
    status: "未开始",
    owner: "测试团队",
    progress: 0,
  },
  {
    id: "demo-ms-5",
    title: "正式上线",
    dateLabel: "2025-02-28",
    status: "未开始",
    owner: "张晓明",
    progress: 0,
  },
];

const DEMO_GANTT: DashboardGanttItem[] = [
  {
    id: "demo-gantt-1",
    title: "需求分析",
    owner: "张晓明",
    dateRange: "12-02 - 12-08",
    progress: 100,
    status: "已完成",
    critical: false,
    isMilestone: false,
  },
  {
    id: "demo-gantt-2",
    title: "用户调研",
    owner: "李华",
    dateRange: "12-06 - 12-15",
    progress: 78,
    status: "进行中",
    critical: false,
    isMilestone: false,
  },
  {
    id: "demo-gantt-3",
    title: "方案设计",
    owner: "陈晨",
    dateRange: "12-12 - 12-28",
    progress: 64,
    status: "进行中",
    critical: true,
    isMilestone: false,
  },
  {
    id: "demo-gantt-4",
    title: "开发实现",
    owner: "工程团队",
    dateRange: "12-24 - 01-18",
    progress: 38,
    status: "进行中",
    critical: true,
    isMilestone: false,
  },
  {
    id: "demo-gantt-5",
    title: "测试验证",
    owner: "测试团队",
    dateRange: "01-12 - 01-28",
    progress: 0,
    status: "未开始",
    critical: false,
    isMilestone: false,
  },
  {
    id: "demo-gantt-6",
    title: "上线发布",
    owner: "张晓明",
    dateRange: "02-08",
    progress: 0,
    status: "未开始",
    critical: true,
    isMilestone: true,
  },
];

const DEMO_INSIGHTS: DashboardInsight[] = [
  {
    id: "demo-insight-1",
    title: "产品经理 Agent 完成了 PRD 草稿",
    detail: "已覆盖 12 个核心功能和验收口径。",
    tone: "primary",
    time: "2 分钟前",
  },
  {
    id: "demo-insight-2",
    title: "研究 Agent 发现 3 个竞品动态",
    detail: "建议同步更新价格策略和渠道假设。",
    tone: "warning",
    time: "15 分钟前",
  },
  {
    id: "demo-insight-3",
    title: "测试 Agent 提交了测试策略",
    detail: "覆盖稳定性、弱网和传感器校准场景。",
    tone: "success",
    time: "1 小时前",
  },
];

const DEMO_ARTIFACTS: DashboardArtifact[] = [
  { id: "demo-doc-1", title: "PRD_初稿_v1.0.docx", type: "doc" },
  { id: "demo-doc-2", title: "需求调研样本.pdf", type: "pdf" },
  { id: "demo-doc-3", title: "竞品分析.xlsx", type: "sheet" },
];

function clampProgress(value: number | undefined | null): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function formatDate(value?: string | null, fallback = "未排期"): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function formatLongDate(value?: string | null, fallback = "未排期"): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatShortToday(): string {
  return new Date().toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  });
}

function dayPeriodGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return "夜深了";
  if (hour < 12) return "上午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function projectProgress(
  milestones: ProjectMilestone[],
  tasks: ProjectTask[],
): number {
  if (tasks.length > 0) {
    return clampProgress(
      tasks.reduce((sum, task) => sum + task.progress, 0) / tasks.length,
    );
  }
  if (milestones.length > 0) {
    return clampProgress(
      milestones.reduce((sum, milestone) => sum + milestone.progress, 0) /
        milestones.length,
    );
  }
  return 68;
}

function remainingDays(target?: string | null): number {
  if (!target) return 72;
  const end = new Date(target).getTime();
  if (Number.isNaN(end)) return 72;
  return Math.max(0, Math.ceil((end - Date.now()) / 86_400_000));
}

function normalizeTasks(tasks: ProjectTask[]): DashboardTask[] {
  if (tasks.length === 0) return DEMO_TASKS;
  return tasks.map((task) => {
    const firstAssignee = task.assignees[0];
    return {
      id: task.id,
      title: task.title,
      description: task.description || "暂无任务说明",
      status: task.status,
      priority: task.priority,
      dueLabel: formatDate(task.due_at ?? task.planned_end_at),
      owner:
        task.owner_name ??
        firstAssignee?.display_name ??
        firstAssignee?.ref ??
        "AI Agent",
      progress: clampProgress(task.progress),
      source: task.source === "agent" ? "AI Agent" : "项目任务",
    };
  });
}

function normalizeMilestones(
  milestones: ProjectMilestone[],
): DashboardMilestone[] {
  if (milestones.length === 0) return DEMO_MILESTONES;
  return milestones.map((milestone) => ({
    id: milestone.id,
    title: milestone.title,
    dateLabel: formatLongDate(
      milestone.target_date ?? milestone.planned_end_at,
      "未排期",
    ),
    status:
      milestone.status === "done"
        ? "已完成"
        : milestone.status === "in_progress"
          ? "进行中"
          : milestone.status === "blocked"
            ? "有风险"
            : "未开始",
    owner: milestone.owner_id ?? "项目团队",
    progress: clampProgress(milestone.progress),
  }));
}

function normalizeGantt(gantt: GanttTaskView[]): DashboardGanttItem[] {
  if (gantt.length === 0) return DEMO_GANTT;
  return gantt.map((item) => ({
    id: item.id,
    title: item.name,
    owner: item.assignee ?? "项目团队",
    dateRange: item.is_milestone
      ? formatDate(item.end ?? item.start)
      : `${formatDate(item.start)} - ${formatDate(item.end)}`,
    progress: clampProgress(item.progress),
    status: item.status || "计划中",
    critical: item.critical,
    isMilestone: item.is_milestone,
  }));
}

function normalizeInsights(insights: ProjectInsight[]): DashboardInsight[] {
  if (insights.length === 0) return DEMO_INSIGHTS;
  return insights.slice(0, 5).map((insight) => ({
    id: insight.id,
    title: insight.title,
    detail: insight.detail,
    tone:
      insight.kind === "risk"
        ? "danger"
        : insight.kind === "decision"
          ? "warning"
          : "primary",
    time: formatDate(insight.created_at, "刚刚"),
  }));
}

function normalizeArtifacts(artifacts: ProjectArtifact[]): DashboardArtifact[] {
  if (artifacts.length === 0) return DEMO_ARTIFACTS;
  return artifacts.slice(0, 5).map((artifact) => ({
    id: artifact.id,
    title: artifact.title,
    type: artifact.type || artifact.source || "file",
  }));
}

function taskGroups(tasks: DashboardTask[]) {
  return {
    todo: tasks.filter((task) => task.status === "todo"),
    doing: tasks.filter((task) => task.status === "doing"),
    blocked: tasks.filter((task) => task.status === "blocked"),
    done: tasks.filter(
      (task) => task.status === "done" || task.status === "cancelled",
    ),
  };
}

function initials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "AI";
  return trimmed.slice(0, 2).toUpperCase();
}

type CompanyPageKey =
  | "home"
  | "projects"
  | "tasks"
  | "milestones"
  | "ai";

function getCompanyPage(pathname: string): CompanyPageKey {
  if (pathname.endsWith("/projects")) return "projects";
  if (pathname.endsWith("/tasks")) return "tasks";
  if (pathname.endsWith("/milestones")) return "milestones";
  if (pathname.endsWith("/ai")) return "ai";
  return "home";
}

export default function CompanyWorkbenchPage() {
  const { data: projects = [], isLoading } = useCompanyProjects();
  const location = useLocation();
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [budgetTier, setBudgetTier] = useState<ProjectBudgetTier>("standard");
  const [horizonDays, setHorizonDays] = useState(90);
  const createBlueprint = useCreateProjectBlueprint();
  const deleteProject = useDeleteCompanyProject();

  const activeProject = useMemo(() => {
    if (projects.length === 0) return null;
    return (
      projects.find((project) => project.id === activeProjectId) ??
      projects[0] ??
      null
    );
  }, [activeProjectId, projects]);

  const { data: milestones = [] } = useProjectMilestones(activeProject?.id);
  const { data: tasks = [] } = useProjectTasks(activeProject?.id);
  const { data: artifacts = [] } = useProjectArtifacts(activeProject?.id);
  const { data: insights = [] } = useProjectInsights(activeProject?.id);
  const { data: gantt = [] } = useProjectGantt(activeProject?.id);

  const dashboardTasks = useMemo(() => normalizeTasks(tasks), [tasks]);
  const dashboardMilestones = useMemo(
    () => normalizeMilestones(milestones),
    [milestones],
  );
  const dashboardGantt = useMemo(() => normalizeGantt(gantt), [gantt]);
  const dashboardInsights = useMemo(
    () => normalizeInsights(insights),
    [insights],
  );
  const dashboardArtifacts = useMemo(
    () => normalizeArtifacts(artifacts),
    [artifacts],
  );

  const progress = projectProgress(milestones, tasks);
  const completedTaskCount =
    tasks.length > 0
      ? tasks.filter((task) => task.status === "done").length
      : 32;
  const totalTaskCount = tasks.length > 0 ? tasks.length : 47;
  const pendingCount =
    tasks.length > 0
      ? tasks.filter(
          (task) => task.status !== "done" && task.status !== "cancelled",
        ).length
      : 12;
  const approvalCount =
    insights.length > 0
      ? insights.filter((insight) => insight.kind === "decision").length
      : 3;
  const aiRunningCount =
    tasks.length > 0
      ? tasks.filter((task) => task.source === "agent" || task.status === "doing")
          .length
      : 8;
  const dueSoonCount =
    tasks.length > 0
      ? tasks.filter((task) => task.status !== "done" && task.due_at).length
      : 5;
  const companyPage = getCompanyPage(location.pathname);

  const handleCreateProject = async (raw: string) => {
    const idea = raw.trim() || QUICK_PROMPTS[0] || "";
    if (createBlueprint.isPending) return;
    const result = await createBlueprint.mutateAsync({
      prompt: idea,
      budget_tier: budgetTier,
      horizon_days: horizonDays,
      metadata: { workbench: "company" },
    });
    setActiveProjectId(result.project.id);
    setPrompt("");
  };

  const handleDeleteProject = (project: CompanyProject) => {
    const confirmed = window.confirm(`删除项目「${project.name}」？`);
    if (!confirmed) return;
    deleteProject.mutate(project.id, {
      onSuccess: () => {
        if (activeProjectId === project.id) setActiveProjectId(null);
      },
    });
  };

  return (
    <CompanyShell>
      {companyPage === "home" ? (
        <HomeDashboardPage
          prompt={prompt}
          setPrompt={setPrompt}
          budgetTier={budgetTier}
          setBudgetTier={setBudgetTier}
          horizonDays={horizonDays}
          setHorizonDays={setHorizonDays}
          submitting={createBlueprint.isPending}
          onCreateProject={() => void handleCreateProject(prompt)}
          projects={projects}
          tasks={dashboardTasks}
          milestones={dashboardMilestones}
          insights={dashboardInsights}
          progress={progress}
          pendingCount={pendingCount}
          approvalCount={approvalCount}
          aiRunningCount={aiRunningCount}
          dueSoonCount={dueSoonCount}
        />
      ) : null}

      {companyPage === "projects" ? (
        <ProjectDetailPage
          project={activeProject}
          projects={projects}
          loading={isLoading}
          progress={progress}
          completedTaskCount={completedTaskCount}
          totalTaskCount={totalTaskCount}
          tasks={dashboardTasks}
          gantt={dashboardGantt}
          milestones={dashboardMilestones}
          insights={dashboardInsights}
          artifacts={dashboardArtifacts}
          activeProjectId={activeProject?.id ?? null}
          deletingProjectId={deleteProject.variables ?? null}
          onSelectProject={setActiveProjectId}
          onDeleteProject={handleDeleteProject}
        />
      ) : null}

      {companyPage === "milestones" ? (
        <MilestoneRoutePage
          projectName={activeProject?.name ?? "智能硬件产品开发"}
          milestones={dashboardMilestones}
          progress={progress}
          insights={dashboardInsights}
        />
      ) : null}

      {companyPage === "tasks" ? (
        <TasksPage
          task={
            dashboardTasks.find((task) => task.status === "doing") ??
            dashboardTasks[0] ??
            DEMO_TASKS[0]!
          }
          tasks={dashboardTasks}
          project={activeProject}
          artifacts={dashboardArtifacts}
        />
      ) : null}

      {companyPage === "ai" ? (
        <AgentPanel
          projectName={activeProject?.name ?? "智能硬件产品开发"}
          insights={dashboardInsights}
          artifacts={dashboardArtifacts}
        />
      ) : null}
    </CompanyShell>
  );
}

function CompanyShell({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="min-h-full bg-[#f4f7fb] text-slate-950 dark:bg-slate-950 dark:text-slate-50">
      <div className="mx-auto w-full max-w-[1520px] space-y-3 p-3">
        <main className="min-w-0 space-y-3">{children}</main>
      </div>
    </div>
  );
}

function HomeDashboardPage({
  prompt,
  setPrompt,
  budgetTier,
  setBudgetTier,
  horizonDays,
  setHorizonDays,
  submitting,
  onCreateProject,
  projects,
  tasks,
  milestones,
  insights,
  progress,
  pendingCount,
  approvalCount,
  aiRunningCount,
  dueSoonCount,
}: {
  prompt: string;
  setPrompt: (value: string) => void;
  budgetTier: ProjectBudgetTier;
  setBudgetTier: (value: ProjectBudgetTier) => void;
  horizonDays: number;
  setHorizonDays: (value: number) => void;
  submitting: boolean;
  onCreateProject: () => void;
  projects: CompanyProject[];
  tasks: DashboardTask[];
  milestones: DashboardMilestone[];
  insights: DashboardInsight[];
  progress: number;
  pendingCount: number;
  approvalCount: number;
  aiRunningCount: number;
  dueSoonCount: number;
}) {
  const activeTasks = tasks.filter((task) => task.status === "doing");
  const dueTasks = tasks.filter(
    (task) => task.status !== "done" && task.status !== "cancelled",
  );

  return (
    <>
      <DashboardHeader
        prompt={prompt}
        setPrompt={setPrompt}
        budgetTier={budgetTier}
        setBudgetTier={setBudgetTier}
        horizonDays={horizonDays}
        setHorizonDays={setHorizonDays}
        submitting={submitting}
        onCreateProject={onCreateProject}
      />
      <div className="grid gap-3 xl:grid-cols-2">
        <HomeFocusCard
          title="我执行的任务"
          items={activeTasks}
          emptyText="暂无内容"
          href="/workspace/company/tasks"
        />
        <HomeFocusCard
          title="我即将逾期的任务"
          items={dueTasks.slice(0, 4)}
          emptyText="暂无内容"
          href="/workspace/company/tasks"
          tone="warning"
        />
      </div>
      <HomeParticipatingProjects
        projects={projects}
        progress={progress}
        milestones={milestones}
      />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_22rem]">
        <HomeProjectProgressTable
          projects={projects}
          milestones={milestones}
          progress={progress}
        />
        <HomeTimelinePlan milestones={milestones} />
        <SuggestionPanel insights={insights} />
      </div>
      <HomeStatsGrid
        projectCount={projects.length || 24}
        taskCount={tasks.length || 128}
        doneCount={tasks.filter((task) => task.status === "done").length || 68}
        progress={progress}
      />
      <div className="grid gap-3 xl:grid-cols-4">
        <QueueCard
          title="我的待办"
          badge={pendingCount}
          items={tasks.filter((task) => task.status !== "done").slice(0, 5)}
        />
        <ApprovalCard approvalCount={approvalCount} />
        <AgentExecutionCard tasks={tasks} aiRunningCount={aiRunningCount} />
        <RiskCard dueSoonCount={dueSoonCount} insights={insights} />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/80 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
        <span>小贴士：您有 3 个项目预计本周可完成关键里程碑，保持当前进度。</span>
        <Link
          to="/workspace/company/projects"
          className="inline-flex items-center gap-1 text-xs font-medium text-blue-600"
        >
          自定义工作台
          <ArrowRightIcon className="size-3.5" />
        </Link>
      </div>
    </>
  );
}

function HomeFocusCard({
  title,
  items,
  emptyText,
  href,
  tone = "primary",
}: {
  title: string;
  items: DashboardTask[];
  emptyText: string;
  href: string;
  tone?: "primary" | "warning";
}) {
  return (
    <section className="min-h-[300px] rounded-lg border border-white/80 bg-white p-5 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-normal text-slate-950 dark:text-white">
          {title}
        </h2>
        <Link
          to={href}
          className="text-xs font-medium text-blue-600 transition hover:text-blue-500"
        >
          查看全部
        </Link>
      </div>
      {items.length > 0 ? (
        <div className="mt-5 space-y-3">
          {items.slice(0, 4).map((task) => (
            <Link
              key={task.id}
              to="/workspace/company/tasks"
              className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-3 transition hover:bg-blue-50 dark:bg-slate-950 dark:hover:bg-blue-950/40"
            >
              <span
                className={cn(
                  "size-2 rounded-full",
                  tone === "warning" ? "bg-orange-400" : "bg-blue-500",
                )}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-slate-800 dark:text-slate-100">
                  {task.title}
                </span>
                <span className="mt-1 block truncate text-xs text-slate-500">
                  {task.owner} · {task.source}
                </span>
              </span>
              <span className="shrink-0 text-xs text-slate-500">{task.dueLabel}</span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="grid min-h-[210px] place-items-center text-center text-slate-400">
          <div>
            <ClipboardListIcon className="mx-auto size-10 stroke-1" />
            <div className="mt-3 text-sm">{emptyText}</div>
          </div>
        </div>
      )}
    </section>
  );
}

function HomeParticipatingProjects({
  projects,
  progress,
  milestones,
}: {
  projects: CompanyProject[];
  progress: number;
  milestones: DashboardMilestone[];
}) {
  const rows =
    projects.length > 0
      ? projects.slice(0, 4).map((project, index) => ({
          id: project.id,
          name: project.name,
          status: STATUS_LABELS[project.status],
          date:
            project.target_end_date || project.start_date
              ? `${formatLongDate(project.start_date, "未设定")} - ${formatLongDate(project.target_end_date, "未设定")}`
              : "未设定时间范围",
          progress: index === 0 ? progress : milestones[index]?.progress ?? 0,
        }))
      : [
          { id: "demo-home-project-1", name: "硬件研发制造", status: "暂无状态", date: "未设定时间范围", progress: 0 },
          { id: "demo-home-project-2", name: "智能床垫项目", status: "暂无状态", date: "未设定时间范围", progress: 0 },
        ];

  return (
    <section className="rounded-lg border border-white/80 bg-white p-5 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold tracking-normal text-slate-950 dark:text-white">
          我参与的项目
        </h2>
        <Link
          to="/workspace/company/projects"
          className="text-xs font-medium text-blue-600 transition hover:text-blue-500"
        >
          查看更多
        </Link>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {rows.map((row, index) => (
          <Link
            key={row.id}
            to="/workspace/company/projects"
            className="min-w-0 rounded-lg border border-slate-100 bg-slate-50/70 p-3 transition hover:border-blue-200 hover:bg-blue-50 dark:border-slate-800 dark:bg-slate-950 dark:hover:border-blue-800 dark:hover:bg-blue-950/40"
          >
            <span className="flex min-w-0 items-start gap-3">
              <span
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-lg text-white",
                  index === 0 ? "bg-blue-500" : "bg-orange-300",
                )}
              >
                <BriefcaseBusinessIcon className="size-4.5" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {row.name}
                </span>
                <span className="mt-1 block text-xs text-slate-500">
                  {row.progress}% 完成
                </span>
              </span>
              <ChevronRightIcon className="mt-0.5 size-4 shrink-0 text-blue-500" />
            </span>
            <span className="mt-3 flex items-center justify-between gap-2 text-xs text-slate-500">
              <span className="truncate">{row.date}</span>
              <span className="inline-flex shrink-0 items-center gap-1">
                <span className="inline-block size-2 rounded-full bg-slate-300" />
                {row.status}
              </span>
            </span>
            <span className="mt-3 block h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <span
                className="block h-full rounded-full bg-blue-500"
                style={{ width: `${clampProgress(row.progress)}%` }}
              />
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function ProjectDetailPage({
  project,
  projects,
  loading,
  progress,
  completedTaskCount,
  totalTaskCount,
  tasks,
  gantt,
  milestones,
  insights,
  artifacts,
  activeProjectId,
  deletingProjectId,
  onSelectProject,
  onDeleteProject,
}: {
  project: CompanyProject | null;
  projects: CompanyProject[];
  loading: boolean;
  progress: number;
  completedTaskCount: number;
  totalTaskCount: number;
  tasks: DashboardTask[];
  gantt: DashboardGanttItem[];
  milestones: DashboardMilestone[];
  insights: DashboardInsight[];
  artifacts: DashboardArtifact[];
  activeProjectId: string | null;
  deletingProjectId: string | null;
  onSelectProject: (id: string) => void;
  onDeleteProject: (project: CompanyProject) => void;
}) {
  const projectName = project?.name ?? "智能硬件产品开发";
  const projectDescription =
    project?.description || "围绕任务、文件、甘特图、统计和自动化协作推进项目交付。";

  return (
    <section className="overflow-hidden rounded-lg border border-white/80 bg-white shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <ProjectWorkspaceHeader
        project={project}
        projectName={projectName}
        description={projectDescription}
      />
      <div className="grid min-h-[720px] lg:grid-cols-[18rem_minmax(0,1fr)]">
        <ProjectWorkspaceSidebar
          projects={projects}
          loading={loading}
          activeProjectId={activeProjectId}
          deletingProjectId={deletingProjectId}
          onSelectProject={onSelectProject}
          onDeleteProject={onDeleteProject}
        />
        <main className="min-w-0 bg-slate-50/70 dark:bg-slate-950/60">
          <ProjectWorkspaceToolbar
            progress={progress}
            completedTaskCount={completedTaskCount}
            totalTaskCount={totalTaskCount}
          />
          <ProjectWorkspaceBoard tasks={tasks} />
          <div className="px-4 pb-4">
            <ProjectMilestoneStrip milestones={milestones} />
          </div>
          <div className="grid gap-3 border-t border-slate-200/70 p-4 dark:border-slate-800 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <ProjectPlanGantt items={gantt} />
            <div className="space-y-3">
              <ProjectWorkspaceSummary
                project={project}
                progress={progress}
                milestones={milestones}
                artifacts={artifacts}
              />
              <DecisionPanel />
              <SuggestionPanel insights={insights} compact />
            </div>
          </div>
        </main>
      </div>
    </section>
  );
}

function ProjectWorkspaceHeader({
  project,
  projectName,
  description,
}: {
  project: CompanyProject | null;
  projectName: string;
  description: string;
}) {
  const tabs = ["任务", "文件", "甘特图", "项目信息", "统计", "工时", "+"];
  return (
    <header className="border-b border-slate-100 bg-white px-4 pt-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full border border-slate-200 text-slate-500 transition hover:bg-slate-50 dark:border-slate-700"
            title="返回"
          >
            <ChevronRightIcon className="size-4 rotate-180" />
          </button>
          <div className="grid size-9 place-items-center rounded-lg bg-gradient-to-br from-orange-100 to-blue-100 text-blue-600">
            <BriefcaseBusinessIcon className="size-5" />
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <h2 className="truncate text-xl font-semibold tracking-normal text-slate-950 dark:text-white">
                {projectName}
              </h2>
              <ChevronRightIcon className="size-4 text-slate-400" />
              <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">
                {project ? STATUS_LABELS[project.status] : "进行中"}
              </span>
              <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-200">
                {project ? STAGE_LABELS[project.stage] : "原型"}
              </span>
            </div>
            <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">
              {description}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <AvatarStack />
          <button
            type="button"
            className="h-9 rounded-lg border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
          >
            邀请
          </button>
          <button
            type="button"
            className="h-9 rounded-lg px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            自动化
          </button>
          <button
            type="button"
            className="h-9 rounded-lg px-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            自定义
          </button>
          <button
            type="button"
            className="grid size-9 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-50 dark:hover:bg-slate-800"
            title="菜单"
          >
            <MoreHorizontalIcon className="size-4" />
          </button>
        </div>
      </div>
      <nav className="mt-3 flex gap-7 overflow-x-auto text-sm font-medium text-slate-500">
        {tabs.map((tab, index) => (
          <button
            key={tab}
            type="button"
            className={cn(
              "shrink-0 border-b-2 pb-3 transition",
              index === 0
                ? "border-blue-600 text-blue-600"
                : "border-transparent hover:text-slate-900 dark:hover:text-white",
            )}
          >
            {tab}
          </button>
        ))}
      </nav>
    </header>
  );
}

function ProjectWorkspaceSidebar({
  projects,
  loading,
  activeProjectId,
  deletingProjectId,
  onSelectProject,
  onDeleteProject,
}: {
  projects: CompanyProject[];
  loading: boolean;
  activeProjectId: string | null;
  deletingProjectId: string | null;
  onSelectProject: (id: string) => void;
  onDeleteProject: (project: CompanyProject) => void;
}) {
  return (
    <aside className="border-r border-slate-100 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <label className="relative block">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          className="h-10 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none transition focus:border-blue-300 focus:bg-white focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950"
          placeholder="搜索分组或视图..."
        />
      </label>
      <div className="mt-5 flex items-center justify-between text-sm font-semibold text-slate-900 dark:text-white">
        视图
        <button
          type="button"
          className="grid size-7 place-items-center rounded-lg text-slate-400 transition hover:bg-slate-50 hover:text-slate-700 dark:hover:bg-slate-800"
          title="新增视图"
        >
          <PlusIcon className="size-4" />
        </button>
      </div>
      <div className="mt-3 space-y-1">
        {[
          { label: "所有任务", icon: ClipboardListIcon, active: true },
          { label: "我执行的", icon: UsersRoundIcon, active: false },
          { label: "我创建的", icon: FileTextIcon, active: false },
        ].map(({ label, icon: ViewIcon, active }) => {
          return (
            <button
              key={label}
              type="button"
              className={cn(
                "flex h-10 w-full items-center gap-2 rounded-lg px-3 text-sm transition",
                active
                  ? "bg-slate-100 font-semibold text-slate-950 dark:bg-slate-800 dark:text-white"
                  : "text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800",
              )}
            >
              <ViewIcon className="size-4 text-blue-500" />
              {label}
            </button>
          );
        })}
      </div>
      <div className="mt-6 border-t border-slate-100 pt-4 dark:border-slate-800">
        <div className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">
          项目
        </div>
        {loading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, index) => (
              <div
                key={index}
                className="h-9 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800"
              />
            ))}
          </div>
        ) : projects.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-xs leading-5 text-slate-500 dark:border-slate-700">
            当前展示参考项目，创建项目后会出现在这里。
          </div>
        ) : (
          <div className="space-y-1">
            {projects.slice(0, 6).map((item) => {
              const active = item.id === activeProjectId;
              return (
                <div
                  key={item.id}
                  className={cn(
                    "group flex items-center gap-2 rounded-lg px-2 py-2 text-sm",
                    active
                      ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-200"
                      : "text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onSelectProject(item.id)}
                    className="min-w-0 flex-1 truncate text-left font-medium"
                  >
                    {item.name}
                  </button>
                  <button
                    type="button"
                    disabled={deletingProjectId === item.id}
                    onClick={() => onDeleteProject(item)}
                    className="grid size-6 place-items-center rounded-md text-slate-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 group-hover:opacity-100 disabled:opacity-50"
                    title="删除项目"
                  >
                    <Trash2Icon className="size-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}

function ProjectWorkspaceToolbar({
  progress,
  completedTaskCount,
  totalTaskCount,
}: {
  progress: number;
  completedTaskCount: number;
  totalTaskCount: number;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex min-w-0 items-center gap-3">
        <div className="grid size-8 place-items-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950">
          <ClipboardListIcon className="size-4" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
            所有任务
            <ChevronRightIcon className="size-4 rotate-90 text-slate-400" />
          </div>
          <div className="mt-0.5 text-xs text-slate-500">
            {completedTaskCount} / {totalTaskCount} 已完成，整体进度 {clampProgress(progress)}%
          </div>
        </div>
      </div>
      <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
        {["看板", "自定义列", "仅父任务", "按创建时间"].map((item, index) => (
          <button
            key={item}
            type="button"
            className={cn(
              "h-8 rounded-lg px-2.5 text-xs font-medium transition",
              index === 0
                ? "bg-white text-slate-900 shadow-sm ring-1 ring-slate-200 dark:bg-slate-950 dark:text-white dark:ring-slate-700"
                : "text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800",
            )}
          >
            {item}
          </button>
        ))}
        <label className="relative w-44">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            className="h-8 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-xs outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950"
            placeholder="搜索标题和 ID"
          />
        </label>
        <Button type="button" size="sm" className="h-8 rounded-lg px-3">
          <PlusIcon className="size-4" />
          创建任务
        </Button>
      </div>
    </div>
  );
}

function ProjectWorkspaceBoard({ tasks }: { tasks: DashboardTask[] }) {
  const sourceTasks = tasks.length > 0 ? tasks : DEMO_TASKS;
  const columns = ["立项", "工业设计", "硬件设计", "软件设计"].map(
    (title, index) => ({
      title,
      items: sourceTasks.filter((_, taskIndex) => taskIndex % 4 === index),
    }),
  );

  return (
    <div className="overflow-x-auto p-4">
      <div className="flex min-h-[330px] min-w-[980px] gap-3">
        {columns.map((column) => (
          <section
            key={column.title}
            className="flex w-[17.5rem] shrink-0 flex-col rounded-xl bg-slate-100/80 p-3 dark:bg-slate-900"
          >
            <div className="mb-3 flex items-center justify-between">
              <div className="text-base font-semibold text-slate-900 dark:text-white">
                {column.title}
              </div>
              <MoreHorizontalIcon className="size-4 text-slate-400" />
            </div>
            <div className="space-y-2">
              {column.items.slice(0, 4).map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
              <button
                type="button"
                className="flex h-10 w-full items-center justify-center rounded-lg border border-slate-200 bg-white text-lg text-slate-500 transition hover:border-blue-200 hover:text-blue-600 dark:border-slate-700 dark:bg-slate-950"
                title="新增任务"
              >
                +
              </button>
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function ProjectWorkspaceSummary({
  project,
  progress,
  milestones,
  artifacts,
}: {
  project: CompanyProject | null;
  progress: number;
  milestones: DashboardMilestone[];
  artifacts: DashboardArtifact[];
}) {
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <PanelTitle title="项目信息" />
      <div className="mt-4 flex items-center gap-4">
        <ProgressRing progress={progress} compact />
        <div className="min-w-0 text-xs text-slate-500">
          <div className="text-sm font-semibold text-slate-900 dark:text-white">
            {project?.name ?? "智能硬件产品开发"}
          </div>
          <div className="mt-1">
            {milestones.filter((item) => item.progress >= 100).length} 个里程碑已完成
          </div>
          <div className="mt-1">{artifacts.length} 个交付物</div>
        </div>
      </div>
      <div className="mt-4 space-y-2 text-xs text-slate-600 dark:text-slate-300">
        <ProjectMetaRow
          label="开始时间"
          value={formatLongDate(project?.start_date, "2024-11-01")}
        />
        <ProjectMetaRow
          label="结束时间"
          value={formatLongDate(project?.target_end_date, "2025-02-28")}
        />
        <ProjectMetaRow
          label="剩余"
          value={`${remainingDays(project?.target_end_date)} 天`}
        />
      </div>
    </section>
  );
}

function MilestoneRoutePage({
  projectName,
  milestones,
  progress,
  insights,
}: {
  projectName: string;
  milestones: DashboardMilestone[];
  progress: number;
  insights: DashboardInsight[];
}) {
  return (
    <>
      <CompanyTopBar
        title="里程碑 / 路线图"
        primaryAction="新建里程碑"
        secondaryAction="导出路线图"
      />
      <MilestoneHero projectName={projectName} milestones={milestones} />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-3">
          <MilestoneProgressSummary progress={progress} milestones={milestones} />
          <MilestonePanel milestones={milestones} />
        </div>
        <MilestoneRiskPanel insights={insights} />
      </div>
    </>
  );
}

function TasksPage({
  task,
  tasks,
  project,
  artifacts,
}: {
  task: DashboardTask;
  tasks: DashboardTask[];
  project: CompanyProject | null;
  artifacts: DashboardArtifact[];
}) {
  return (
    <>
      <CompanyTopBar title="任务 / 看板" primaryAction="新增任务" />
      <TaskBoard tasks={tasks} />
      <TaskDetailPanel task={task} project={project} artifacts={artifacts} />
    </>
  );
}

function CompanyTopBar({
  title,
  primaryAction,
  secondaryAction,
}: {
  title: string;
  primaryAction?: string;
  secondaryAction?: string;
}) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/80 bg-white px-4 py-3 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="min-w-0">
        <div className="text-xl font-semibold tracking-normal text-slate-950 dark:text-white">
          {title}
        </div>
      </div>
      <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
        <label className="relative min-w-[220px] max-w-md flex-1">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            placeholder="搜索项目、任务、文档..."
            className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none transition focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950"
          />
        </label>
        {secondaryAction ? (
          <button
            type="button"
            className="h-9 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300"
          >
            {secondaryAction}
          </button>
        ) : null}
        {primaryAction ? (
          <Button type="button" size="sm" className="h-9 rounded-lg px-3">
            <PlusIcon className="size-4" />
            {primaryAction}
          </Button>
        ) : null}
        <button
          type="button"
          className="grid size-9 place-items-center rounded-lg border border-slate-200 bg-white text-slate-500 dark:border-slate-700 dark:bg-slate-950"
          title="通知"
        >
          <BellIcon className="size-4" />
        </button>
      </div>
    </header>
  );
}

function HomeStatsGrid({
  projectCount,
  taskCount,
  doneCount,
  progress,
}: {
  projectCount: number;
  taskCount: number;
  doneCount: number;
  progress: number;
}) {
  const stats = [
    {
      label: "项目总数",
      value: projectCount,
      helper: "较上周 +20%",
      visual: "line-blue",
    },
    {
      label: "任务总数",
      value: taskCount,
      helper: "较上周 +18%",
      visual: "line-green",
    },
    {
      label: "已完成任务",
      value: doneCount,
      helper: `完成率 ${clampProgress(progress)}%`,
      visual: "ring",
    },
    {
      label: "节省工时",
      value: "186.5h",
      helper: "较上周 +23.5h",
      visual: "bars",
    },
    {
      label: "协作效率",
      value: "92%",
      helper: "较上周 +6%",
      visual: "ring-blue",
    },
  ];

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
      {stats.map((stat) => (
        <div
          key={stat.label}
          className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900"
        >
          <div className="text-xs font-medium text-blue-600">{stat.label}</div>
          <div className="mt-3 flex items-center justify-between gap-3">
            <div>
              <div className="text-3xl font-semibold tracking-normal text-slate-950 dark:text-white">
                {stat.value}
              </div>
              <div className="mt-2 text-xs text-slate-500">{stat.helper}</div>
            </div>
            <HomeStatVisual kind={stat.visual} progress={progress} />
          </div>
        </div>
      ))}
    </div>
  );
}

function HomeStatVisual({ kind, progress }: { kind: string; progress: number }) {
  if (kind === "ring" || kind === "ring-blue") {
    return (
      <div
        className="grid size-16 place-items-center rounded-full"
        style={{
          background: `conic-gradient(${kind === "ring" ? "#8b5cf6" : "#2563eb"} ${clampProgress(progress) * 3.6}deg, #e8eef7 0deg)`,
        }}
      >
        <div className="size-11 rounded-full bg-white dark:bg-slate-900" />
      </div>
    );
  }
  if (kind === "bars") {
    return (
      <div className="flex h-16 items-end gap-2">
        {[34, 50, 42, 62, 56].map((height, index) => (
          <span
            key={index}
            className="w-2 rounded-full bg-orange-300"
            style={{ height }}
          />
        ))}
      </div>
    );
  }
  const green = kind === "line-green";
  return (
    <svg viewBox="0 0 90 54" className="h-16 w-24" aria-hidden="true">
      <polyline
        points="4,35 16,31 26,36 38,22 50,25 62,18 72,28 86,12"
        fill="none"
        stroke={green ? "#22c55e" : "#2563eb"}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="4"
      />
    </svg>
  );
}

function QueueCard({
  title,
  badge,
  items,
}: {
  title: string;
  badge: number;
  items: DashboardTask[];
}) {
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <CardHeaderLink title={title} badge={badge} href="/workspace/company/tasks" />
      <div className="mt-4 space-y-3">
        {items.slice(0, 5).map((task) => (
          <div key={task.id} className="flex items-center gap-3 text-sm">
            <span
              className={cn(
                "size-1.5 rounded-full",
                task.priority === "urgent" ? "bg-red-500" : "bg-blue-500",
              )}
            />
            <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
              {task.title}
            </span>
            <span className="rounded-md bg-blue-50 px-2 py-1 text-[11px] text-blue-700">
              {task.source}
            </span>
            <span className="text-xs text-slate-500">{task.dueLabel}</span>
          </div>
        ))}
      </div>
      <CardFooterLink href="/workspace/company/tasks" text="查看全部待办" />
    </section>
  );
}

function ApprovalCard({ approvalCount }: { approvalCount: number }) {
  const approvals = [
    ["用户研究计划方案", "项目方案", "张三"],
    ["AI 功能需求文档", "需求文档", "李四"],
    ["预算申请 - Q2", "财务申请", "王五"],
  ];
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <CardHeaderLink title="待我审批" badge={approvalCount} href="/workspace/company/tasks" />
      <div className="mt-4 space-y-4">
        {approvals.map(([title, tag, owner]) => (
          <div key={title} className="flex items-center gap-3 text-sm">
            <span className="size-2 rounded-full border border-blue-500" />
            <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
              {title}
            </span>
            <span className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700">
              {tag}
            </span>
            <span className="text-xs text-slate-500">{owner}</span>
          </div>
        ))}
      </div>
      <CardFooterLink href="/workspace/company/tasks" text="查看全部审批" />
    </section>
  );
}

function AgentExecutionCard({
  tasks,
  aiRunningCount,
}: {
  tasks: DashboardTask[];
  aiRunningCount: number;
}) {
  const rows = (tasks.length > 0 ? tasks : DEMO_TASKS).slice(0, 4);
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <CardHeaderLink title="Agent 执行中" badge={aiRunningCount} href="/workspace/company/ai" />
      <div className="mt-4 space-y-3">
        {rows.map((task) => (
          <div key={task.id}>
            <div className="mb-1 flex items-center gap-2 text-xs">
              <Avatar name={task.owner} size="sm" tone="primary" />
              <span className="min-w-0 flex-1 truncate text-slate-700 dark:text-slate-200">
                {task.title.replace("PRD", "需求分析")} Agent
              </span>
              <span className="text-blue-600">执行中</span>
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {task.progress}%
              </span>
            </div>
            <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-blue-600"
                style={{ width: `${task.progress}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <CardFooterLink href="/workspace/company/ai" text="查看全部智能体" />
    </section>
  );
}

function RiskCard({
  dueSoonCount,
  insights,
}: {
  dueSoonCount: number;
  insights: DashboardInsight[];
}) {
  const riskItems = insights.length
    ? insights.slice(0, 2)
    : [
        {
          id: "risk-1",
          title: "项目进度风险",
          detail: "AI 客服升级项目进度落后于计划 3 天",
          tone: "danger" as const,
          time: "今天",
        },
        {
          id: "risk-2",
          title: "资源分配风险",
          detail: "视觉中台建设需求变更频繁，建议评估",
          tone: "warning" as const,
          time: "今天",
        },
      ];
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <CardHeaderLink title="风险提醒" badge={dueSoonCount} href="/workspace/company/milestones" />
      <div className="mt-4 space-y-3">
        {riskItems.map((item) => (
          <div
            key={item.id}
            className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-3 dark:border-slate-800 dark:bg-slate-950"
          >
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800 dark:text-slate-100">
              <AlertTriangleIcon className="size-4 text-red-500" />
              {item.title}
            </div>
            <p className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">
              {item.detail}
            </p>
            <Link
              to="/workspace/company/milestones"
              className="mt-2 inline-flex text-xs font-medium text-blue-600"
            >
              查看详情 →
            </Link>
          </div>
        ))}
      </div>
      <CardFooterLink href="/workspace/company/milestones" text="查看全部风险" />
    </section>
  );
}

function HomeProjectProgressTable({
  projects,
  milestones,
  progress,
}: {
  projects: CompanyProject[];
  milestones: DashboardMilestone[];
  progress: number;
}) {
  const rows =
    projects.length > 0
      ? projects.slice(0, 5).map((project, index) => ({
          id: project.id,
          name: project.name,
          progress: index === 0 ? progress : milestones[index]?.progress ?? 45,
          status: STATUS_LABELS[project.status],
          owner: ["张晓明", "李四", "王五", "赵六", "孙七"][index] ?? "项目团队",
        }))
      : [
          ["AI 客服升级项目", 68, "进行中", "张晓明"],
          ["数据中台建设", 45, "进行中", "李四"],
          ["智能推荐优化", 80, "进行中", "王五"],
          ["用户增长活动", 25, "规划中", "赵六"],
          ["知识库重构", 60, "进行中", "孙七"],
        ].map(([name, rowProgress, status, owner], index) => ({
          id: `home-project-${index}`,
          name: String(name),
          progress: Number(rowProgress),
          status: String(status),
          owner: String(owner),
        }));

  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <PanelTitle title="项目进度概览" action="查看全部项目" />
      <div className="mt-4 overflow-hidden rounded-lg border border-slate-100 dark:border-slate-800">
        <div className="grid grid-cols-[minmax(9rem,1fr)_7rem_5rem_5rem] bg-slate-50 px-3 py-2 text-xs font-medium text-slate-500 dark:bg-slate-950">
          <span>项目</span>
          <span>进度</span>
          <span>状态</span>
          <span>负责人</span>
        </div>
        {rows.map((row) => (
          <div
            key={row.id}
            className="grid grid-cols-[minmax(9rem,1fr)_7rem_5rem_5rem] items-center border-t border-slate-100 px-3 py-3 text-xs dark:border-slate-800"
          >
            <span className="truncate font-medium text-slate-700 dark:text-slate-200">
              {row.name}
            </span>
            <span className="flex items-center gap-2">
              <span className="h-1.5 flex-1 rounded-full bg-slate-100 dark:bg-slate-800">
                <span
                  className="block h-full rounded-full bg-blue-600"
                  style={{ width: `${clampProgress(row.progress)}%` }}
                />
              </span>
              <span>{clampProgress(row.progress)}%</span>
            </span>
            <span className="text-emerald-600">{row.status}</span>
            <span className="truncate text-slate-500">{row.owner}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function HomeTimelinePlan({ milestones }: { milestones: DashboardMilestone[] }) {
  const rows = milestones.slice(0, 5);
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <PanelTitle title="项目时间线（近7天）" action="查看完整计划" />
      <div className="mt-4 space-y-4">
        {rows.map((item, index) => (
          <div key={item.id} className="grid grid-cols-[7rem_minmax(0,1fr)_4rem] items-center gap-3 text-xs">
            <div className="flex items-center gap-2 text-slate-600 dark:text-slate-300">
              <span
                className={cn(
                  "size-2 rounded-sm",
                  index < 2 ? "bg-emerald-500" : index < 4 ? "bg-blue-600" : "bg-slate-300",
                )}
              />
              <span className="truncate">{item.title}</span>
            </div>
            <div className="h-3 rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className={cn(
                  "h-full rounded-full",
                  index < 2 ? "bg-emerald-500" : "bg-blue-600",
                )}
                style={{
                  width: `${Math.max(22, item.progress || 30 + index * 12)}%`,
                }}
              />
            </div>
            <span className="text-right text-blue-600">{item.status}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function SuggestionPanel({
  insights,
  compact = false,
}: {
  insights: DashboardInsight[];
  compact?: boolean;
}) {
  const rows = insights.length
    ? insights.slice(0, compact ? 3 : 4)
    : DEMO_INSIGHTS.slice(0, compact ? 3 : 4);
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center gap-2">
        <SparklesIcon className="size-4 text-blue-600" />
        <div className="text-sm font-semibold text-slate-900 dark:text-white">
          AI 建议下一步
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {rows.map((item) => (
          <div
            key={item.id}
            className="rounded-lg bg-slate-50 p-3 dark:bg-slate-950"
          >
            <div className="text-sm font-medium text-slate-800 dark:text-slate-100">
              {item.title}
            </div>
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">
              {item.detail}
            </p>
            <Link
              to="/workspace/company/ai"
              className="mt-2 inline-flex text-xs font-medium text-blue-600"
            >
              查看建议 →
            </Link>
          </div>
        ))}
      </div>
      <CardFooterLink href="/workspace/company/ai" text="查看更多建议" />
    </section>
  );
}

function ProjectMilestoneStrip({
  milestones,
}: {
  milestones: DashboardMilestone[];
}) {
  const rows = milestones.slice(0, 6);
  return (
    <section className="rounded-lg border border-white/80 bg-white px-4 py-3 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {rows.map((item, index) => (
          <div key={item.id} className="flex items-center gap-3">
            <span
              className={cn(
                "grid size-6 place-items-center rounded-full text-xs font-semibold text-white",
                item.progress >= 100
                  ? "bg-emerald-500"
                  : index === 2
                    ? "bg-blue-600"
                    : "bg-slate-300",
              )}
            >
              {index + 1}
            </span>
            <div className="min-w-0">
              <div className="truncate text-xs font-semibold text-slate-700 dark:text-slate-200">
                {item.title}
              </div>
              <div className="mt-0.5 text-[11px] text-slate-500">
                {item.dateLabel}
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ProjectPlanGantt({ items }: { items: DashboardGanttItem[] }) {
  const colors = ["bg-emerald-500", "bg-blue-500", "bg-violet-500", "bg-orange-400", "bg-cyan-500", "bg-red-500"];
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle title="项目计划（甘特图）" />
        <div className="flex gap-2">
          {["今天", "周", "月", "全部任务"].map((item, index) => (
            <button
              key={item}
              className={cn(
                "h-8 rounded-lg border px-3 text-xs",
                index === 2
                  ? "border-blue-200 bg-blue-50 text-blue-700"
                  : "border-slate-200 text-slate-500 dark:border-slate-700",
              )}
              type="button"
            >
              {item}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4 overflow-auto rounded-lg border border-slate-100 dark:border-slate-800">
        <div className="min-w-[900px]">
          <div className="grid grid-cols-[13rem_minmax(0,1fr)] bg-slate-50 text-xs text-slate-500 dark:bg-slate-950">
            <div className="grid grid-cols-[1fr_4rem] px-3 py-2">
              <span>任务名称</span>
              <span>负责人</span>
            </div>
            <div className="grid grid-cols-8 px-3 py-2 text-center">
              {["W45", "W46", "W47", "W48", "W49", "W50", "W51", "W52"].map((week) => (
                <span key={week}>{week}</span>
              ))}
            </div>
          </div>
          {items.slice(0, 12).map((item, index) => {
            const left = 5 + ((index * 9) % 56);
            const width = item.isMilestone ? 2 : Math.max(14, Math.min(34, 12 + item.progress / 4));
            return (
              <div
                key={item.id}
                className="grid grid-cols-[13rem_minmax(0,1fr)] border-t border-slate-100 dark:border-slate-800"
              >
                <div className="grid grid-cols-[1fr_4rem] items-center px-3 py-3 text-xs">
                  <span className="truncate font-medium text-slate-700 dark:text-slate-200">
                    {index + 1}. {item.title}
                  </span>
                  <span className="truncate text-slate-500">{item.owner}</span>
                </div>
                <div className="relative h-10 bg-[linear-gradient(to_right,rgba(148,163,184,.18)_1px,transparent_1px)] bg-[length:12.5%_100%]">
                  <span className="absolute left-[62%] top-0 h-full border-l border-dashed border-blue-400" />
                  <span
                    className={cn(
                      "absolute top-1/2 h-3 -translate-y-1/2 rounded-full shadow-sm",
                      item.isMilestone ? "w-3 rotate-45 rounded-sm bg-blue-600" : colors[index % colors.length],
                    )}
                    style={{
                      left: `${left}%`,
                      width: item.isMilestone ? undefined : `${width}%`,
                    }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function DecisionPanel() {
  const rows = [
    ["D-12", "确定核心芯片供应商方案", "已通过"],
    ["D-09", "确认产品外观设计方向", "已通过"],
    ["D-05", "通过需求规格说明书", "已通过"],
  ];
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <PanelTitle title="关键决策" action="添加决策" />
      <div className="mt-4 space-y-3">
        {rows.map(([id, title, status]) => (
          <div key={id} className="rounded-lg border border-slate-100 p-3 dark:border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold text-blue-600">{id}</span>
              <span className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700">
                {status}
              </span>
            </div>
            <div className="mt-2 text-sm font-medium text-slate-800 dark:text-slate-100">
              {title}
            </div>
            <Link to="/workspace/company/projects" className="mt-2 inline-flex text-xs font-medium text-blue-600">
              查看详情 →
            </Link>
          </div>
        ))}
      </div>
    </section>
  );
}

function MilestoneHero({
  projectName,
  milestones,
}: {
  projectName: string;
  milestones: DashboardMilestone[];
}) {
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-3">
        <span className="size-3 rounded-full bg-emerald-500" />
        <div className="text-base font-semibold text-slate-900 dark:text-white">
          {projectName}
        </div>
        <span className="rounded-lg bg-blue-50 px-2 py-1 text-xs text-blue-700">
          进行中
        </span>
      </div>
      <div className="mt-6 overflow-x-auto">
        <div className="relative min-w-[860px] px-5 py-8">
          <div className="absolute left-8 right-8 top-14 h-1 bg-gradient-to-r from-blue-500 via-emerald-500 via-45% to-slate-200" />
          <div className="relative grid grid-cols-6 gap-5">
            {milestones.slice(0, 6).map((item, index) => (
              <div key={item.id} className="text-center">
                <div
                  className={cn(
                    "mx-auto grid size-10 place-items-center rounded-full text-sm font-semibold text-white shadow-sm",
                    item.progress >= 100
                      ? "bg-emerald-500"
                      : index === 2
                        ? "bg-orange-500"
                        : "bg-slate-400",
                  )}
                >
                  {item.progress >= 100 ? "✓" : index + 1}
                </div>
                <div className="mt-3 text-sm font-semibold text-slate-800 dark:text-slate-100">
                  {item.title}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {item.dateLabel}
                </div>
                <div className="mt-2 text-xs text-slate-500">{item.status}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function MilestoneProgressSummary({
  progress,
  milestones,
}: {
  progress: number;
  milestones: DashboardMilestone[];
}) {
  const done = milestones.filter((item) => item.progress >= 100).length;
  const doing = milestones.filter((item) => item.progress > 0 && item.progress < 100).length;
  const pending = Math.max(0, milestones.length - done - doing);
  return (
    <section className="grid gap-3 rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900 md:grid-cols-[13rem_minmax(0,1fr)]">
      <div className="flex items-center justify-center">
        <ProgressRing progress={progress} />
      </div>
      <div className="grid items-center gap-3 sm:grid-cols-4">
        <MilestoneCount label="里程碑总数" value={milestones.length} />
        <MilestoneCount label="已完成" value={done} tone="success" />
        <MilestoneCount label="进行中" value={doing} tone="warning" />
        <MilestoneCount label="待开始" value={pending} />
      </div>
    </section>
  );
}

function MilestoneCount({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "success" | "warning";
}) {
  return (
    <div className="text-center">
      <div
        className={cn(
          "text-2xl font-semibold",
          tone === "success"
            ? "text-emerald-600"
            : tone === "warning"
              ? "text-orange-500"
              : "text-slate-800 dark:text-slate-100",
        )}
      >
        {value}
      </div>
      <div className="mt-1 text-xs text-slate-500">{label}</div>
    </div>
  );
}

function MilestoneRiskPanel({ insights }: { insights: DashboardInsight[] }) {
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center gap-2">
        <AlertTriangleIcon className="size-4 text-red-500" />
        <div className="text-sm font-semibold text-slate-900 dark:text-white">
          AI 风险预警
        </div>
      </div>
      <div className="mt-4 space-y-3">
        {(insights.length ? insights : DEMO_INSIGHTS).slice(0, 3).map((item, index) => (
          <div
            key={item.id}
            className={cn(
              "rounded-lg border p-4",
              index === 0
                ? "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/30"
                : "border-orange-200 bg-orange-50/70 dark:border-orange-900 dark:bg-orange-950/30",
            )}
          >
            <div className="font-semibold text-slate-900 dark:text-white">
              {item.title}
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {item.detail}
            </p>
            <button className="mt-3 rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600">
              查看详情
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function CardHeaderLink({
  title,
  badge,
  href,
}: {
  title: string;
  badge: number;
  href: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 text-base font-semibold text-slate-900 dark:text-white">
        <ClipboardListIcon className="size-4 text-blue-600" />
        {title}
      </div>
      <Link
        to={href}
        className="rounded-lg bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700"
      >
        {badge}
      </Link>
    </div>
  );
}

function CardFooterLink({ href, text }: { href: string; text: string }) {
  return (
    <Link
      to={href}
      className="mt-5 inline-flex w-full items-center justify-center gap-1 text-xs font-medium text-blue-600"
    >
      {text}
      <ArrowRightIcon className="size-3.5" />
    </Link>
  );
}

function DashboardHeader({
  prompt,
  setPrompt,
  budgetTier,
  setBudgetTier,
  horizonDays,
  setHorizonDays,
  submitting,
  onCreateProject,
}: {
  prompt: string;
  setPrompt: (value: string) => void;
  budgetTier: ProjectBudgetTier;
  setBudgetTier: (value: ProjectBudgetTier) => void;
  horizonDays: number;
  setHorizonDays: (value: number) => void;
  submitting: boolean;
  onCreateProject: () => void;
}) {
  return (
    <header className="relative rounded-lg border border-white/80 bg-white px-4 py-6 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="absolute right-4 top-4 flex items-center gap-2">
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200"
        >
          <FileTextIcon className="size-4" />
          卡片配置
        </button>
        <button
          type="button"
          className="grid size-9 place-items-center rounded-lg text-slate-500 transition hover:bg-slate-50 dark:hover:bg-slate-800"
          title="通知"
        >
          <BellIcon className="size-4" />
        </button>
      </div>

      <div className="mx-auto max-w-2xl pt-5 text-center">
        <div className="text-sm font-medium text-slate-500 dark:text-slate-400">
          {formatShortToday()}
        </div>
        <h1 className="mt-3 text-3xl font-semibold tracking-normal text-slate-950 dark:text-white">
          {dayPeriodGreeting()}
        </h1>

        <form
          className="mt-7 flex flex-wrap items-center justify-center gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            onCreateProject();
          }}
        >
          <label className="relative min-w-[260px] flex-1">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
            <input
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="搜索项目、任务、文档，或输入目标创建项目..."
              className="h-9 w-full rounded-lg border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm outline-none transition focus:border-blue-400 focus:bg-white focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950"
            />
          </label>
          <select
            value={budgetTier}
            onChange={(event) =>
              setBudgetTier(event.target.value as ProjectBudgetTier)
            }
            className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300"
            aria-label="预算档位"
          >
            {BUDGET_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            value={horizonDays}
            onChange={(event) => setHorizonDays(Number(event.target.value))}
            className="h-9 rounded-lg border border-slate-200 bg-white px-2 text-xs text-slate-600 outline-none dark:border-slate-700 dark:bg-slate-950 dark:text-slate-300"
            aria-label="项目周期"
          >
            {HORIZON_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <Button
            type="submit"
            size="sm"
            disabled={submitting}
            className="h-9 rounded-lg px-3"
            title="创建项目"
          >
            <PlusIcon className="size-4" />
            {submitting ? "生成中" : "创建"}
          </Button>
          <button
            type="button"
            className="inline-flex size-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-950"
            title="通知"
          >
            <BellIcon className="size-4" />
          </button>
          <div className="grid size-9 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-blue-500 text-xs font-semibold text-white">
            张
          </div>
        </form>
      </div>

      <div className="mt-5 flex gap-2 overflow-x-auto pb-1">
        {QUICK_PROMPTS.map((item) => (
          <button
            key={item}
            type="button"
            onClick={() => setPrompt(item)}
            className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700 dark:border-slate-800 dark:bg-slate-950 dark:text-slate-300"
          >
            {item}
          </button>
        ))}
      </div>
    </header>
  );
}

function TaskBoard({ tasks }: { tasks: DashboardTask[] }) {
  const groups = taskGroups(tasks);
  const columns = [
    { key: "todo", title: "待处理", count: groups.todo.length, items: groups.todo },
    { key: "doing", title: "进行中", count: groups.doing.length, items: groups.doing },
    {
      key: "blocked",
      title: "等待确认",
      count: groups.blocked.length,
      items: groups.blocked,
    },
    { key: "done", title: "已完成", count: groups.done.length, items: groups.done },
  ];

  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle title="任务看板" />
        <div className="flex gap-2">
          {["全部任务", "截止日优先"].map((item) => (
            <button
              key={item}
              type="button"
              className="h-7 rounded-lg border border-slate-200 px-2 text-xs text-slate-500 transition hover:bg-slate-50 dark:border-slate-700"
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {columns.map((column) => (
          <div
            key={column.key}
            className={cn(
              "min-h-[260px] rounded-lg border p-3",
              column.key === "blocked"
                ? "border-amber-100 bg-amber-50/70 dark:border-amber-900 dark:bg-amber-950/30"
                : column.key === "done"
                  ? "border-emerald-100 bg-emerald-50/60 dark:border-emerald-900 dark:bg-emerald-950/20"
                  : "border-slate-100 bg-slate-50/70 dark:border-slate-800 dark:bg-slate-950",
            )}
          >
            <div className="mb-3 flex items-center justify-between text-xs">
              <div className="font-semibold text-slate-700 dark:text-slate-200">
                {column.title}
              </div>
              <span className="rounded-md bg-white px-1.5 py-0.5 text-slate-500 shadow-sm dark:bg-slate-900">
                {column.count}
              </span>
            </div>
            <div className="space-y-2">
              {column.items.slice(0, 4).map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
              {column.items.length === 0 && (
                <div className="rounded-lg border border-dashed border-slate-200 px-3 py-8 text-center text-xs text-slate-400 dark:border-slate-700">
                  暂无任务
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TaskCard({ task }: { task: DashboardTask }) {
  return (
    <div className="rounded-lg border border-slate-100 bg-white p-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-2">
        <div className="line-clamp-2 text-sm font-medium leading-5 text-slate-800 dark:text-slate-100">
          {task.title}
        </div>
        <span
          className={cn(
            "shrink-0 rounded-md px-1.5 py-0.5 text-[10px] font-medium",
            task.priority === "urgent" && "bg-red-50 text-red-600",
            task.priority === "high" && "bg-orange-50 text-orange-600",
            task.priority === "medium" && "bg-blue-50 text-blue-600",
            task.priority === "low" && "bg-slate-100 text-slate-500",
          )}
        >
          {task.priority === "urgent"
            ? "高"
            : task.priority === "high"
              ? "中"
              : task.priority === "medium"
                ? "中"
                : "低"}
        </span>
      </div>
      <div className="mt-2 line-clamp-2 text-xs leading-5 text-slate-500">
        {task.description}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div
          className="h-full rounded-full bg-blue-500"
          style={{ width: `${task.progress}%` }}
        />
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[11px] text-slate-500">
        <div className="flex min-w-0 items-center gap-1.5">
          <Avatar name={task.owner} size="sm" />
          <span className="truncate">{task.owner}</span>
        </div>
        <span>{task.dueLabel}</span>
      </div>
    </div>
  );
}

function MilestonePanel({ milestones }: { milestones: DashboardMilestone[] }) {
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle title="里程碑视图" />
        <div className="flex gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-700 dark:bg-slate-950">
          {["列表", "时间轴", "日历"].map((item, index) => (
            <span
              key={item}
              className={cn(
                "rounded-md px-2 py-1 text-xs",
                index === 1
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-slate-500",
              )}
            >
              {item}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-5 overflow-x-auto pb-2">
        <div className="relative min-w-[520px] px-2 py-6">
          <div className="absolute left-8 right-8 top-1/2 h-px bg-slate-200 dark:bg-slate-700" />
          <div className="relative grid grid-cols-5 gap-4">
            {milestones.slice(0, 5).map((item, index) => (
              <div key={item.id} className="text-center">
                <div
                  className={cn(
                    "mx-auto grid size-9 place-items-center rounded-full text-xs font-semibold text-white shadow-sm",
                    index === 0 && "bg-emerald-500",
                    index === 1 && "bg-blue-500",
                    index === 2 && "bg-orange-500",
                    index === 3 && "bg-violet-500",
                    index >= 4 && "bg-red-500",
                  )}
                >
                  {index + 1}
                </div>
                <div className="mt-2 text-xs font-medium text-slate-700 dark:text-slate-200">
                  {item.title}
                </div>
                <div className="mt-1 text-[11px] text-slate-500">
                  {formatDate(item.dateLabel)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-100 dark:border-slate-800">
        <div className="grid grid-cols-[1.2fr_1fr_.8fr_1fr_.8fr] bg-slate-50 px-3 py-2 text-[11px] font-medium text-slate-500 dark:bg-slate-950">
          <span>里程碑</span>
          <span>计划日期</span>
          <span>状态</span>
          <span>负责人</span>
          <span>进度</span>
        </div>
        {milestones.slice(0, 5).map((item) => (
          <div
            key={item.id}
            className="grid grid-cols-[1.2fr_1fr_.8fr_1fr_.8fr] border-t border-slate-100 px-3 py-2 text-xs text-slate-600 dark:border-slate-800 dark:text-slate-300"
          >
            <span className="truncate">{item.title}</span>
            <span>{formatLongDate(item.dateLabel)}</span>
            <span>{item.status}</span>
            <span className="truncate">{item.owner}</span>
            <span>{item.progress}%</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function TaskDetailPanel({
  task,
  project,
  artifacts,
}: {
  task: DashboardTask | undefined;
  project: CompanyProject | null;
  artifacts: DashboardArtifact[];
}) {
  const current = task ?? DEMO_TASKS[0]!;
  return (
    <section className="rounded-lg border border-white/80 bg-white p-4 shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span>返回</span>
        <ChevronRightIcon className="size-3" />
        <span>任务</span>
        <ChevronRightIcon className="size-3" />
        <span>{current.title}</span>
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-lg font-semibold tracking-normal text-slate-950 dark:text-white">
              {current.title}
            </h3>
            <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-600">
              高优先级
            </span>
            <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
              {TASK_STATUS_LABELS[current.status]}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <Avatar name={current.owner} size="sm" />
              {current.owner}
            </span>
            <span className="flex items-center gap-1">
              <CalendarDaysIcon className="size-3.5" />
              {current.dueLabel} 截止
            </span>
            <span className="flex items-center gap-1">
              <MessageSquareIcon className="size-3.5" />3
            </span>
            <span className="flex items-center gap-1">
              <UsersRoundIcon className="size-3.5" />8
            </span>
          </div>
        </div>
      </div>

      <div className="mt-4 flex gap-5 overflow-x-auto border-b border-slate-100 text-xs font-medium text-slate-500 dark:border-slate-800">
        {["详情", "子任务 5", "评论 8", "文件", "历史记录", "AI 协作"].map(
          (tab, index) => (
            <span
              key={tab}
              className={cn(
                "shrink-0 border-b-2 pb-2",
                index === 0
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent",
              )}
            >
              {tab}
            </span>
          ),
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_13rem]">
        <div className="space-y-4">
          <div>
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              任务描述
            </div>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {current.description}
            </p>
          </div>
          <div>
            <div className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              验收标准
            </div>
            <ol className="mt-2 space-y-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
              <li>1. 覆盖核心功能需求与边界条件。</li>
              <li>2. 对齐项目里程碑和责任人。</li>
              <li>3. 输出可供研发和测试执行的交付清单。</li>
              <li>4. 通过产品评审。</li>
            </ol>
          </div>
        </div>
        <div className="rounded-lg border border-slate-100 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-950">
          <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">
            任务信息
          </div>
          <div className="mt-3 space-y-2 text-xs text-slate-500">
            <ProjectMetaRow label="所属项目" value={project?.name ?? "智能硬件产品开发"} />
            <ProjectMetaRow label="预计工时" value="32 小时" />
            <ProjectMetaRow label="当前进度" value={`${current.progress}%`} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {artifacts.slice(0, 2).map((artifact) => (
              <span
                key={artifact.id}
                className="rounded-md bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
              >
                {artifact.title.split(".")[0]}
              </span>
            ))}
          </div>
          <div className="mt-4 flex -space-x-2">
            <Avatar name="张晓明" />
            <Avatar name="李华" />
            <Avatar name="陈晨" />
            <Avatar name="AI" tone="primary" />
          </div>
        </div>
      </div>
    </section>
  );
}

function AgentPanel({
  projectName,
  insights,
  artifacts,
}: {
  projectName: string;
  insights: DashboardInsight[];
  artifacts: DashboardArtifact[];
}) {
  const agents = ["产品经理 Agent", "研究分析 Agent", "设计助手 Agent", "测试工程师 Agent", "项目经理 Agent"];

  return (
    <section className="grid rounded-lg border border-white/80 bg-white shadow-sm shadow-slate-200/70 dark:border-slate-800 dark:bg-slate-900 lg:grid-cols-[10rem_minmax(0,1fr)_10rem]">
      <div className="border-b border-slate-100 p-3 dark:border-slate-800 lg:border-b-0 lg:border-r">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-700 dark:text-slate-200">
          <BotIcon className="size-4 text-blue-600" />
          AI Agent
        </div>
        <div className="space-y-2">
          {agents.map((agent, index) => (
            <div
              key={agent}
              className={cn(
                "flex items-center gap-2 rounded-lg px-2 py-2 text-xs",
                index === 0
                  ? "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-200"
                  : "text-slate-500",
              )}
            >
              <Avatar name={agent} size="sm" tone={index === 0 ? "primary" : "neutral"} />
              <span className="truncate">{agent}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="min-w-0 p-4">
        <div className="text-sm font-semibold text-slate-900 dark:text-white">
          产品经理 Agent
        </div>
        <div className="mt-1 text-xs text-slate-500">正在处理 {projectName} 的任务</div>
        <div className="mt-4 space-y-3">
          <ChatBubble side="left">
            我已完成 PRD 文档的初稿编写，包含核心功能、验收标准和风险说明。
          </ChatBubble>
          <ChatBubble side="left">
            需要你确认以下内容：1. 用户画像；2. 设备配对方案；3. 试产时间窗口。
          </ChatBubble>
          <ChatBubble side="right">通过方案，继续细化需求修改和评审讨论。</ChatBubble>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {["通过方案", "需要修改", "评审讨论"].map((item, index) => (
            <button
              key={item}
              type="button"
              className={cn(
                "inline-flex h-8 items-center gap-1 rounded-lg px-3 text-xs font-medium",
                index === 0
                  ? "bg-blue-600 text-white"
                  : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
              )}
            >
              {index === 0 ? <SparklesIcon className="size-3.5" /> : null}
              {item}
            </button>
          ))}
        </div>
      </div>

      <div className="border-t border-slate-100 p-3 dark:border-slate-800 lg:border-l lg:border-t-0">
        <div className="text-xs font-semibold text-slate-700 dark:text-slate-200">
          Agent 执行记录
        </div>
        <div className="mt-3 space-y-2">
          {insights.slice(0, 4).map((item) => (
            <div
              key={item.id}
              className="rounded-lg bg-slate-50 px-2 py-2 text-[11px] text-slate-600 dark:bg-slate-950 dark:text-slate-300"
            >
              <div className="font-medium">{item.time}</div>
              <div className="mt-1 line-clamp-2">{item.title}</div>
            </div>
          ))}
        </div>
        <div className="mt-4 text-xs font-semibold text-slate-700 dark:text-slate-200">
          相关文件
        </div>
        <div className="mt-2 space-y-2">
          {artifacts.slice(0, 3).map((artifact) => (
            <div key={artifact.id} className="flex items-center gap-2 text-[11px] text-slate-500">
              <FileTextIcon className="size-3.5 text-blue-500" />
              <span className="truncate">{artifact.title}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function PanelTitle({
  title,
  action,
}: {
  title: string;
  action?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="text-sm font-semibold text-slate-900 dark:text-white">
        {title}
      </div>
      {action ? (
        <button className="text-xs font-medium text-blue-600">{action} →</button>
      ) : null}
    </div>
  );
}

function ProgressRing({
  progress,
  compact = false,
}: {
  progress: number;
  compact?: boolean;
}) {
  const sizeClass = compact ? "size-14" : "size-24";
  return (
    <div
      className={cn(
        "grid place-items-center rounded-full",
        sizeClass,
      )}
      style={{
        background: `conic-gradient(#22c55e ${clampProgress(progress) * 3.6}deg, #e5edf5 0deg)`,
      }}
    >
      <div
        className={cn(
          "grid place-items-center rounded-full bg-white font-semibold text-slate-950 dark:bg-slate-900 dark:text-white",
          compact ? "size-10 text-sm" : "size-16 text-2xl",
        )}
      >
        {clampProgress(progress)}%
      </div>
    </div>
  );
}

function ProjectMetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-400">{label}</span>
      <span className="truncate text-right font-medium text-slate-700 dark:text-slate-200">
        {value}
      </span>
    </div>
  );
}

function AvatarStack() {
  return (
    <div className="flex -space-x-2">
      <Avatar name="张晓明" />
      <Avatar name="李华" tone="success" />
      <Avatar name="陈晨" tone="warning" />
      <Avatar name="AI" tone="primary" />
      <span className="grid size-7 place-items-center rounded-full border-2 border-white bg-slate-100 text-[10px] font-medium text-slate-500 dark:border-slate-900 dark:bg-slate-800">
        +5
      </span>
    </div>
  );
}

function Avatar({
  name,
  tone = "neutral",
  size = "md",
}: {
  name: string;
  tone?: DashboardInsight["tone"] | "neutral";
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-full border-2 border-white text-[10px] font-semibold dark:border-slate-900",
        size === "sm" ? "size-5" : "size-7",
        tone === "primary" && "bg-blue-500 text-white",
        tone === "success" && "bg-emerald-500 text-white",
        tone === "warning" && "bg-amber-500 text-white",
        tone === "danger" && "bg-red-500 text-white",
        tone === "neutral" && "bg-slate-200 text-slate-700",
      )}
    >
      {initials(name)}
    </span>
  );
}

function ChatBubble({
  side,
  children,
}: {
  side: "left" | "right";
  children: ReactNode;
}) {
  return (
    <div className={cn("flex", side === "right" && "justify-end")}>
      <div
        className={cn(
          "max-w-[78%] rounded-lg px-3 py-2 text-xs leading-5",
          side === "right"
            ? "bg-blue-600 text-white"
            : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-200",
        )}
      >
        {children}
      </div>
    </div>
  );
}
