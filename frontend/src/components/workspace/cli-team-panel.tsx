import { useCallback, useEffect, useState } from "react";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  Loader2Icon,
  UsersIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getBackendBaseURL } from "@/core/config";

interface Detected {
  agent_id: string;
  partner_id: string;
  command: string;
}

interface TeamStatus {
  detected: Detected[];
  repo_root: string;
  is_git_repo: boolean;
}

interface Member {
  agent_id: string;
  partner_id: string;
  ok: boolean;
  files: string[];
  error: string | null;
  diff?: string;
}

interface RunResult {
  ok: boolean;
  error?: string;
  count?: number;
  succeeded?: number;
  members: Member[];
}

export default function CliTeamPanel() {
  const [status, setStatus] = useState<TeamStatus | null>(null);
  const [goal, setGoal] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cli-team/status`);
      if (res.ok) setStatus((await res.json()) as TeamStatus);
    } catch {
      /* offline → leave status null */
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const run = useCallback(async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/cli-team/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
      const data = (await res.json()) as RunResult;
      setResult(data);
      if (!data.ok && data.error) setError(data.error);
    } catch (e) {
      setError(e instanceof Error ? e.message : "请求失败");
    } finally {
      setRunning(false);
    }
  }, [goal]);

  const detected = status?.detected ?? [];
  const notGit = status != null && !status.is_git_repo;
  const canRun = detected.length > 0 && !notGit && goal.trim().length > 0 && !running;

  return (
    <div className="rounded-lg border border-border/55 bg-card p-4">
      <div className="mb-3 flex items-center gap-2">
        <UsersIcon className="size-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">CLI 团队 · 让你装的编码 agent 一起干</h2>
          <p className="mt-0.5 text-xs text-muted-foreground leading-snug">
            探测到的本地 coding CLI 各自隔离 worktree + 共享黑板并行,完事各给一份 diff 供你挑(不自动合并)。
          </p>
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        {detected.length === 0 ? (
          <span className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
            没探测到可驱动的 CLI —— 安装 Claude Code 或 Codex
          </span>
        ) : (
          detected.map((d) => (
            <span
              key={d.agent_id}
              className="rounded bg-emerald-50 px-2 py-1 text-[11px] text-emerald-700"
            >
              {d.partner_id}
            </span>
          ))
        )}
        {notGit && (
          <span className="rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700">
            当前目录不是 git 仓(worktree 隔离需要)
          </span>
        )}
      </div>

      <div className="mb-2 flex gap-2">
        <input
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder="让这队 agent 做什么?例如:给登录接口加上速率限制"
          className="flex-1"
          onKeyDown={(e) => {
            if (e.key === "Enter" && canRun) void run();
          }}
        />
        <Button onClick={() => void run()} disabled={!canRun} className="shrink-0">
          {running ? <Loader2Icon className="size-3.5 animate-spin" /> : null}
          <span className={running ? "ml-1.5" : ""}>{running ? "运行中…" : "开跑"}</span>
        </Button>
      </div>

      {error && <p className="mb-2 text-[11px] text-red-600">{error}</p>}

      {result?.members?.map((m) => (
        <div key={m.agent_id} className="mt-2 overflow-hidden rounded-md border border-border/40">
          <div className="flex items-center gap-2 px-3 py-1.5">
            {m.ok ? (
              <CheckCircle2Icon className="size-3.5 shrink-0 text-emerald-600" />
            ) : (
              <AlertCircleIcon className="size-3.5 shrink-0 text-amber-500" />
            )}
            <span className="text-xs font-medium">{m.agent_id}</span>
            <span className="text-[11px] text-muted-foreground">
              {m.ok ? `${m.files.length} 个文件改动` : m.error || "失败"}
            </span>
          </div>
          {m.diff && (
            <pre className="max-h-48 overflow-auto border-t border-border/40 px-3 py-2 text-[11px] leading-snug">
              {m.diff}
            </pre>
          )}
        </div>
      ))}
    </div>
  );
}

/** Dialog wrapper so the team room can open the CLI-team run surface from its
 * header menu, alongside 接入本地伙伴. The same diff-first run engine. */
export function CliTeamDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent style={{ maxWidth: "720px", width: "720px" }}>
        <DialogHeader>
          <DialogTitle className="text-base">CLI 团队 · 开跑</DialogTitle>
        </DialogHeader>
        <CliTeamPanel />
      </DialogContent>
    </Dialog>
  );
}
