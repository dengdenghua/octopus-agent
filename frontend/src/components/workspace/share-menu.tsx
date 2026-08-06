import { useState } from "react";
import {
  CopyIcon,
  DownloadIcon,
  ImageIcon,
  Loader2Icon,
  Share2Icon,
} from "lucide-react";
import { toast } from "sonner";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  buildTaskShareImage,
  canCopyImageToClipboard,
  copyPngToClipboard,
  downloadPng,
} from "@/core/sharing/share-image";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

interface ShareMenuProps {
  /** Headline — usually the thread title / task. */
  title: string;
  /** "做同款" prompt so a recipient can recreate the task. */
  prompt?: string;
  /** One-line result summary. */
  summary?: string;
  footer?: string;
  className?: string;
  /** Render only the icon (compact header placement). */
  iconOnly?: boolean;
  /**
   * Export the run as a self-contained, offline-playable replay ``.html``.
   * Omitted when the thread has no replayable steps — the item is then hidden.
   * The caller assembles the replay data (it owns the run's events); this menu
   * is just the unified entry point.
   */
  onExportReplay?: () => void;
}

/**
 * Unified share affordance in the chat header: turns the current task/result
 * into a branded PNG (download or copy), and — when the run has replayable
 * steps — exports a self-contained replay ``.html``. Both are outward shares
 * the user can inspect before sending; the HTML keeps redaction at export time.
 */
export function ShareMenu({
  title,
  prompt,
  summary,
  footer,
  className,
  iconOnly = false,
  onExportReplay,
}: ShareMenuProps) {
  const { t } = useI18n();
  const [busy, setBusy] = useState<"save" | "copy" | null>(null);

  const opts = { title, prompt, summary, footer };

  const handleSave = async () => {
    setBusy("save");
    try {
      const blob = await buildTaskShareImage(opts);
      downloadPng(blob, title);
      toast.success(t.share.imageSaved);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.share.imageFailed);
    } finally {
      setBusy(null);
    }
  };

  const handleCopy = async () => {
    setBusy("copy");
    try {
      const blob = await buildTaskShareImage(opts);
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
          title={t.share.share}
          className={cn(
            "flex h-[42px] items-center gap-1.5 border text-xs font-medium shadow-none transition-all duration-base sm:h-7",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
            iconOnly
              ? "w-[42px] justify-center rounded-lg border-transparent bg-transparent px-0 text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground sm:w-8"
              : "rounded-lg border-transparent bg-transparent px-2.5 text-muted-foreground hover:bg-muted/55 hover:text-foreground",
            className,
          )}
        >
          {busy ? (
            <Loader2Icon className="size-3.5 animate-spin text-muted-foreground" />
          ) : (
            <Share2Icon className="size-3.5 text-muted-foreground" />
          )}
          {!iconOnly && <span>{t.share.share}</span>}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-52">
        <DropdownMenuItem
          disabled={busy !== null}
          onSelect={() => void handleSave()}
        >
          <ImageIcon className="size-4" />
          {t.share.saveImage}
        </DropdownMenuItem>
        {canCopyImageToClipboard() && (
          <DropdownMenuItem
            disabled={busy !== null}
            onSelect={() => void handleCopy()}
          >
            <CopyIcon className="size-4" />
            {t.share.copyImage}
          </DropdownMenuItem>
        )}
        {onExportReplay && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onExportReplay()}>
              <DownloadIcon className="size-4" />
              {t.share.exportReplay}
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
