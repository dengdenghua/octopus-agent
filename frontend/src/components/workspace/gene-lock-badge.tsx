/**
 * Gene-lock status badge · compact "who's allowed to do what"
 * indicator for governance surfaces in the workspace.
 *
 * Shows:
 *   - Current maturity level (Lv 0..4) with color coding
 *   - Panic active badge when engaged
 *   - Mode: dev / production
 *
 * Click opens a compact dropdown with:
 *   - Level up/down buttons
 *   - Panic trigger (destructive)
 *   - "Clear panic" (only when panic active)
 *
 * Full reference: docs/gene-locks.md
 */

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { DnaIcon, SirenIcon, ShieldCheckIcon, ShieldIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type LockStatus = {
  schema_version: number;
  maturity_level: number;
  maturity_level_name: string;
  panic: { active: boolean; since: number | null; reason: string };
  mode: string;
  last_mutation_at?: Record<string, number>;
  required_levels?: Record<
    string,
    { autonomous: number; human_signed: number }
  >;
  cooldowns_seconds?: Record<string, number>;
};

const LEVEL_NAMES = ["初生", "幼年", "成长期", "成熟", "完全成熟"];

const LEVEL_DESCRIPTIONS = [
  "所有自主进化禁用",
  "允许应用变更，但需要人工确认",
  "允许调整权重",
  "允许自动晋升",
  "除不可变字段外不再限制",
];

export function GeneLockBadge() {
  const [status, setStatus] = useState<LockStatus | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r: LockStatus = await fetch(
        `${getBackendBaseURL()}/api/gene-locks/status`,
      ).then((r) => r.json());
      setStatus(r);
    } catch (e) {
      swallow(e);
      // Silent · the badge is optional. A missing endpoint means
      // older backend · we render nothing.
    }
  }, []);

  useEffect(() => {
    void reload();
    const tid = window.setInterval(() => void reload(), 15000);
    return () => window.clearInterval(tid);
  }, [reload]);

  const changeLevel = useCallback(
    async (delta: number) => {
      if (!status) return;
      const target = Math.max(0, Math.min(4, status.maturity_level + delta));
      if (target === status.maturity_level) return;
      setBusy(true);
      try {
        // In dev mode any change goes through; in prod, up-moves need
        // a human approver. For the UI badge we always pass a
        // synthetic "ui-operator" signature · real deploys should
        // replace this with the logged-in user's ID.
        const r = await fetch(
          `${getBackendBaseURL()}/api/gene-locks/maturity`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Human-Approver": "ui-operator",
            },
            body: JSON.stringify({ level: target }),
          },
        ).then((r) => r.json());
        setMsg(
          r.ok
            ? `${status.maturity_level} → ${target}`
            : `✕ ${r.message ?? r.error}`,
        );
        void reload();
      } finally {
        setBusy(false);
        window.setTimeout(() => setMsg(null), 3500);
      }
    },
    [status, reload],
  );

  const triggerPanic = useCallback(async () => {
    if (!confirm("Trigger panic? Freezes every autonomous mutation.")) return;
    setBusy(true);
    try {
      await fetch(`${getBackendBaseURL()}/api/gene-locks/panic`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "ui-operator" }),
      });
      void reload();
    } finally {
      setBusy(false);
    }
  }, [reload]);

  const clearPanic = useCallback(async () => {
    setBusy(true);
    try {
      await fetch(`${getBackendBaseURL()}/api/gene-locks/panic/clear`, {
        method: "POST",
        headers: { "X-Human-Approver": "ui-operator" },
      });
      void reload();
    } finally {
      setBusy(false);
    }
  }, [reload]);

  if (!status) return null;
  const lvl = status.maturity_level;
  const panic = status.panic.active;
  const levelColor = panic
    ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
    : lvl === 0
      ? "bg-slate-500/20 text-slate-300 border-slate-500/40"
      : lvl <= 2
        ? "bg-amber-500/20 text-amber-300 border-amber-500/40"
        : "bg-emerald-500/20 text-emerald-300 border-emerald-500/40";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          "inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-xs font-medium transition-colors",
          levelColor,
        )}
        title="基因锁治理状态 · 点击调整"
      >
        {panic ? (
          <SirenIcon className="size-3 animate-pulse" />
        ) : lvl >= 3 ? (
          <ShieldCheckIcon className="size-3" />
        ) : (
          <DnaIcon className="size-3" />
        )}
        <span>基因锁</span>
        <span className="tabular-nums">Lv {lvl}</span>
        <span className="text-[10px] opacity-75">
          {panic ? "紧急锁定" : (LEVEL_NAMES[lvl] ?? "?")}
        </span>
        {status.mode === "production" && (
          <Badge className="ml-1 h-4 bg-slate-900/40 px-1 text-[9px] uppercase tracking-wider text-slate-300">
            生产
          </Badge>
        )}
      </button>

      {expanded && (
        <div className="absolute right-0 top-full z-30 mt-1 w-72 rounded-lg border border-border/60 bg-background/95 p-3 text-xs shadow-xl backdrop-blur">
          <div className="mb-2 flex items-center gap-2 font-medium">
            <ShieldIcon className="size-3.5" />
            基因锁 · 自进化治理
          </div>
          <div className="space-y-1 text-muted-foreground">
            <div>
              模式: <span className="text-foreground">{status.mode}</span>
            </div>
            <div>
              成熟度:{" "}
              <span className="text-foreground">
                Lv {lvl} · {LEVEL_NAMES[lvl]}
              </span>
            </div>
            {panic && (
              <div className="rounded bg-rose-500/10 px-2 py-1 text-rose-300">
                <div className="font-medium">紧急锁定中</div>
                <div className="text-[10px]">
                  开始于{" "}
                  {status.panic.since
                    ? new Date(status.panic.since * 1000).toLocaleString()
                    : "?"}
                </div>
                <div className="text-[10px]">原因: {status.panic.reason}</div>
              </div>
            )}
          </div>

          <div className="mt-3 flex items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => changeLevel(-1)}
              disabled={busy || lvl === 0 || panic}
            >
              ← Lv {Math.max(0, lvl - 1)}
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              onClick={() => changeLevel(+1)}
              disabled={busy || lvl === 4 || panic}
            >
              Lv {Math.min(4, lvl + 1)} →
            </Button>
            <div className="flex-1" />
            {panic ? (
              <Button
                size="sm"
                className="h-7 bg-emerald-600 text-xs hover:bg-emerald-700"
                onClick={clearPanic}
                disabled={busy}
              >
                <ShieldCheckIcon className="mr-1 size-3" />
                解除锁定
              </Button>
            ) : (
              <Button
                size="sm"
                variant="destructive"
                className="h-7 text-xs"
                onClick={triggerPanic}
                disabled={busy}
              >
                <SirenIcon className="mr-1 size-3" />
                紧急锁定
              </Button>
            )}
          </div>
          {msg && (
            <div className="mt-2 text-xs text-muted-foreground">{msg}</div>
          )}
          <div className="mt-2 border-t border-border/30 pt-2 text-[10px] text-muted-foreground">
            Lv 0 初生 · 所有自主进化禁用
            <br />
            Lv 1 幼年 · 允许应用变更，但需要人工确认
            <br />
            Lv 2 成长期 · 允许调整权重
            <br />
            Lv 3 成熟 · 允许自动晋升
            <br />
            Lv 4 完全成熟 · 除不可变字段外不再限制
          </div>
        </div>
      )}
    </div>
  );
}

