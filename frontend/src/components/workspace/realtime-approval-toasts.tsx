import { LoaderCircleIcon, ShieldAlertIcon } from "lucide-react";
import { useRef, useState } from "react";
import { provisionProjectRoles, type RoleProvision } from "@/core/agents/project-recruitment";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { PendingApproval } from "@/core/realtime/items";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

function approvalToolLabel(
  tool: string | undefined,
  method: PendingApproval["method"],
  t: ReturnType<typeof useI18n>["t"],
): string {
  const normalized = tool?.trim().toLowerCase() ?? "";
  if (
    normalized === "bash" ||
    normalized === "exec_shell" ||
    normalized === "shell_command" ||
    normalized === "run_command"
  ) {
    return t.toolApproval.tools.bash;
  }
  if (
    normalized === "write_file" ||
    normalized === "write_text_file" ||
    normalized === "create_file"
  ) {
    return t.toolApproval.tools.write_file;
  }
  if (
    normalized === "apply_patch" ||
    normalized === "edit_file" ||
    normalized === "edit_text_file" ||
    normalized === "str_replace"
  ) {
    return t.toolApproval.tools.str_replace;
  }
  const knownTool =
    (t.toolApproval.tools as Record<string, string>)[normalized];
  if (knownTool) return knownTool;
  if (method.includes("commandExecution")) {
    return t.toolApproval.tools.bash;
  }
  if (method.includes("fileChange")) {
    return t.toolApproval.tools.str_replace;
  }
  return t.liveTools.genericAction;
}

function approvalArgsSummary(
  params: {
    argsPreview?: string;
    detail?: string;
  },
  method: PendingApproval["method"],
): string {
  const preview = params.argsPreview?.trim();
  if (!preview) return params.detail?.trim() ?? "";

  const field = method.includes("commandExecution") ? "command" : "path";
  const quoted = new RegExp(
    `["']${field}["']\\s*:\\s*["']([^"']+)["']`,
    "i",
  ).exec(preview);
  if (quoted?.[1]) return quoted[1].trim();

  try {
    const parsed = JSON.parse(preview) as Record<string, unknown>;
    const value = parsed[field];
    if (typeof value === "string" && value.trim()) return value.trim();
  } catch {
    // Tool adapters may provide a Python-style dict preview. The targeted
    // field extraction above handles that common form; otherwise retain the
    // original preview instead of inventing a command or path.
  }
  return preview;
}

