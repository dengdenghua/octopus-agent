/**
 * Privacy / Developer Mode settings.
 *
 * Today this page hosts a single toggle: the **identity lock**. When
 * enabled (default), the runtime scrubs vendor / model self-identification
 * from LLM replies (``"I'm Claude"`` → ``"I'm Octopus"``). Operators
 * who need to see which underlying model is responding (debugging prompt
 * behavior, verifying a provider switch, etc.) can disable it here.
 *
 * The toggle calls ``PUT /api/config/identity-lock`` · `GET` on mount.
 * Two other unlock paths exist outside this UI (documented in-page):
 *   • env ``OCTOPUS_IDENTITY_LOCK=0`` at server start
 *   • user prompt starts with ``/raw`` (per-turn)
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import {
  AlertTriangleIcon,
  MoreHorizontalIcon,
  PlusIcon,
  RefreshCwIcon,
  TrashIcon,
} from "lucide-react";

import type { components } from "@/core/api/openapi-types";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { getBackendBaseURL } from "@/core/config";
import { jsonAuthHeaders } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";

// ─── Local API types · narrow to what the UI actually uses ──────
//
// These mirror the backend wire shape (see ``runtime/web/ai_mode_router.py``
// and ``runtime/web/path_denylist_router.py``). They're intentionally
// hand-rolled rather than codegen — the endpoints are recent and
// the openapi-ts pipeline hasn't picked them up yet.
type AiModeId = "efficiency" | "privacy";

interface AiModeOption {
  id: AiModeId;
  label: string;
  description: string;
  recommended_default?: boolean;
}

interface AiModeStatus {
  mode: AiModeId;
  recommended: AiModeId;
  device?: string | null;
  modes: AiModeOption[];
}

interface PathDenylistStatus {
  paths: string[];
}

// Static fallback so the AI-mode cards still render before the
// initial GET resolves (or if the endpoint is briefly unavailable).
const defaultAiModeOptions: AiModeOption[] = [
  {
    id: "efficiency",
    label: "效率模式",
    description: "优先使用云端高性能模型，响应更快、能力更强。",
  },
  {
    id: "privacy",
    label: "隐私模式",
    description: "优先使用本地模型，数据不离开本机。",
  },
];


// Pulled from the auto-generated OpenAPI types so backend changes
// to the ``IdentityLockResponse`` pydantic model propagate here
// without a hand-edit. See docs/adr/004-openapi-ts-codegen.md.
// The ``source`` field is typed as ``string`` in the generated
// file (FastAPI can't express the ``"runtime" | "env" | "default"``
// union through pydantic without a Literal); we re-narrow it for
// UI-side compile-time safety where we branch on it.
type LockStatus = components["schemas"]["IdentityLockResponse"] & {
  source: "runtime" | "env" | "default";
};

type ConstitutionProfile = "strict" | "normal" | "lax";

type ConstitutionProfileStatus = {
  profile: ConstitutionProfile;
  available: ConstitutionProfile[];
};

// LLM 语义安全 judge:enabled=当前是否接了真 judge;available=有无模型路由可接。
type JudgeStatus = {
  enabled: boolean;
  available: boolean;
};

export default function PrivacySettingsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Blurbs resolve live against the selected locale.
  const PROFILE_BLURB: Record<ConstitutionProfile, string> = {
    strict: t.privacySettings.profileStrictBlurb,
    normal: t.privacySettings.profileNormalBlurb,
    lax: t.privacySettings.profileLaxBlurb,
  };
  const [status, setStatus] = useState<LockStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<ConstitutionProfileStatus | null>(
    null,
  );
  const [profileBusy, setProfileBusy] = useState(false);
  const [judge, setJudge] = useState<JudgeStatus | null>(null);
  const [judgeBusy, setJudgeBusy] = useState(false);
  const [showFactoryResetDialog, setShowFactoryResetDialog] = useState(false);
  const [factoryResetConfirmText, setFactoryResetConfirmText] = useState("");
  const [factoryResetPending, setFactoryResetPending] = useState(false);

  // ── AI mode (efficiency / privacy) ──
  const [aiMode, setAiMode] = useState<AiModeStatus | null>(null);
  const [aiModeBusy, setAiModeBusy] = useState(false);

  // ── Path denylist ──
  const [denylist, setDenylist] = useState<PathDenylistStatus | null>(null);
  const [showAddPathDialog, setShowAddPathDialog] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [denylistBusy, setDenylistBusy] = useState(false);
  const [denylistMenuOpen, setDenylistMenuOpen] = useState<string | null>(null);

  const fetchAiMode = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/ai-mode`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as AiModeStatus;
      setAiMode(data);
    } catch {
      setAiMode(null);
    }
  }, []);

  const fetchDenylist = useCallback(async () => {
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/path-denylist`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as PathDenylistStatus;
      setDenylist({ paths: Array.isArray(data?.paths) ? data.paths : [] });
    } catch {
      setDenylist({ paths: [] });
    }
  }, []);

  useEffect(() => {
    fetch(`${getBackendBaseURL()}/api/config/identity-lock`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: LockStatus | null) => setStatus(j))
      .catch(() => setStatus(null));
    fetch(`${getBackendBaseURL()}/api/safety/constitution-profile`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: ConstitutionProfileStatus | null) => setProfile(j))
      .catch(() => setProfile(null));
    fetch(`${getBackendBaseURL()}/api/safety/llm-judge`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j: JudgeStatus | null) => setJudge(j))
      .catch(() => setJudge(null));
    fetchAiMode();
    fetchDenylist();
  }, [fetchAiMode, fetchDenylist]);

  async function selectAiMode(mode: AiModeId) {
    if (aiModeBusy || !aiMode) return;
    if (aiMode.mode === mode) return;
    // Optimistic update — rollback on failure.
    const prev = aiMode;
    setAiMode({ ...aiMode, mode });
    setAiModeBusy(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/ai-mode`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ mode }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next = (await res.json()) as AiModeStatus;
      setAiMode(next);
      const label = next.modes.find((m) => m.id === mode)?.label ?? mode;
      toast.success(`已切换到${label}`);
    } catch (e) {
      setAiMode(prev);
      toast.error(`切换 AI 模式失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setAiModeBusy(false);
    }
  }

  async function addDenylistPath() {
    const path = newPath.trim();
    if (!path) {
      toast.error("请输入有效路径");
      return;
    }
    setDenylistBusy(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/path-denylist`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ path }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(`已添加：${path}`);
      setNewPath("");
      setShowAddPathDialog(false);
      await fetchDenylist();
    } catch (e) {
      toast.error(`添加失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDenylistBusy(false);
    }
  }

  async function removeDenylistPath(path: string) {
    setDenylistBusy(true);
    setDenylistMenuOpen(null);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/path-denylist`, {
        method: "DELETE",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ path }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      toast.success(`已移除：${path}`);
      await fetchDenylist();
    } catch (e) {
      toast.error(`移除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDenylistBusy(false);
    }
  }

  async function setConstitutionProfile(name: ConstitutionProfile) {
    setProfileBusy(true);
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/safety/constitution-profile`,
        {
          method: "PUT",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({ profile: name }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next: ConstitutionProfileStatus = await res.json();
      setProfile(next);
      toast.success(t.privacySettings.toastProfileSwitched(name));
    } catch (e) {
      toast.error(t.privacySettings.toastProfileFailed(e instanceof Error ? e.message : String(e)));
    } finally {
      setProfileBusy(false);
    }
  }

  async function setJudgeEnabled(enabled: boolean) {
    if (judgeBusy) return;
    setJudgeBusy(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/safety/llm-judge`, {
        method: "PUT",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({ enabled }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next: JudgeStatus = await res.json();
      setJudge(next);
      toast.success(next.enabled ? "已开启 LLM 语义审查" : "已关闭 LLM 语义审查");
    } catch (e) {
      toast.error(
        `切换失败:${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setJudgeBusy(false);
    }
  }

  async function toggle(newLocked: boolean | null) {
    setBusy(true);
    try {
      const res = await fetch(
        `${getBackendBaseURL()}/api/config/identity-lock`,
        {
          method: "PUT",
          headers: jsonAuthHeaders(),
          body: JSON.stringify({ locked: newLocked }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const next: LockStatus = await res.json();
      setStatus(next);
      toast.success(
        newLocked === null
          ? t.privacySettings.toastRestoreDefault
          : newLocked
            ? t.privacySettings.toastLockOn
            : t.privacySettings.toastLockOff,
      );
    } catch (e) {
      toast.error(t.privacySettings.toastToggleFailed(e instanceof Error ? e.message : String(e)));
    } finally {
      setBusy(false);
    }
  }

  async function handleFactoryReset() {
    if (factoryResetConfirmText !== "RESET OCTOPUS") {
      toast.error(t.accountSettings.factoryResetTypeMismatch);
      return;
    }
    setFactoryResetPending(true);
    try {
      const res = await fetch(`${getBackendBaseURL()}/api/system/factory-reset`, {
        method: "POST",
        headers: jsonAuthHeaders(),
        body: JSON.stringify({
          confirm: "RESET OCTOPUS",
          clear_user_install_state: true,
        }),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        throw new Error(text || `Factory reset failed: ${res.status}`);
      }
      clearOctopusBrowserState();
      queryClient.removeQueries({ queryKey: ["threads"] });
      queryClient.removeQueries({ queryKey: ["projects"] });
      toast.success(t.accountSettings.factoryResetSuccess);
      setShowFactoryResetDialog(false);
      setFactoryResetConfirmText("");
      navigate("/workspace/realtime/new", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t.accountSettings.factoryResetFailed);
    } finally {
      setFactoryResetPending(false);
    }
  }

  const locked = status?.locked ?? true;
  const source = status?.source ?? "default";

  return (
    <div className="flex flex-col gap-6 text-sm">
      {/* ─── Identity Lock toggle ─── */}
      <div className="rounded-lg border border-border/50 bg-card/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h3 className="text-base font-semibold text-foreground">
              {t.privacySettings.identityLockTitle}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {t.privacySettings.identityLockDesc}
            </p>
          </div>
          <button
            type="button"
            onClick={() => toggle(!locked)}
            disabled={busy}
            aria-pressed={locked}
            className={cn(
              "shrink-0 relative inline-flex h-7 w-12 items-center rounded-full transition-colors",
              locked ? "bg-primary" : "bg-muted",
              busy && "opacity-60 cursor-not-allowed",
            )}
          >
            <span
              className={cn(
                "inline-block h-5 w-5 rounded-full bg-background shadow transition-transform",
                locked ? "translate-x-6" : "translate-x-1",
              )}
            />
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px]">
          <span
            className={cn(
              "rounded px-1.5 py-0.5 font-medium",
              locked
                ? "bg-emerald-500/10 text-emerald-600"
                : "bg-amber-500/10 text-amber-600",
            )}
          >
            {locked ? t.privacySettings.lockedTag : t.privacySettings.unlockedTag}
          </span>
          <span className="text-muted-foreground/70">
            {t.privacySettings.sourceLabel}: <code>{source}</code>
          </span>
          {source === "runtime" && (
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2"
              onClick={() => toggle(null)}
              disabled={busy}
            >
              {t.privacySettings.restoreDefault}
            </button>
          )}
        </div>
      </div>

      {/* ─── AI mode (efficiency / privacy) ─── */}
      <div className="rounded-lg border border-border/50 bg-card/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h3 className="text-base font-semibold text-foreground">AI 模式</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {(() => {
                if (!aiMode) return "正在检测设备配置…";
                const recLabel =
                  aiMode.modes.find((m) => m.id === aiMode.recommended)?.label ??
                  (aiMode.recommended === "efficiency" ? "效率模式" : "隐私模式");
                return `根据本机设备配置，推荐使用：${recLabel}`;
              })()}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            onClick={fetchAiMode}
            disabled={aiModeBusy}
          >
            <RefreshCwIcon className="mr-1 h-3 w-3" /> 检测
          </Button>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {(aiMode?.modes ?? defaultAiModeOptions).map((opt) => {
            const active = aiMode?.mode === opt.id;
            const recommended =
              !!opt.recommended_default || aiMode?.recommended === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => selectAiMode(opt.id)}
                disabled={aiModeBusy}
                aria-pressed={active}
                className={cn(
                  "flex flex-col gap-2 rounded-lg border p-4 text-left transition",
                  active
                    ? "border-primary bg-primary/5 ring-1 ring-primary/40"
                    : "border-border/50 hover:border-primary/40",
                  aiModeBusy && "opacity-60 cursor-not-allowed",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium">{opt.label}</span>
                  <div className="flex items-center gap-1.5">
                    {recommended && (
                      <span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        推荐
                      </span>
                    )}
                    {active && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        已启用
                      </span>
                    )}
                  </div>
                </div>
                <p className="text-[11px] leading-snug text-muted-foreground">
                  {opt.description}
                </p>
              </button>
            );
          })}
        </div>
        {aiMode?.device && (
          <div className="mt-3 text-[11px] text-muted-foreground/80">
            设备：<code>{aiMode.device}</code>
          </div>
        )}
      </div>

      {/* ─── Path denylist (folders the agent can't read) ─── */}
      <div className="rounded-lg border border-border/50 bg-card/50 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h3 className="text-base font-semibold text-foreground">
              不可读取文件夹
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              添加后，Agent 将拒绝读取或写入这些路径下的任何文件。
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            className="h-8 text-xs"
            onClick={() => {
              setNewPath("");
              setShowAddPathDialog(true);
            }}
          >
            <PlusIcon className="mr-1 h-3 w-3" /> 新增
          </Button>
        </div>

        <div className="mt-4 rounded-lg border border-border/40 divide-y divide-border/40">
          {(denylist?.paths ?? []).length === 0 ? (
            <div className="px-4 py-6 text-center text-xs text-muted-foreground">
              暂无 — 默认黑名单（.vscode / AppData / .cache 等）已生效
            </div>
          ) : (
            (denylist?.paths ?? []).map((p) => (
              <div
                key={p}
                className="flex items-center justify-between gap-3 px-4 py-3"
              >
                <code className="truncate font-mono text-xs text-foreground">
                  {p}
                </code>
                <div className="relative shrink-0">
                  <button
                    type="button"
                    aria-label={`操作 ${p}`}
                    className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    onClick={() =>
                      setDenylistMenuOpen((cur) => (cur === p ? null : p))
                    }
                    disabled={denylistBusy}
                  >
                    <MoreHorizontalIcon className="h-4 w-4" />
                  </button>
                  {denylistMenuOpen === p && (
                    <div
                      role="menu"
                      className="absolute right-0 top-full z-10 mt-1 min-w-[120px] rounded-md border border-border bg-popover p-1 shadow-md"
                    >
                      <button
                        type="button"
                        role="menuitem"
                        className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs text-destructive hover:bg-destructive/10"
                        onClick={() => removeDenylistPath(p)}
                        disabled={denylistBusy}
                      >
                        <TrashIcon className="h-3 w-3" /> 删除
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ─── Constitution profile ─── */}
      <div className="rounded-lg border border-border/50 bg-card/50 p-5">
        <h3 className="text-base font-semibold text-foreground">
          {t.privacySettings.profileTitle}
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {t.privacySettings.profileDescPrefix}
          <a
            href="https://github.com/your-org/octopus-agent/blob/main/docs/constitution.md"
            className="underline underline-offset-2"
          >
            {t.privacySettings.profileDescDocLink}
          </a>
          {t.privacySettings.profileDescSuffix}
        </p>

        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {(["strict", "normal", "lax"] as ConstitutionProfile[]).map(
            (name) => {
              const active = profile?.profile === name;
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => setConstitutionProfile(name)}
                  disabled={profileBusy || active}
                  className={cn(
                    "flex flex-col gap-1 rounded-lg border p-3 text-left transition",
                    active
                      ? "border-primary bg-primary/5 ring-1 ring-primary/40"
                      : "border-border/50 hover:border-primary/40",
                    profileBusy && "opacity-60 cursor-not-allowed",
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm font-medium uppercase">
                      {name}
                    </span>
                    {active && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        {t.privacySettings.activeTag}
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-muted-foreground leading-snug">
                    {PROFILE_BLURB[name]}
                  </div>
                </button>
              );
            },
          )}
        </div>
        {profile === null && (
          <div className="mt-3 text-[11px] text-muted-foreground">
            {t.privacySettings.profileLoadFailed}
          </div>
        )}

        {/* LLM 语义审查 judge —— 运行时开关(无需重启)。上面的 profile 决定
            judge 命中是硬拦截(strict)还是仅审计(normal/lax)。 */}
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-border/50 p-3">
          <div className="min-w-0">
            <div className="text-sm font-medium">LLM 语义审查 (judge)</div>
            <div className="text-[11px] text-muted-foreground leading-snug">
              每条出口消息多一次模型调用,审查诱导钓鱼 / 越权抓取等语义违规。默认关(有成本)。
              {judge && !judge.available && " 当前无模型路由,不可开启。"}
            </div>
          </div>
          <Switch
            checked={!!judge?.enabled}
            disabled={judgeBusy || !judge || !judge.available}
            onCheckedChange={(v) => setJudgeEnabled(v)}
          />
        </div>
      </div>

      {/* ─── Alternative unlock paths ─── */}
      <div className="rounded-lg border border-border/40 bg-muted/20 p-4">
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {t.privacySettings.alternativeUnlockTitle}
        </h4>
        <ul className="space-y-1.5 text-xs text-muted-foreground/90">
          <li>
            <strong className="text-foreground">{t.privacySettings.altEnvLabel}</strong>
            {" "}{t.privacySettings.altEnvDesc}
          </li>
          <li>
            <strong className="text-foreground">{t.privacySettings.altTurnLabel}</strong>
            {" "}{t.privacySettings.altTurnDesc}
          </li>
          <li>
            <strong className="text-foreground">{t.privacySettings.altApiLabel}</strong>
            {" "}{t.privacySettings.altApiDesc}
          </li>
        </ul>
      </div>

      <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h3 className="text-base font-semibold text-destructive">
              {t.accountSettings.factoryResetTitle}
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              {t.accountSettings.factoryResetDescription}
            </p>
          </div>
          <Button
            variant="destructive"
            size="sm"
            className="h-8 text-xs"
            onClick={() => setShowFactoryResetDialog(true)}
          >
            {t.accountSettings.factoryResetTitle}
          </Button>
        </div>
      </div>

      <Dialog open={showAddPathDialog} onOpenChange={setShowAddPathDialog}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>新增不可读取文件夹</DialogTitle>
            <DialogDescription>
              输入绝对路径（例如 <code>C:\\Users\\you\\secrets</code> 或{" "}
              <code>/home/you/.ssh</code>）。Agent 将拒绝读写该目录下的任何文件。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <Label htmlFor="denylist-path-input" className="text-sm">
              路径
            </Label>
            <Input
              id="denylist-path-input"
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              placeholder="C:\\Users\\you\\secrets"
              className="h-9 font-mono text-xs"
              autoFocus
            />
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={() => setShowAddPathDialog(false)}
              disabled={denylistBusy}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={addDenylistPath}
              disabled={denylistBusy || !newPath.trim()}
            >
              {denylistBusy ? t.common.loading : "确认"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showFactoryResetDialog} onOpenChange={setShowFactoryResetDialog}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangleIcon className="size-5" />
              {t.accountSettings.factoryResetTitle}
            </DialogTitle>
            <DialogDescription>
              {t.accountSettings.factoryResetDialogDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-4">
            <Label htmlFor="factory-reset-confirm" className="text-sm">
              {t.accountSettings.factoryResetTypeToConfirm}
            </Label>
            <Input
              id="factory-reset-confirm"
              value={factoryResetConfirmText}
              onChange={(e) => setFactoryResetConfirmText(e.target.value)}
              placeholder="RESET OCTOPUS"
              className="h-9"
            />
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => setShowFactoryResetDialog(false)}>
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={handleFactoryReset}
              disabled={factoryResetConfirmText !== "RESET OCTOPUS" || factoryResetPending}
            >
              {factoryResetPending
                ? t.accountSettings.factoryResetPending
                : t.accountSettings.factoryResetConfirm}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function clearOctopusBrowserState(): void {
  if (typeof window === "undefined") return;
  const prefixes = ["octopus", "code:", "team:", "realtime:"];
  const exactKeys = new Set([
    "token",
    "octopus_auth_token",
    "octopus_user",
    "octopus_auth_ts",
  ]);
  for (const store of [window.localStorage, window.sessionStorage]) {
    for (let i = store.length - 1; i >= 0; i -= 1) {
      const key = store.key(i);
      if (!key) continue;
      if (exactKeys.has(key) || prefixes.some((prefix) => key.startsWith(prefix))) {
        store.removeItem(key);
      }
    }
  }
  window.dispatchEvent(new Event("storage"));
}