export function GeneLockControlCard({
  compact = false,
  className,
}: {
  compact?: boolean;
  className?: string;
} = {}) {
  const [status, setStatus] = useState<LockStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const r: LockStatus = await fetch(
        `${getBackendBaseURL()}/api/gene-locks/status`,
      ).then((r) => r.json());
      setStatus(r);
    } catch (e) {
      swallow(e);
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    void reload();
    const tid = window.setInterval(() => void reload(), 15000);
    return () => window.clearInterval(tid);
  }, [reload]);

  const run = useCallback(
    async (key: string, action: () => Promise<Response>) => {
      setBusy(key);
      try {
        const r = await action();
        const body = await r.json().catch(() => ({}));
        if (body?.ok === false) {
          setMsg(body.message ?? body.error ?? "操作未生效");
        } else {
          setMsg("已更新");
        }
        await reload();
      } finally {
        setBusy(null);
        window.setTimeout(() => setMsg(null), 3500);
      }
    },
    [reload],
  );

  const setMode = useCallback(
    (mode: "dev" | "production") =>
      run(`mode:${mode}`, () =>
        fetch(`${getBackendBaseURL()}/api/gene-locks/mode`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Human-Approver": "ui-operator",
          },
          body: JSON.stringify({ mode }),
        }),
      ),
    [run],
  );

  const setLevel = useCallback(
    (level: number) =>
      run(`level:${level}`, () =>
        fetch(`${getBackendBaseURL()}/api/gene-locks/maturity`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Human-Approver": "ui-operator",
          },
          body: JSON.stringify({ level }),
        }),
      ),
    [run],
  );

  const setPanic = useCallback(
    (enabled: boolean) =>
      run(enabled ? "panic:on" : "panic:off", () =>
        fetch(
          `${getBackendBaseURL()}/api/gene-locks/panic${enabled ? "" : "/clear"}`,
          {
            method: "POST",
            headers: enabled
              ? { "Content-Type": "application/json" }
              : { "X-Human-Approver": "ui-operator" },
            body: enabled
              ? JSON.stringify({ reason: "ui-operator" })
              : undefined,
          },
        ),
      ),
    [run],
  );

  if (!status) return null;

  const lvl = Math.max(0, Math.min(4, status.maturity_level));
  const panic = status.panic.active;
  const strict = status.mode === "production";

  if (compact) {
    return (
      <div
        className={cn(
          "rounded-lg border border-border/60 bg-background/75 px-3 py-2 shadow-sm",
          className,
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <DnaIcon className="size-3.5 shrink-0 text-primary" />
            <span className="text-xs font-semibold">基因锁</span>
            <Badge
              variant={panic ? "destructive" : "outline"}
              className="h-5 rounded-md px-1.5 text-[11px]"
            >
              {panic ? "紧急锁定" : `Lv ${lvl} · ${LEVEL_NAMES[lvl]}`}
            </Badge>
          </div>

          <span className="hidden h-4 w-px bg-border/70 sm:block" />

          <div className="flex items-center rounded-md bg-muted/45 p-0.5">
            {[
              ["dev", "宽松"],
              ["production", "严格"],
            ].map(([mode, label]) => {
              const selected =
                (mode === "production" && strict) ||
                (mode === "dev" && !strict);
              return (
                <button
                  key={mode}
                  type="button"
                  disabled={busy !== null}
                  onClick={() => setMode(mode as "dev" | "production")}
                  className={cn(
                    "h-6 rounded-[5px] px-2 text-[11px] transition-colors",
                    selected
                      ? "bg-background text-foreground shadow-sm"
                      : "text-muted-foreground hover:text-foreground",
                    "disabled:cursor-not-allowed disabled:opacity-45",
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <div className="flex items-center rounded-md bg-muted/45 p-0.5">
            {LEVEL_NAMES.map((name, index) => (
              <button
                key={name}
                type="button"
                disabled={busy !== null || panic}
                onClick={() => setLevel(index)}
                title={`${name} · ${LEVEL_DESCRIPTIONS[index]}`}
                className={cn(
                  "h-6 rounded-[5px] px-2 font-mono text-[11px] transition-colors",
                  index === lvl
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
              >
                Lv{index}
              </button>
            ))}
          </div>

          <Button
            type="button"
            size="sm"
            variant={panic ? "secondary" : "outline"}
            className="h-7 px-2 text-[11px]"
            disabled={busy !== null}
            onClick={() => setPanic(!panic)}
          >
            {panic ? (
              <>
                <ShieldCheckIcon className="mr-1 size-3" />
                解锁
              </>
            ) : (
              <>
                <SirenIcon className="mr-1 size-3" />
                锁定
              </>
            )}
          </Button>

          {msg ? (
            <span className="text-[11px] text-muted-foreground">{msg}</span>
          ) : null}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] leading-5 text-muted-foreground">
          <span>{strict ? "严格拦截不合规自修改" : "宽松模式只提示风险"}</span>
          <span>{LEVEL_DESCRIPTIONS[lvl]}</span>
          {panic ? (
            <span className="text-destructive">自主变更已暂停</span>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <section className="workspace-panel rounded-[1.25rem] border border-border/70 px-4 py-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <DnaIcon className="size-4" />
            </div>
            <div>
              <h2 className="text-sm font-semibold">基因锁设置</h2>
              <p className="text-xs text-muted-foreground">
                控制系统能不能自主修改配置、技能权重和进化结果。
              </p>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={panic ? "destructive" : "outline"} className="h-7">
            {panic ? "紧急锁定中" : `Lv ${lvl} · ${LEVEL_NAMES[lvl]}`}
          </Badge>
          {msg ? (
            <span className="text-xs text-muted-foreground">{msg}</span>
          ) : null}
        </div>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_1.4fr_1fr]">
        <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
          <div className="text-xs font-medium">开启方式</div>
          <div className="mt-2 grid grid-cols-2 gap-1">
            <Button
              type="button"
              size="sm"
              variant={!strict ? "secondary" : "outline"}
              className="h-8 text-xs"
              disabled={busy !== null}
              onClick={() => setMode("dev")}
            >
              宽松
            </Button>
            <Button
              type="button"
              size="sm"
              variant={strict ? "secondary" : "outline"}
              className="h-8 text-xs"
              disabled={busy !== null}
              onClick={() => setMode("production")}
            >
              严格
            </Button>
          </div>
          <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
            宽松模式只提示风险；严格模式会真正拦截不合规自修改。
          </p>
        </div>

        <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-medium">进化档位</div>
            <span className="text-[11px] text-muted-foreground">
              {LEVEL_DESCRIPTIONS[lvl]}
            </span>
          </div>
          <div className="mt-2 grid grid-cols-5 gap-1">
            {LEVEL_NAMES.map((name, index) => (
              <Button
                key={name}
                type="button"
                size="sm"
                variant={index === lvl ? "secondary" : "outline"}
                className="h-auto min-h-10 flex-col gap-0.5 px-1 py-1 text-[11px]"
                disabled={busy !== null || panic}
                onClick={() => setLevel(index)}
                title={LEVEL_DESCRIPTIONS[index]}
              >
                <span className="font-mono">Lv {index}</span>
                <span className="truncate">{name}</span>
              </Button>
            ))}
          </div>
        </div>

        <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
          <div className="text-xs font-medium">总开关</div>
          <Button
            type="button"
            size="sm"
            variant={panic ? "secondary" : "destructive"}
            className="mt-2 h-8 w-full text-xs"
            disabled={busy !== null}
            onClick={() => setPanic(!panic)}
          >
            {panic ? (
              <>
                <ShieldCheckIcon className="mr-1 size-3.5" />
                解除锁定
              </>
            ) : (
              <>
                <SirenIcon className="mr-1 size-3.5" />
                关闭自主进化
              </>
            )}
          </Button>
          <p className="mt-2 text-[11px] leading-5 text-muted-foreground">
            关闭后会进入紧急锁定，所有自主变更都会被挡住。
          </p>
        </div>
      </div>
    </section>
  );
}