export function RealtimeApprovalPrompt({
  approvals,
  resolveApproval,
  className,
}: {
  approvals: PendingApproval[];
  resolveApproval: (requestId: string | number, accept: boolean, preparedRoles?: Record<string, string>) => void;
  className?: string;
}) {
  const { t, locale } = useI18n();
  const zh = locale === "zh-CN";
  const [busy, setBusy] = useState<string | number | null>(null);
  const inFlight = useRef(false);
  const liveApprovals = useRef(approvals);
  liveApprovals.current = approvals;
  const [error, setError] = useState<{ id: string | number; message: string } | null>(null);
  const approve = async (approval: PendingApproval, roles?: RoleProvision[]) => {
    if (inFlight.current) return;
    if (!roles?.length) { resolveApproval(approval.requestId, true); return; }
    inFlight.current = true;
    setBusy(approval.requestId);
    setError(null);
    try {
      const prepared = await provisionProjectRoles(roles, () => liveApprovals.current.some(item => item.requestId === approval.requestId));
      resolveApproval(approval.requestId, true, prepared);
    } catch (e) {
      setError({ id: approval.requestId, message: e instanceof Error ? e.message : String(e) });
    } finally {
      inFlight.current = false;
      setBusy(null);
    }
  };
  if (approvals.length === 0) return null;

  return (
    <div
      className={cn(
        "mx-1 max-h-44 space-y-1.5 overflow-y-auto overscroll-contain",
        className,
      )}
    >
      {approvals.map((approval) => {
        const params = approval.params as {
          tool?: string;
          argsPreview?: string;
          detail?: string;
          roleProvisions?: RoleProvision[];
          staffingReview?: { role: string; name: string; source: string; responsibilities: string; phases: number[] }[];
        };
        const toolLabel = approvalToolLabel(params.tool, approval.method, t);
        const summary = approvalArgsSummary(params, approval.method);
        const label = `${toolLabel} · ${t.toolApproval.requiresApproval}`;
        const labelId = `approval-${String(approval.requestId)}-label`;
        if (params.tool?.startsWith("project_")) {
          // Queue project dialogs rather than stacking multiple modal overlays.
          if (approvals.find(item => String((item.params as { tool?: string }).tool ?? "").startsWith("project_")) !== approval) return null;
          const roles = params.tool === "project_initiation" ? params.roleProvisions : undefined;
          return (
            <Dialog key={String(approval.requestId)} open>
              <DialogContent showCloseButton={false} className="flex max-h-[85dvh] flex-col sm:max-w-2xl" onEscapeKeyDown={event => event.preventDefault()} onInteractOutside={event => event.preventDefault()}>
                <DialogTitle>{label}</DialogTitle>
                <DialogDescription>{params.tool === "project_acceptance"
                  ? (zh ? "请对照验收标准审阅交付内容。批准仅记录本阶段验收，不自动启动下一阶段。" : "Review the deliverables against the acceptance criteria. Approval records acceptance only; it does not start the next stage.")
                  : params.tool === "project_budget"
                    ? (zh ? "请核对费用上限。批准仅调整预算策略，不启动执行或付款。" : "Review the spending limit. Approval changes the budget policy only; it does not start execution or make a payment.")
                    : (zh ? "请审阅方案后决定。只有你批准后，系统才会添加候选角色或推进对应阶段。" : "Review before deciding. Candidate roles are added or the requested stage advances only after approval.")}</DialogDescription>
                <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
                  {!!params.staffingReview?.length && <ul className="space-y-2">
                    {params.staffingReview.map((role, index) => <li key={index} className="rounded-lg border p-3 text-sm">
                      <div className="flex items-center justify-between gap-2"><strong>{role.name} · {role.role}</strong><span className="rounded bg-muted px-2 py-0.5 text-xs">{({ existing: zh ? "已有角色" : "Existing role", hub: zh ? "从 HUB 添加" : "Add from HUB", new: zh ? "待创建角色" : "Create role", human: zh ? "真人建议" : "Human proposal", supplier: zh ? "供应商建议" : "Supplier proposal" } as Record<string, string>)[role.source] ?? role.source}</span></div>
                      <p className="mt-1 text-muted-foreground">{role.responsibilities}</p>
                      <p className="mt-1 text-xs">{zh ? "参与阶段" : "Stages"}：{role.phases.join(", ")}</p>
                    </li>)}
                  </ul>}
                  <section aria-labelledby={labelId}><h3 id={labelId} className="sr-only">{label}</h3><p className="whitespace-pre-wrap text-sm leading-6">{summary}</p></section>
                </div>
                {error?.id === approval.requestId && <p role="alert" className="text-sm text-destructive">{error.message}</p>}
                <div className="flex shrink-0 justify-end gap-2 border-t pt-3">
                  <Button variant="outline" disabled={busy !== null} onClick={() => resolveApproval(approval.requestId, false)}>{t.toolApproval.reject}</Button>
                  <Button disabled={busy !== null} aria-busy={busy === approval.requestId} onClick={() => void approve(approval, roles)}>
                    {busy === approval.requestId && <LoaderCircleIcon className="size-4 animate-spin" />}
                    {busy === approval.requestId ? (zh ? "正在准备角色…" : "Preparing roles…") : t.toolApproval.approve}
                  </Button>
                </div>
              </DialogContent>
            </Dialog>
          );
        }
        return (
          <section
            key={String(approval.requestId)}
            aria-labelledby={labelId}
            className="grid min-h-14 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-warning/20 bg-background/95 px-3 py-2 shadow-[0_12px_32px_-24px_rgba(15,23,42,0.55)] backdrop-blur-xl"
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <ShieldAlertIcon
                aria-hidden="true"
                className="size-4 shrink-0 text-warning"
              />
              <div className="min-w-0">
                <p
                  id={labelId}
                  className="truncate text-[13px] font-medium leading-5 text-foreground"
                >
                  {label}
                </p>
                {summary ? (
                  <code
                    className={cn("block text-mini leading-4 text-muted-foreground",
                      params.tool?.startsWith("project_") ? "whitespace-pre-wrap font-sans" : "truncate font-mono")}
                    title={summary}
                  >
                    {summary}
                  </code>
                ) : null}
                {error?.id === approval.requestId ? <p role="alert" className="text-xs text-destructive">{error.message}</p> : null}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => resolveApproval(approval.requestId, false)}
                disabled={busy !== null}
                className="text-muted-foreground hover:text-foreground"
              >
                {t.toolApproval.reject}
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => void approve(approval, params.tool === "project_initiation" ? params.roleProvisions : undefined)}
                disabled={busy !== null}
                aria-busy={busy === approval.requestId}
              >
                {busy === approval.requestId ? <LoaderCircleIcon className="size-3 animate-spin" /> : null}
                {t.toolApproval.approve}
              </Button>
            </div>
          </section>
        );
      })}
    </div>
  );
}
