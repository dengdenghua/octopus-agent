/* Implementation note. */
import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import {
  CheckIcon,
  ChevronRightIcon,
  MessageCircleIcon,
  PlusIcon,
  SettingsIcon,
  XIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ChannelCredentialDialog } from "@/components/workspace/channel-credential-dialog";
import { ChannelPairingsSheet } from "@/components/workspace/channel-pairings-sheet";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type ChannelRow = {
  channel_id: string;
  type: string;
  platform: string;
  connected: boolean;
  display_name: string;
  description: string;
  help_url: string;
  metrics: {
    pairings_count: number;
    group_count: number;
    pending_count: number;
  };
  assigned_agent_id?: string | null;
};

type AgentLite = {
  id: string;
  display_name?: string;
  avatar_url?: string | null;
};

// Implementation note.
const PLATFORM_COLORS: Record<string, string> = {
  wechat: "bg-[#07c160] text-white",
  dingtalk: "bg-[#1677ff] text-white",
  feishu: "bg-[#3370ff] text-white",
  telegram: "bg-[#26a5e4] text-white",
  slack: "bg-[#4a154b] text-white",
  discord: "bg-[#5865f2] text-white",
  signal: "bg-[#3a76f0] text-white",
  whatsapp: "bg-[#25d366] text-white",
  email: "bg-[#ea4335] text-white",
  sms: "bg-[#f22f46] text-white",
  mattermost: "bg-[#0058cc] text-white",
  matrix: "bg-[#0dbd8b] text-white",
  wecom: "bg-[#07c160] text-white",
  qqbot: "bg-[#12b7f5] text-white",
  teams: "bg-[#6264a7] text-white",
  line: "bg-[#06c755] text-white",
  homeassistant: "bg-[#41bdf5] text-white",
  bluebubbles: "bg-[#34c759] text-white",
  ntfy: "bg-[#317f6e] text-white",
  webhooks: "bg-[#f59e0b] text-white",
  google_chat: "bg-[#00ac47] text-white",
  simplex: "bg-[#f76b1c] text-white",
  open_webui: "bg-[#8b5cf6] text-white",
  yuanbao: "bg-[#006eff] text-white",
  other: "bg-muted/70 text-muted-foreground",
};

// Implementation note.
const PLATFORM_ICONS: Record<string, string> = {
  wechat: "💬",
  dingtalk: "📌",
  feishu: "🐦",
  telegram: "✈️",
  slack: "#",
  discord: "🎮",
  signal: "🔒",
  whatsapp: "📱",
  email: "✉️",
  sms: "📩",
  mattermost: "📡",
  matrix: "🟢",
  wecom: "💼",
  qqbot: "🐧",
  teams: "👥",
  line: "💬",
  homeassistant: "🏠",
  bluebubbles: "🔵",
  ntfy: "🔔",
  webhooks: "🪝",
  google_chat: "💬",
  simplex: "🔐",
  open_webui: "🌐",
  yuanbao: "💎",
  other: "•",
};

const PLATFORM_CATEGORIES: Record<string, string> = {
  im: "即时通讯",
  china: "国内平台",
  email_sms: "邮件/短信",
  smart_home: "智能家居",
  dev_tools: "开发工具",
};

const PLATFORM_CATEGORY_MAP: Record<string, string> = {
  telegram: "im",
  discord: "im",
  slack: "im",
  signal: "im",
  whatsapp: "im",
  matrix: "im",
  mattermost: "im",
  simplex: "im",
  line: "im",
  wechat: "china",
  feishu: "china",
  dingtalk: "china",
  wecom: "china",
  qqbot: "china",
  yuanbao: "china",
  email: "email_sms",
  sms: "email_sms",
  homeassistant: "smart_home",
  ntfy: "smart_home",
  webhooks: "dev_tools",
  open_webui: "dev_tools",
  google_chat: "dev_tools",
  bluebubbles: "dev_tools",
  teams: "dev_tools",
};

