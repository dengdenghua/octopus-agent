import { FilesIcon, XIcon } from "lucide-react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ArtifactFileDetail } from "./artifact-file-detail";
import { ArtifactFileList } from "./artifact-file-list";
import { useArtifacts } from "./context";

export function ArtifactPanel({
  className,
  showHeader = true,
  threadId,
}: {
  className?: string;
  showHeader?: boolean;
  threadId: string;
}) {
  const { t } = useI18n();
  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    selectedArtifact,
  } = useArtifacts();
  const artifactCount = artifacts?.length ?? 0;

  if (selectedArtifact) {
    return (
      <ArtifactFileDetail
        className={cn("size-full", className)}
        filepath={selectedArtifact}
        threadId={threadId}
      />
    );
  }

  return (
    <div
      aria-hidden={!artifactsOpen}
      className={cn("flex min-h-0 flex-1 flex-col overflow-hidden", className)}
    >
      {showHeader && (
        <header className="flex shrink-0 items-center gap-2 border-b border-border/40 px-3 py-2.5">
          <FilesIcon className="size-4 text-muted-foreground" />
          <h2 className="flex-1 truncate text-sm font-medium">
            {t.conversation.artifactsTitle}
          </h2>
          {artifactCount > 0 && (
            <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
              {artifactCount}
            </span>
          )}
          <Button
            size="icon-sm"
            variant="ghost"
            onClick={() => setArtifactsOpen(false)}
            aria-label={t.common.close}
            className="size-7"
          >
            <XIcon className="size-3.5" />
          </Button>
        </header>
      )}
      <main className="min-h-0 grow overflow-y-auto p-2">
        {artifactCount === 0 ? (
          <ConversationEmptyState
            icon={<FilesIcon />}
            title={t.conversation.noArtifactSelected}
            description={t.conversation.selectArtifactToView}
          />
        ) : (
          <ArtifactFileList files={artifacts ?? []} threadId={threadId} />
        )}
      </main>
    </div>
  );
}
