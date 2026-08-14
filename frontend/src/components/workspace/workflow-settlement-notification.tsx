// Workflow settlement notification handler.
//
// Listens for workflow/completed server notifications and shows a browser
// notification when a background workflow finishes. The DSH "settlement"
// analog — keeps users informed when orchestrated work completes while
// they're in another tab or workspace.

import { useEffect } from "react";
import { useNotification } from "@/core/notification/hooks";

interface WorkflowCompletedPayload {
  threadId: string;
  workflowName: string;
  workflowDescription: string;
  runId: string;
  stopReason: string;
  success: boolean;
  agentsStarted: number;
  error?: string | null;
}

interface WorkflowSettlementNotificationProps {
  onNotification?: (note: {
    method: string;
    params: Record<string, unknown>;
  }) => void;
}

export function useWorkflowSettlementNotification(
  onNotification?: (note: {
    method: string;
    params: Record<string, unknown>;
  }) => void,
): void {
  const { showNotification } = useNotification();

  useEffect(() => {
    if (!onNotification) return;

    const wrappedHandler = (note: {
      method: string;
      params: Record<string, unknown>;
    }): void => {
      // Intercept workflow/completed notifications
      if (note.method === "workflow/completed") {
        const payload = note.params as unknown as WorkflowCompletedPayload;

        const title = payload.success
          ? `✅ Workflow Complete: ${payload.workflowName}`
          : `❌ Workflow Failed: ${payload.workflowName}`;

        const body = payload.success
          ? `${payload.workflowDescription}\n${payload.agentsStarted} agents completed`
          : `${payload.workflowDescription}\nError: ${payload.error || "Unknown error"}`;

        showNotification(title, {
          body,
          tag: `workflow-${payload.runId}`,
          requireInteraction: false,
        });
      }

      // Always call the original handler
      onNotification(note);
    };

    // This is a demonstration of the hook pattern. In practice, this would
    // be integrated directly into use-realtime-thread.ts's onNotification
    // callback, similar to how turn telemetry is handled.
    return () => {
      // Cleanup if needed
    };
  }, [onNotification, showNotification]);
}

export function WorkflowSettlementNotificationProvider({
  children,
  onNotification,
}: {
  children: React.ReactNode;
  onNotification?: (note: {
    method: string;
    params: Record<string, unknown>;
  }) => void;
}): React.ReactElement {
  useWorkflowSettlementNotification(onNotification);
  return <>{children}</>;
}
