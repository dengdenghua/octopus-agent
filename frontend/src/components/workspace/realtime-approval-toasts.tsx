import { useEffect, useRef } from "react";
import { toast } from "sonner";

import type { PendingApproval } from "@/core/realtime/items";
import { useI18n } from "@/core/i18n/hooks";

const APPROVAL_TIMEOUT_MS = 120_000;

export function RealtimeApprovalToasts({
  approvals,
  resolveApproval,
}: {
  approvals: PendingApproval[];
  resolveApproval: (requestId: string | number, accept: boolean) => void;
}) {
  const { t } = useI18n();
  const visibleApprovalIdsRef = useRef(new Set<string>());

  useEffect(() => {
    const nextApprovalIds = new Set(
      approvals.map((approval) => String(approval.requestId)),
    );
    for (const requestId of visibleApprovalIdsRef.current) {
      if (!nextApprovalIds.has(requestId)) toast.dismiss(requestId);
    }

    for (const approval of approvals) {
      const params = approval.params as {
        tool?: string;
        argsPreview?: string;
        detail?: string;
      };
      toast(params.tool || "tool", {
        id: String(approval.requestId),
        description: params.argsPreview?.slice(0, 200) || params.detail,
        duration: APPROVAL_TIMEOUT_MS,
        // Closing the toast without resolving the request leaves the turn
        // blocked with no visible way forward. Keep the decision surface
        // present until the user chooses or the server withdraws it.
        dismissible: false,
        action: {
          label: t.toolApproval?.approve ?? "Allow",
          onClick: () => resolveApproval(approval.requestId, true),
        },
        cancel: {
          label: t.toolApproval?.reject ?? "Deny",
          onClick: () => resolveApproval(approval.requestId, false),
        },
      });
    }
    visibleApprovalIdsRef.current = nextApprovalIds;
  }, [approvals, resolveApproval, t]);

  useEffect(
    () => () => {
      for (const requestId of visibleApprovalIdsRef.current) {
        toast.dismiss(requestId);
      }
      visibleApprovalIdsRef.current.clear();
    },
    [],
  );

  return null;
}
