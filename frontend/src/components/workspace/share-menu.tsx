import { useState } from "react";
import { ClockIcon, CopyIcon, ImageIcon, Loader2Icon, Share2Icon } from "lucide-react";
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
}

/**
 * Share affordance: turns the current task/result into a branded PNG the user
 * can download or copy. Replayable HTML export lives in the workbench replay
 * bar (it needs the run's WorkBlocks, which this header menu doesn't hold), so
 * the menu just points there — the self-contained file keeps redaction at
 * export time, which is the privacy-safe form of an outward share.
 */
export function ShareMenu({
  title,
  prompt,
  summary,
  footer,
  className,
  iconOnly = false,
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
            "flex h-7 items-center gap-1.5 rounded-full bg-muted/45 px-2.5 text-[11px] font-medium text-foreground transition-colors",
            "hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
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
        <DropdownMenuItem disabled={busy !== null} onSelect={() => void handleSave()}>
          <ImageIcon className="size-4" />
          {t.share.saveImage}
        </DropdownMenuItem>
        {canCopyImageToClipboard() && (
          <DropdownMenuItem disabled={busy !== null} onSelect={() => void handleCopy()}>
            <CopyIcon className="size-4" />
            {t.share.copyImage}
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled className="flex-col items-start gap-0.5">
          <span className="flex items-center gap-2">
            <ClockIcon className="size-4" />
            {t.share.replayHint}
          </span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
