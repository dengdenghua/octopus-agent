import { useState, type ReactNode } from "react";
import {
  CircleDotIcon,
  CopyIcon,
  DownloadIcon,
  ImageIcon,
  Loader2Icon,
  MoreHorizontalIcon,
} from "lucide-react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildTaskShareImage,
  canCopyImageToClipboard,
  copyPngToClipboard,
  downloadPng,
} from "@/core/sharing/share-image";
import { cn } from "@/lib/utils";

export interface RealtimeChatHeaderShareOptions {
  title: string;
  prompt?: string;
  summary?: string;
  footer?: string;
  onExportReplay?: () => void;
}

/**
 * Keeps the two membership domains honest while presenting one visual unit.
 * The first segment manages the AI execution roster; the second opens the
 * existing human invite flow. Their counts and permissions remain independent.
 */
export function RealtimeChatHeaderMemberSurface({
  aiMembers,
  humanInvite,
  className,
}: {
  aiMembers?: ReactNode;
  humanInvite?: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();

  if (!aiMembers && !humanInvite) return null;

  return (
    <div
      role="group"
      aria-label={t.chatInputBox.collaborators}
      data-slot="realtime-header-members"
      className={cn(
        "inline-flex h-[42px] max-w-full shrink-0 items-stretch overflow-hidden rounded-lg border border-border-default bg-background/45 shadow-none sm:h-8",
        "[&_[data-slot=task-collaborator-trigger]]:h-full [&_[data-slot=task-collaborator-trigger]]:rounded-none [&_[data-slot=task-collaborator-trigger]]:border-0",
        "[&_[data-slot=button]]:h-full [&_[data-slot=button]]:rounded-none [&_[data-slot=button]]:border-0",
        className,
      )}
    >
      {aiMembers ? <div className="min-w-0">{aiMembers}</div> : null}
      {humanInvite ? (
        <div className="shrink-0 border-l border-border-subtle">
          {humanInvite}
        </div>
      ) : null}
    </div>
  );
}

/** Keeps the three persistent header actions in one non-wrapping cluster. */
export function RealtimeChatHeaderActions({
  recording,
  workbench,
  overflow,
  className,
}: {
  recording?: ReactNode;
  workbench?: ReactNode;
  overflow: ReactNode;
  className?: string;
}) {
  return (
    <div
      data-slot="realtime-header-actions"
      className={cn("flex shrink-0 items-center gap-1", className)}
    >
      {recording}
      {workbench}
      {overflow}
    </div>
  );
}

/**
 * Compact home for low-frequency chat utilities. Idle recording lives here;
 * an active recording is promoted by the caller into the persistent actions.
 */
export function RealtimeChatHeaderOverflowMenu({
  onOpenRecorder,
  recorderDisabled = false,
  share,
  className,
}: {
  onOpenRecorder?: () => void;
  recorderDisabled?: boolean;
  share?: RealtimeChatHeaderShareOptions;
  className?: string;
}) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<"save" | "copy" | null>(null);

  const handleSave = async () => {
    if (!share) return;
    setBusy("save");
    try {
      const blob = await buildTaskShareImage(share);
      downloadPng(blob, share.title);
      toast.success(t.share.imageSaved);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.share.imageFailed);
    } finally {
      setBusy(null);
    }
  };

  const handleCopy = async () => {
    if (!share) return;
    setBusy("copy");
    try {
      const blob = await buildTaskShareImage(share);
      await copyPngToClipboard(blob);
      toast.success(t.share.imageCopied);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.share.imageFailed);
    } finally {
      setBusy(null);
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={t.common.more}
          title={t.common.more}
          data-slot="realtime-header-overflow-trigger"
          className={cn(
            "flex size-[42px] shrink-0 items-center justify-center rounded-lg border border-transparent bg-transparent text-muted-foreground shadow-none transition-colors duration-base hover:border-border-default hover:bg-muted/55 hover:text-foreground sm:size-8",
            "outline-none focus-visible:ring-2 focus-visible:ring-ring/35",
            className,
          )}
        >
          {busy ? (
            <Loader2Icon className="size-4 animate-spin" />
          ) : (
            <MoreHorizontalIcon className="size-4" />
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {onOpenRecorder ? (
          <DropdownMenuItem
            disabled={recorderDisabled}
            onSelect={onOpenRecorder}
          >
            <CircleDotIcon className="size-4" />
            <span className="truncate">{t.realtime.recording.idle}</span>
          </DropdownMenuItem>
        ) : null}

        {onOpenRecorder && share ? <DropdownMenuSeparator /> : null}

        {share ? (
          <>
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              {t.share.share}
            </DropdownMenuLabel>
            <DropdownMenuItem
              disabled={busy !== null}
              onSelect={() => void handleSave()}
            >
              <ImageIcon className="size-4" />
              {t.share.saveImage}
            </DropdownMenuItem>
            {canCopyImageToClipboard() ? (
              <DropdownMenuItem
                disabled={busy !== null}
                onSelect={() => void handleCopy()}
              >
                <CopyIcon className="size-4" />
                {t.share.copyImage}
              </DropdownMenuItem>
            ) : null}
            {share.onExportReplay ? (
              <DropdownMenuItem onSelect={() => share.onExportReplay?.()}>
                <DownloadIcon className="size-4" />
                {t.share.exportReplay}
              </DropdownMenuItem>
            ) : null}
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
