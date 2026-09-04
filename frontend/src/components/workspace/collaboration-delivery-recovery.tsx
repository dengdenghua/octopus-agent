import {
  AlertTriangleIcon,
  ChevronDownIcon,
  RotateCcwIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { authHeaders, jsonAuthHeaders } from "@/core/auth/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type DeliveryStatus = "pending" | "delivering" | "retry_wait" | "failed";

interface CollaborationDelivery {
  delivery_id: string;
  status: DeliveryStatus;
  attempt: number;
  max_attempts: number;
  last_error?: string | null;
  next_attempt_at?: string | null;
  payload?: {
    item?: {
      agent_display_name?: string | null;
      text?: string | null;
    };
  };
}

interface DeliveryListResponse {
  deliveries?: CollaborationDelivery[];
}

const RECOVERABLE_STATUSES = "pending,delivering,retry_wait,failed";

function deliveryAgent(delivery: CollaborationDelivery, fallback: string) {
  const name = delivery.payload?.item?.agent_display_name?.trim();
  return name || fallback;
}

function deliveryPreview(delivery: CollaborationDelivery): string {
  return (
    delivery.payload?.item?.text?.trim() || delivery.last_error?.trim() || ""
  );
}

export function CollaborationDeliveryRecovery({
  threadId,
  className,
}: {
  threadId: string;
  className?: string;
}) {
  const { t } = useI18n();
  const [deliveries, setDeliveries] = useState<CollaborationDelivery[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        status: RECOVERABLE_STATUSES,
        limit: "50",
      });
      const response = await fetch(
        `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/deliveries?${params}`,
        { headers: authHeaders() },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as DeliveryListResponse;
      const next = Array.isArray(payload.deliveries) ? payload.deliveries : [];
      setDeliveries(next);
      setLoadFailed(false);
      if (next.some((delivery) => delivery.status === "failed")) {
        setExpanded(true);
      }
    } catch {
      // A recovery monitor must never disrupt the primary execution surface.
      // Keep a small retry affordance only when it was already visible.
      setLoadFailed(true);
    }
  }, [threadId]);

  useEffect(() => {
    let active = true;
    const refresh = () => {
      if (!active || document.visibilityState === "hidden") return;
      void load();
    };
    refresh();
    const interval = window.setInterval(refresh, 5_000);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [load]);

  const sorted = useMemo(
    () =>
      [...deliveries].sort((a, b) => {
        const rank = (status: DeliveryStatus) =>
          status === "failed" ? 0 : status === "retry_wait" ? 1 : 2;
        return rank(a.status) - rank(b.status);
      }),
    [deliveries],
  );

  const mutate = useCallback(
    async (deliveryId: string, action: "retry" | "dismiss") => {
      setBusyId(deliveryId);
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/collab/${encodeURIComponent(threadId)}/deliveries/${encodeURIComponent(deliveryId)}/${action}`,
          { method: "POST", headers: jsonAuthHeaders() },
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await load();
      } finally {
        setBusyId(null);
      }
    },
    [load, threadId],
  );

  if (sorted.length === 0 && !loadFailed) return null;

  return (
    <div
      className={cn(
        "shrink-0 border-b border-warning/25 bg-warning/[0.055]",
        className,
      )}
      data-testid="collaboration-delivery-recovery"
    >
      <div className="flex min-h-9 items-center gap-2 px-3">
        <AlertTriangleIcon className="size-3.5 shrink-0 text-warning" />
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-xs font-medium text-foreground"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          <span className="truncate">
            {loadFailed && sorted.length === 0
              ? t.coworkCollab.deliveryMonitorUnavailable
              : t.coworkCollab.deliveryPending(sorted.length)}
          </span>
          <ChevronDownIcon
            className={cn(
              "size-3.5 shrink-0 text-muted-foreground transition-transform",
              expanded && "rotate-180",
            )}
          />
        </button>
        {loadFailed ? (
          <button
            type="button"
            className="text-xs text-muted-foreground hover:text-foreground"
            onClick={() => void load()}
          >
            {t.coworkCollab.deliveryRetry}
          </button>
        ) : null}
      </div>

      {expanded && sorted.length > 0 ? (
        <ul className="border-t border-warning/15 px-3 py-1">
          {sorted.map((delivery) => {
            const isBusy = busyId === delivery.delivery_id;
            const preview = deliveryPreview(delivery);
            return (
              <li
                key={delivery.delivery_id}
                className="flex min-w-0 items-center gap-2 border-b border-border-subtle py-2 last:border-b-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-baseline gap-2">
                    <span className="truncate text-xs font-medium text-foreground">
                      {deliveryAgent(
                        delivery,
                        t.coworkCollab.deliveryUnknownMember,
                      )}
                    </span>
                    <span className="shrink-0 text-mini text-muted-foreground">
                      {delivery.status === "failed"
                        ? t.coworkCollab.deliveryFailed
                        : t.coworkCollab.deliveryWaiting}
                    </span>
                  </div>
                  {preview ? (
                    <p className="mt-0.5 truncate text-mini text-muted-foreground">
                      {preview}
                    </p>
                  ) : null}
                </div>
                <button
                  type="button"
                  disabled={isBusy}
                  className="inline-flex h-7 shrink-0 items-center gap-1 px-1.5 text-xs text-primary hover:text-primary/75 disabled:opacity-50"
                  onClick={() => void mutate(delivery.delivery_id, "retry")}
                >
                  <RotateCcwIcon
                    className={cn("size-3", isBusy && "animate-spin")}
                  />
                  {t.coworkCollab.deliveryRetry}
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  aria-label={t.coworkCollab.deliveryDismiss}
                  title={t.coworkCollab.deliveryDismiss}
                  className="inline-flex size-7 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground disabled:opacity-50"
                  onClick={() => void mutate(delivery.delivery_id, "dismiss")}
                >
                  <XIcon className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
