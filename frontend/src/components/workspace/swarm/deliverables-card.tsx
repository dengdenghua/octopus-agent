import { CopyIcon, DownloadIcon, FolderIcon } from "lucide-react";
import { toast } from "sonner";

import { copyTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import type { DeliverableFile, SwarmAgent } from "./types";

interface Props {
  files: DeliverableFile[];
  agents: SwarmAgent[];
  onPreviewAll?: () => void;
  className?: string;
}

export function DeliverablesCard({
  files,
  agents,
  onPreviewAll,
  className,
}: Props) {
  const { t } = useI18n();
  const byId = new Map(agents.map((a) => [a.id, a]));
  return (
    <div
      className={cn(
        "w-full space-y-3 rounded-lg border border-border bg-card p-4",
        className,
      )}
    >
      <div className="flex items-center gap-2 text-sm font-medium">
        <span>📁</span>
        <span>{t.deliverablesCard.detailedReports}</span>
      </div>
      <p className="text-muted-foreground text-xs">
        {t.deliverablesCard.expertsSaved(agents.length)}
      </p>

      <div className="overflow-hidden rounded-lg border border-border/60">
        <table className="w-full text-xs">
          <thead className="bg-muted/40 text-muted-foreground">
            <tr>
              <th className="w-28 px-3 py-2 text-left font-medium">
                {t.deliverablesCard.colReport}
              </th>
              <th className="px-3 py-2 text-left font-medium">
                {t.deliverablesCard.colPath}
              </th>
              <th className="w-20 px-3 py-2 text-right font-medium">
                {t.deliverablesCard.colActions}
              </th>
            </tr>
          </thead>
          <tbody>
            {files.map((f) => {
              const owners = f.ownerAgentIds
                .map((id) => byId.get(id))
                .filter((a): a is SwarmAgent => !!a);
              return (
                <tr
                  key={f.path}
                  className="border-t border-border/40 hover:bg-muted/30"
                >
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-1.5">
                      <OwnerStack owners={owners} />
                      <span>{f.name}</span>
                    </div>
                  </td>
                  <td className="px-3 py-2 font-mono text-[11px] text-muted-foreground">
                    {f.path}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        title={t.deliverablesCard.copyPath}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                        onClick={() =>
                          void copyTextToClipboard(f.path).catch(() =>
                            toast.error(t.clipboard.failedToCopyToClipboard),
                          )
                        }
                      >
                        <CopyIcon className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        title={t.deliverablesCard.download}
                        className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                      >
                        <DownloadIcon className="size-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <button
        type="button"
        onClick={onPreviewAll}
        className="flex w-full items-center gap-3 rounded-lg border border-dashed border-border px-3 py-3 text-left transition-colors hover:border-primary/40 hover:bg-primary/5"
      >
        <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted text-lg">
          <FolderIcon className="size-5 text-muted-foreground" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">
            {t.deliverablesCard.allFiles}
          </div>
          <div className="text-muted-foreground text-xs">
            {t.deliverablesCard.previewOrDownload}
          </div>
        </div>
      </button>
    </div>
  );
}

function OwnerStack({ owners }: { owners: SwarmAgent[] }) {
  if (owners.length === 0) return null;
  return (
    <div className="flex -space-x-1">
      {owners.slice(0, 3).map((a) => (
        <span
          key={a.id}
          title={a.name}
          className="flex size-5 items-center justify-center rounded-lg border border-background text-[10px]"
          style={{ background: `hsl(${a.hue} 70% 92%)` }}
        >
          {a.avatarEmoji}
        </span>
      ))}
    </div>
  );
}