const CATEGORY_ORDER = ["im", "china", "email_sms", "smart_home", "dev_tools"];

export default function ChannelsPage() {
  const { t } = useI18n();
  const [rows, setRows] = useState<ChannelRow[]>([]);
  const [agents, setAgents] = useState<AgentLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  /* Implementation note. */
  const [assigningId, setAssigningId] = useState<string | null>(null);
  /* Implementation note. */
  const [credPlatform, setCredPlatform] = useState<string | null>(null);
  /* Implementation note. */
  const [pairingsForId, setPairingsForId] = useState<string | null>(null);

  // Implementation note.
  const loadAll = async () => {
    setLoading(true);
    try {
      const [chRes, agRes] = await Promise.all([
        fetch(`${getBackendBaseURL()}/api/channels`),
        fetch(`${getBackendBaseURL()}/api/agents`),
      ]);
      if (!chRes.ok) throw new Error(`Failed to load channels: ${chRes.status}`);
      const ch = (await chRes.json()) as ChannelRow[];
      setRows(ch);
      if (agRes.ok) {
        const ag = (await agRes.json()) as AgentLite[];
        setAgents(ag);
      }
      setError(null);
    } catch (e) {
      swallow(e);
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await loadAll();
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const assignRow = rows.find((r) => r.channel_id === assigningId);

  async function assignAgent(channelId: string, agentId: string) {
    try {
      const r = await fetch(`/api/channels/${channelId}/assistant`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ agent_id: agentId }),
      });
      if (!r.ok) {
        const detail = await r.text();
        throw new Error(detail || r.statusText);
      }
      toast.success(t.channels.toastAgentBound);
      setAssigningId(null);
      await loadAll();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.channels.toastBindFailed);
    }
  }

  async function unassignAgent(channelId: string) {
    try {
      const r = await fetch(`/api/channels/${channelId}/assistant`, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error(r.statusText);
      toast.success(t.channels.toastAgentUnbound);
      await loadAll();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.channels.toastUnbindFailed);
    }
  }

  const connectedCount = useMemo(
    () => rows.filter((r) => r.connected).length,
    [rows],
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="px-4 pb-4">
        <div className="ui-density-stack mx-auto flex w-full max-w-6xl flex-col">
          {/* Implementation note. */}
          <section className="workspace-panel ui-density-panel rounded-[1.75rem]">
            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary ring-1 ring-primary/10">
                    <MessageCircleIcon className="size-5" />
                  </div>
                  <div>
                    <div className="text-muted-foreground text-xs font-medium uppercase tracking-[0.18em]">
                      Channel Ops
                    </div>
                    <h1 className="text-xl font-semibold tracking-tight">{t.channels.title}</h1>
                  </div>
                </div>
                <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                  {t.channels.pageDescription}
                  <span className="ml-1 text-muted-foreground/80">
                    {t.channels.localDataNote}
                  </span>
                </p>
              </div>

              <div className="grid min-w-[220px] grid-cols-2 gap-2 tabular-nums">
                <div className="rounded-xl border border-border/60 bg-background/62 px-3 py-2">
                  <div className="text-[11px] text-muted-foreground">{t.channels.channelCount(rows.length)}</div>
                  <div className="mt-1 text-lg font-semibold">{rows.length}</div>
                </div>
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/[0.06] px-3 py-2">
                  <div className="flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                    <span className={cn("inline-block size-1.5 rounded-full", connectedCount > 0 ? "bg-emerald-500" : "bg-muted-foreground/40")} />
                    {t.channels.connectedCount(connectedCount)}
                  </div>
                  <div className="mt-1 text-lg font-semibold text-emerald-600 dark:text-emerald-400">{connectedCount}</div>
                </div>
              </div>
            </div>
          </section>

          {loading && (
            <div className="text-sm text-muted-foreground">
              {t.channels.loading}
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-600">
              {error}
            </div>
          )}

          {!loading && !error && rows.length === 0 && (
            <div className="rounded-xl border border-dashed border-border/60 px-6 py-10 text-center text-sm text-muted-foreground">
              {t.channels.noRegistered}
            </div>
          )}

          {!loading && !error && rows.length > 0 && (() => {
            const grouped: Record<string, ChannelRow[]> = {};
            const otherRows: ChannelRow[] = [];
            for (const row of rows) {
              const cat = PLATFORM_CATEGORY_MAP[row.platform];
              if (cat) {
                if (!grouped[cat]) grouped[cat] = [];
                grouped[cat].push(row);
              } else {
                otherRows.push(row);
              }
            }
            const sections: { key: string; label: string; items: ChannelRow[] }[] = [];
            for (const cat of CATEGORY_ORDER) {
              if (grouped[cat] && grouped[cat].length > 0) {
                sections.push({ key: cat, label: PLATFORM_CATEGORIES[cat] ?? cat, items: grouped[cat] });
              }
            }
            if (otherRows.length > 0) {
              sections.push({ key: "other", label: "其他", items: otherRows });
            }
            return sections.map((section) => (
              <div key={section.key}>
                <h2 className="mb-3 text-sm font-semibold text-muted-foreground">{section.label}</h2>
                <div className="grid gap-4 md:grid-cols-2">
                  {section.items.map((row, index) => (
                    <ChannelCard
                      key={row.channel_id || `${row.platform}-${index}`}
                      row={row}
                      agents={agents}
                      onRequestAssign={() => setAssigningId(row.channel_id)}
                      onRequestCredential={() => setCredPlatform(row.platform)}
                      onRequestPairings={() => setPairingsForId(row.channel_id)}
                    />
                  ))}
                </div>
              </div>
            ));
          })()}
        </div>
      </WorkspaceBody>

      {/* Implementation note. */}
      {pairingsForId &&
        (() => {
          const row = rows.find((r) => r.channel_id === pairingsForId);
          if (!row) return null;
          return (
            <ChannelPairingsSheet
              open={true}
              onOpenChange={(o) => !o && setPairingsForId(null)}
              channelId={pairingsForId}
              displayName={row.display_name}
            />
          );
        })()}

      {/* Implementation note. */}
      {credPlatform &&
        (() => {
          const row = rows.find((r) => r.platform === credPlatform);
          if (!row) return null;
          return (
            <ChannelCredentialDialog
              open={true}
              onOpenChange={(o) => !o && setCredPlatform(null)}
              platform={credPlatform}
              displayName={row.display_name}
              helpUrl={row.help_url}
              hasExisting={row.connected}
              onSaved={() => void loadAll()}
              onDeleted={() => void loadAll()}
            />
          );
        })()}

      {/* Implementation note. */}
      <Dialog
        open={!!assigningId}
        onOpenChange={(open) => !open && setAssigningId(null)}
      >
        <DialogContent className="max-w-md max-h-[70vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-base">
              <PlusIcon className="size-4" />
              {t.channels.assignDialogTitle(assignRow?.display_name ?? "")}
            </DialogTitle>
            <DialogDescription className="text-[12px]">
              {t.channels.assignDialogDesc}
            </DialogDescription>
          </DialogHeader>

          <div className="overflow-y-auto flex-1 mt-2">
            {agents.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/60 px-4 py-8 text-center text-[12px] text-muted-foreground">
                {t.channels.noAgentsAvailable}
              </div>
            ) : (
              <ul className="space-y-1">
                {agents.map((a, index) => {
                  const isCurrent = assignRow?.assigned_agent_id === a.id;
                  const agentKey = a.id?.trim() || `${a.display_name ?? "agent"}-${index}`;
                  return (
                    <li key={agentKey}>
                      <button
                        type="button"
                        onClick={() =>
                          assigningId &&
                          void assignAgent(assigningId, a.id)
                        }
                        className={cn(
                          "w-full flex items-center gap-3 rounded-lg border border-border/40",
                          "bg-background px-3 py-2 text-left transition-colors",
                          "hover:bg-muted/40 hover:border-border/80",
                          isCurrent &&
                            "border-primary/40 bg-primary/5 hover:border-primary/60",
                        )}
                      >
                        {a.avatar_url ? (
                          <img
                            src={a.avatar_url}
                            alt=""
                            className="size-8 rounded-md object-cover"
                          />
                        ) : (
                          <div className="flex size-8 items-center justify-center rounded-md bg-muted text-xs font-medium text-muted-foreground">
                            {(a.display_name ?? a.id).charAt(0).toUpperCase()}
                          </div>
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="text-[13px] font-medium truncate">
                            {a.display_name || a.id}
                          </div>
                          <div className="text-[11px] text-muted-foreground truncate">
                            {a.id}
                          </div>
                        </div>
                        {isCurrent && (
                          <CheckIcon className="size-4 text-primary shrink-0" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {assignRow?.assigned_agent_id && (
            <div className="mt-3 pt-3 border-t border-border/40">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void unassignAgent(assignRow.channel_id);
                  setAssigningId(null);
                }}
                className="w-full text-[12px] text-muted-foreground hover:text-destructive"
              >
                <XIcon className="mr-1.5 size-3.5" />
                {t.channels.unassignCurrent}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </WorkspaceContainer>
  );
}

function ChannelCard({
  row, agents, onRequestAssign, onRequestCredential, onRequestPairings,
}: {
  row: ChannelRow;
  agents: AgentLite[];
  onRequestAssign: () => void;
  onRequestCredential: () => void;
  onRequestPairings: () => void;
}) {
  const { t } = useI18n();
  const colorCls = row.connected
    ? PLATFORM_COLORS[row.platform] ?? PLATFORM_COLORS.other
    : "bg-muted/70 text-muted-foreground";
  const icon = PLATFORM_ICONS[row.platform] ?? "•";
  const assignedAgent = agents.find((a) => a.id === row.assigned_agent_id);

  return (
    <div
      className={cn(
        "workspace-panel ui-density-panel group relative overflow-hidden rounded-2xl border bg-background/60",
        "transition-colors hover:border-border/80",
        row.connected ? "border-emerald-500/20" : "border-border/60",
      )}
    >
      <div
        className={cn(
          "absolute inset-x-0 top-0 h-1",
          row.connected ? "bg-emerald-500/55" : "bg-muted",
        )}
      />
      {/* Implementation note. */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div
            className={cn(
              "flex size-11 items-center justify-center rounded-xl text-lg shadow-sm ring-1 ring-black/[0.04] dark:ring-white/[0.06]",
              colorCls,
            )}
          >
            <span>{icon}</span>
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold leading-5">{row.display_name}</div>
            <div className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">
              {row.description}
              {row.help_url && !row.connected && (
                <a
                  href={row.help_url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 text-primary underline underline-offset-2 hover:opacity-80 cursor-pointer"
                  onClick={(e) => {
                    console.log("Help URL clicked:", row.help_url);
                    if (!row.help_url || row.help_url === "#") {
                      e.preventDefault();
                      toast.info(t.channels.helpDocsComingSoon);
                    }
                  }}
                >
                  {t.channels.howToSetup}
                </a>
              )}
            </div>
          </div>
        </div>
        <span
          className={cn(
            "shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium",
            row.connected
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
              : "border-border/60 bg-muted/60 text-muted-foreground",
          )}
        >
          {row.connected ? t.channels.connectedBadge : t.channels.notLinked}
        </span>
      </div>

      {/* Implementation note. */}
      <div className="mt-4 grid grid-cols-3 gap-2">
        <Metric
          label={t.channels.pairedUsers}
          value={row.metrics.pairings_count}
          onClick={row.connected ? onRequestPairings : undefined}
        />
        <Metric
          label={t.channels.pairedGroups}
          value={row.metrics.group_count}
          onClick={row.connected ? onRequestPairings : undefined}
        />
        <Metric
          label={t.channels.pendingRequests}
          value={row.metrics.pending_count}
          onClick={row.connected ? onRequestPairings : undefined}
        />
      </div>

      {/* Implementation note. */}
      <div className="mt-3">
        {row.assigned_agent_id ? (
          <button
            type="button"
            onClick={onRequestAssign}
            className={cn(
              "group flex w-full items-center justify-between rounded-xl",
              "border border-primary/20 bg-primary/[0.04] px-3 py-2.5 text-left",
              "hover:border-primary/40 hover:bg-primary/[0.08] transition-colors",
            )}
            title={t.channels.clickToChangeAgent}
          >
            <div className="flex items-center gap-2">
              {assignedAgent?.avatar_url ? (
                <img
                  src={assignedAgent.avatar_url}
                  alt=""
                  className="size-6 rounded-md object-cover"
                />
              ) : (
                <div className="flex size-6 items-center justify-center rounded-md bg-primary/15 text-[10px] font-medium text-primary">
                  {(
                    assignedAgent?.display_name ?? row.assigned_agent_id
                  )
                    .charAt(0)
                    .toUpperCase()}
                </div>
              )}
              <div>
                <div className="text-[12px] font-medium">
                  {assignedAgent?.display_name ?? row.assigned_agent_id}
                </div>
                <div className="text-[10px] text-muted-foreground">
                  {t.channels.handlingMessages}
                </div>
              </div>
            </div>
            <ChevronRightIcon className="size-3.5 text-muted-foreground opacity-60 transition-transform group-hover:translate-x-0.5" />
          </button>
        ) : (
          <button
            type="button"
            onClick={onRequestAssign}
            className={cn(
              "group flex w-full items-center justify-between rounded-xl",
              "border border-dashed border-border/60 bg-muted/18 px-3 py-2.5 text-left",
              "hover:border-border hover:bg-muted/40 transition-colors",
            )}
          >
            <div className="flex items-center gap-2">
              <PlusIcon className="size-3.5 text-muted-foreground" />
              <div>
                <div className="text-[12px] font-medium">{t.channels.configureAgent}</div>
                <div className="text-[10px] text-muted-foreground">
                  {t.channels.configureAgentHint}
                </div>
              </div>
            </div>
            <ChevronRightIcon className="size-3.5 text-muted-foreground opacity-60 transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </div>

      {/* Implementation note. */}
      <div className="mt-3 flex gap-2 border-t border-border/50 pt-3">
        {row.connected ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full text-xs"
            onClick={onRequestCredential}
          >
            <SettingsIcon className="mr-1.5 size-3" />
            {t.channels.rebindOrUnbind}
          </Button>
        ) : (
          <Button
            variant="outline"
            size="sm"
            className="h-8 w-full text-xs"
            onClick={onRequestCredential}
          >
            <SettingsIcon className="mr-1.5 size-3" />
            {t.channels.connectBot}
          </Button>
        )}
      </div>
    </div>
  );
}

function Metric({
  label, value, onClick,
}: {
  label: string;
  value: number;
  /* Implementation note. */
  onClick?: () => void;
}) {
  const body = (
    <>
      <div className="text-[14px] font-semibold tabular-nums">{value}</div>
      <div className="mt-0.5 text-[10px] text-muted-foreground">{label}</div>
    </>
  );
  const baseClass = cn(
    "rounded-lg border border-border/45 bg-background/70",
    "px-2 py-1.5 text-center",
  );
  if (!onClick) {
    return <div className={baseClass}>{body}</div>;
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        baseClass,
        "transition-colors cursor-pointer",
        "hover:border-primary/40 hover:bg-primary/[0.04]",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/30",
      )}
      title="点击查看详情"
    >
      {body}
    </button>
  );
}
