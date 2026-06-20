import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { XIcon, UsersIcon } from "lucide-react";

import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { Button } from "@/components/ui/button";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import {
  getPairingRequests,
  approvePairingRequest,
  rejectPairingRequest,
  isChannelNotImplemented,
} from "@/core/channels/api";
import type {
  ChannelName,
  PairingRequest,
  PairingStatus,
} from "@/core/channels/api";
import { cn } from "@/lib/utils";

const CHANNEL_NAMES: Record<string, string> = {
  dingtalk: "DingTalk",
  wechat: "WeChat",
  feishu: "Feishu",
  telegram: "Telegram",
  slack: "Slack",
  wecom: "WeCom",
  discord: "Discord",
};

const ALL_CHANNELS: ChannelName[] = [
  "dingtalk",
  "wechat",
  "feishu",
  "telegram",
  "slack",
  "wecom",
];

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (e) {
    swallow(e);
    return iso;
  }
}

function PairingRequestRow({
  req,
  onApprove,
  onReject,
  loading,
}: {
  req: PairingRequest;
  onApprove: () => void;
  onReject: () => void;
  loading: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="workspace-panel-subtle group flex items-center gap-3 rounded-lg px-4 py-3 transition-all duration-200">
      {req.user_avatar ? (
        <img
          src={req.user_avatar}
          alt=""
          className="size-9 rounded-lg object-cover ring-1 ring-border/50"
        />
      ) : (
        <div className="bg-gradient-to-br from-primary/12 to-primary/5 text-primary flex size-9 shrink-0 items-center justify-center rounded-lg text-sm font-bold">
          {req.user_name.charAt(0)}
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{req.user_name}</span>
          <span className="bg-muted text-muted-foreground rounded px-1.5 py-0.5 text-[10px]">
            {CHANNEL_NAMES[req.channel] ?? req.channel}
          </span>
          {req.group_name && (
            <span className="text-muted-foreground text-xs">
              · {req.group_name}
            </span>
          )}
        </div>
        <div className="text-muted-foreground mt-0.5 text-xs">
          {t.pairing.requestedAt}: {formatTime(req.created_at)}
          {" · "}
          {t.pairing.expiresAt}: {formatTime(req.expires_at)}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          disabled={loading}
          onClick={onReject}
        >
          {t.pairing.reject}
        </Button>
        <Button
          size="sm"
          className="h-7 text-xs"
          disabled={loading}
          onClick={onApprove}
        >
          {t.pairing.approve}
        </Button>
      </div>
    </div>
  );
}

export default function PairingPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [filterChannel, setFilterChannel] = useState<ChannelName | "">("");
  const [filterStatus, setFilterStatus] = useState<PairingStatus | "">("");
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [toast, setToast] = useState<{ text: string; ok: boolean } | null>(
    null,
  );

  const showToast = (text: string, ok: boolean) => {
    setToast({ text, ok });
    setTimeout(() => setToast(null), 3000);
  };

  const { data, isLoading, error } = useQuery({
    queryKey: ["pairing-requests", filterChannel, filterStatus],
    queryFn: () =>
      getPairingRequests({
        channel: filterChannel || undefined,
        status: filterStatus || undefined,
      }),
    retry: false,
  });
  const notImplemented = isChannelNotImplemented(error);

  const approveMutation = useMutation({
    mutationFn: approvePairingRequest,
    onMutate: (id) => setActionLoading(id),
    onSuccess: () => {
      setActionLoading(null);
      showToast(t.pairing.approveSuccess, true);
      void queryClient.invalidateQueries({ queryKey: ["pairing-requests"] });
    },
    onError: () => {
      setActionLoading(null);
      showToast(t.pairing.operationFailed, false);
    },
  });

  const rejectMutation = useMutation({
    mutationFn: rejectPairingRequest,
    onMutate: (id) => setActionLoading(id),
    onSuccess: () => {
      setActionLoading(null);
      showToast(t.pairing.rejectSuccess, true);
      void queryClient.invalidateQueries({ queryKey: ["pairing-requests"] });
    },
    onError: () => {
      setActionLoading(null);
      showToast(t.pairing.operationFailed, false);
    },
  });

  const hasFilters = filterChannel || filterStatus;
  const requests = data?.requests ?? [];
  const pendingRequests = requests.filter((r) => r.status === "pending");

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-4 py-2">
          {/* Header */}
          <section className="workspace-panel rounded-[1.75rem] px-5 py-5 md:px-6">
            <div className="text-muted-foreground mb-1 text-xs font-medium uppercase tracking-[0.18em]">
              IM Channels
            </div>
            <div className="flex items-center gap-2 text-xl font-semibold tracking-tight">
              <div className="page-header-icon flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-primary/15 to-primary/5">
                <UsersIcon className="size-3.5 text-primary" />
              </div>
              {t.pairing.title}
            </div>
            <p className="text-muted-foreground mt-1 text-sm">
              {t.pairing.description}
            </p>
          </section>

          {/* Coming-soon state · backend endpoints not yet implemented */}
          {notImplemented && (
            <div className="workspace-panel rounded-[1.75rem] px-5 py-10 md:px-6">
              <div className="flex flex-col items-center text-center">
                <div className="text-muted-foreground/40 mb-3 text-5xl">🚧</div>
                <div className="text-base font-semibold">
                  {t.pairing.notImplementedTitle}
                </div>
                <div className="text-muted-foreground mt-2 max-w-md text-sm">
                  {t.pairing.notImplementedDesc}
                </div>
              </div>
            </div>
          )}

          {/* Filters + Pending · hidden in coming-soon state */}
          {!notImplemented && (
            <>
              <div className="workspace-panel rounded-[1.75rem] px-5 py-4 md:px-6">
                <div className="flex flex-wrap items-center gap-2">
                  {hasFilters && (
                    <span className="text-muted-foreground text-xs">
                      {t.pairing.currentFilters}:
                    </span>
                  )}
                  {filterChannel && (
                    <FilterTag
                      label={`${t.pairing.filterChannel}: ${CHANNEL_NAMES[filterChannel] ?? filterChannel}`}
                      onRemove={() => setFilterChannel("")}
                    />
                  )}
                  {filterStatus && (
                    <FilterTag
                      label={`${t.pairing.filterStatus}: ${t.pairing[`status${filterStatus.charAt(0).toUpperCase()}${filterStatus.slice(1)}` as keyof typeof t.pairing] as string}`}
                      onRemove={() => setFilterStatus("")}
                    />
                  )}
                  <div className="ml-auto flex items-center gap-2">
                    <select
                      value={filterChannel}
                      onChange={(e) =>
                        setFilterChannel(e.target.value as ChannelName | "")
                      }
                      className="rounded-lg border border-border bg-background px-2 py-1 text-xs outline-none focus:border-primary"
                    >
                      <option value="">{t.pairing.allChannels}</option>
                      {ALL_CHANNELS.map((ch) => (
                        <option key={ch} value={ch}>
                          {CHANNEL_NAMES[ch]}
                        </option>
                      ))}
                    </select>
                    <select
                      value={filterStatus}
                      onChange={(e) =>
                        setFilterStatus(e.target.value as PairingStatus | "")
                      }
                      className="rounded-lg border border-border bg-background px-2 py-1 text-xs outline-none focus:border-primary"
                    >
                      <option value="">{t.pairing.allStatuses}</option>
                      <option value="pending">{t.pairing.statusPending}</option>
                      <option value="approved">
                        {t.pairing.statusApproved}
                      </option>
                      <option value="rejected">
                        {t.pairing.statusRejected}
                      </option>
                    </select>
                    {hasFilters && (
                      <button
                        onClick={() => {
                          setFilterChannel("");
                          setFilterStatus("");
                        }}
                        className="text-primary text-xs hover:underline"
                      >
                        {t.pairing.clearFilters}
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Pending section */}
              <div className="workspace-panel rounded-[1.75rem] px-5 py-5 md:px-6">
                <div className="mb-1 text-sm font-semibold">
                  {t.pairing.pendingSection}
                </div>
                <div className="text-muted-foreground mb-4 text-xs">
                  {t.pairing.pendingNote}
                </div>

                {isLoading && (
                  <div className="text-muted-foreground py-6 text-center text-sm">
                    {t.common.loading}
                  </div>
                )}

                {!isLoading && pendingRequests.length === 0 && (
                  <div className="flex flex-col items-center py-10">
                    <div className="text-muted-foreground/40 mb-2 text-4xl">
                      📭
                    </div>
                    <div className="text-sm font-medium">
                      {t.pairing.noPendingRequests}
                    </div>
                    <div className="text-muted-foreground mt-1 text-xs">
                      {t.pairing.noPendingDesc}
                    </div>
                  </div>
                )}

                {!isLoading && pendingRequests.length > 0 && (
                  <div className="flex flex-col gap-2">
                    {pendingRequests.map((req) => (
                      <PairingRequestRow
                        key={req.id}
                        req={req}
                        loading={actionLoading === req.id}
                        onApprove={() => approveMutation.mutate(req.id)}
                        onReject={() => rejectMutation.mutate(req.id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Toast */}
        {toast && (
          <div
            className={cn(
              "fixed bottom-6 left-1/2 -translate-x-1/2 rounded-lg px-4 py-2.5 text-sm font-medium shadow-lg",
              toast.ok
                ? "bg-green-600 text-white"
                : "bg-destructive text-destructive-foreground",
            )}
          >
            {toast.text}
          </div>
        )}
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function FilterTag({
  label,
  onRemove,
}: {
  label: string;
  onRemove: () => void;
}) {
  return (
    <span className="bg-primary/10 text-primary flex items-center gap-1 rounded-lg px-2.5 py-0.5 text-xs font-medium">
      {label}
      <button onClick={onRemove} className="hover:text-primary/70">
        <XIcon className="size-3" />
      </button>
    </span>
  );
}
