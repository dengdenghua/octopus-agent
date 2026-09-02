import {
  GitBranchIcon,
  GitCommitIcon,
  GitPullRequestIcon,
  Link2Icon,
  ShieldCheckIcon,
  TerminalSquareIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

type CodingToolboxPanelProps = {
  onOpen?: (target: "tools" | "automationSecurity") => void;
  compact?: boolean;
};

const ITEMS = [
  {
    key: "hooks",
    label: "钩子",
    detail: "安全审批 · 提交校验",
    status: "已启用",
    icon: ShieldCheckIcon,
    tone: "text-emerald-600 dark:text-emerald-400",
  },
  {
    key: "connections",
    label: "连接",
    detail: "MCP · 连接器 · 插件",
    status: "可管理",
    icon: Link2Icon,
    tone: "text-sky-600 dark:text-sky-400",
  },
  {
    key: "git",
    label: "Git",
    detail: "状态 · 差异 · 分支 · 提交",
    status: "可用",
    icon: GitCommitIcon,
    tone: "text-violet-600 dark:text-violet-400",
  },
  {
    key: "environment",
    label: "环境",
    detail: "工作区 · 网络 · 权限",
    status: "可配置",
    icon: TerminalSquareIcon,
    tone: "text-amber-600 dark:text-amber-400",
  },
  {
    key: "worktrees",
    label: "Worktrees",
    detail: "隔离分支 · 并行任务",
    status: "后端可用",
    icon: GitBranchIcon,
    tone: "text-pink-600 dark:text-pink-400",
  },
] as const;

export function CodingToolboxPanel({ onOpen, compact = false }: CodingToolboxPanelProps) {
  if (compact) {
    return (
      <aside
        aria-label="编码工具箱"
        className="flex w-16 shrink-0 flex-col items-center gap-2 border-r border-border bg-muted/10 px-2 py-3"
      >
        {ITEMS.map((item) => {
          const Icon = item.icon;
          const clickable = item.key === "connections" || item.key === "environment";
          return (
            <button
              key={item.key}
              type="button"
              disabled={!clickable}
              onClick={() => {
                if (item.key === "connections") onOpen?.("tools");
                if (item.key === "environment") onOpen?.("automationSecurity");
              }}
              title={`${item.label} · ${item.detail}`}
              className={cn(
                "flex size-11 flex-col items-center justify-center gap-0.5 rounded-lg border border-transparent text-muted-foreground transition-colors",
                clickable
                  ? "hover:border-primary/30 hover:bg-primary/[0.06] hover:text-foreground"
                  : "cursor-default",
              )}
            >
              <Icon className={cn("size-4", item.tone)} aria-hidden="true" />
              <span className="text-[9px] leading-3">{item.label}</span>
            </button>
          );
        })}
      </aside>
    );
  }

  return (
    <section
      aria-labelledby="coding-toolbox-title"
      className="rounded-xl border border-border bg-card/70 p-4 shadow-sm"
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 id="coding-toolbox-title" className="text-sm font-semibold">
            编码工具箱
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            一处查看编码任务的执行能力与连接状态
          </p>
        </div>
        <GitPullRequestIcon className="size-4 text-muted-foreground" aria-hidden="true" />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        {ITEMS.map((item) => {
          const Icon = item.icon;
          const clickable = item.key === "connections" || item.key === "environment";
          return (
            <button
              key={item.key}
              type="button"
              disabled={!clickable}
              onClick={() => {
                if (item.key === "connections") onOpen?.("tools");
                if (item.key === "environment") onOpen?.("automationSecurity");
              }}
              className={cn(
                "group rounded-lg border border-border-subtle bg-background/60 p-3 text-left transition-colors",
                clickable
                  ? "hover:border-primary/40 hover:bg-primary/[0.03]"
                  : "cursor-default",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <Icon className={cn("size-4", item.tone)} aria-hidden="true" />
                <span className="text-[10px] text-muted-foreground">{item.status}</span>
              </div>
              <div className="mt-2 text-sm font-medium">{item.label}</div>
              <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
                {item.detail}
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
