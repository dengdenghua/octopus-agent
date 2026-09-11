import { useQuery } from "@tanstack/react-query";
import { ClipboardCheckIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { getAPIClient } from "@/core/api";

/** A durable way back to an expired proposal; opening it is not approval. */
export function ProjectProposalNotice({ threadId, busy, onReview }: {
  threadId: string;
  busy: boolean;
  onReview: (command: string) => void;
}) {
  const [submittedId, setSubmittedId] = useState("");
  useEffect(() => {
    if (!submittedId) return;
    // Suppress the double-click gap before the live turn becomes busy, but
    // allow another attempt if transport fails before a turn can start.
    const timer = setTimeout(() => setSubmittedId(""), 2000);
    return () => clearTimeout(timer);
  }, [submittedId]);
  const { data } = useQuery({
    queryKey: ["thread", "project-proposal", threadId],
    queryFn: () => getAPIClient().threads.get(threadId),
    enabled: Boolean(threadId) && threadId !== "new" && !busy,
    staleTime: 0,
    retry: false,
  });
  const raw = data?.metadata?.project_initiation;
  if (busy || !raw || typeof raw !== "object") return null;
  const draft = raw as { id?: unknown; status?: unknown; proposal?: { name?: unknown } };
  if (typeof draft.id !== "string" || !/^[a-zA-Z0-9_-]+$/.test(draft.id) ||
      !["approval_expired", "needs_revision", "needs_roles"].includes(String(draft.status)) ||
      typeof draft.proposal?.name !== "string") return null;
  const id = draft.id;
  return (
    <div className="mx-auto my-3 flex max-w-3xl items-start gap-3 rounded-lg border bg-muted/30 p-3">
      <ClipboardCheckIcon className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-medium">待审批方案 · {draft.proposal.name}</p>
        <p className="mt-1 text-xs text-muted-foreground">方案已保留。可重新审阅；批准前不会添加成员或启动项目。修改需求可继续发消息。</p>
      </div>
      <Button size="sm" variant="outline" disabled={submittedId === id} onClick={() => {
        if (submittedId === id) return;
        setSubmittedId(id);
        onReview(`/project review ${id}`);
      }}>重新提交审批</Button>
    </div>
  );
}
