import { useEffect } from "react";
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

  useEffect(() => {
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
        dismissible: true,
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
  }, [approvals, resolveApproval, t]);

  return null;
}
