import { FileIcon, PaperclipIcon, Trash2Icon } from "lucide-react";

import type { Translations } from "@/core/i18n/locales";
import type {
  PendingContextFile,
} from "./helpers";
import { imageFileKey } from "./helpers";

interface FileAttachmentProps {
  pendingFiles: PendingContextFile[];
  pendingImages: File[];
  pendingImagePreviews: Record<string, string>;
  pendingImageSources: Record<string, string>;
  onRemoveFile: (id: string) => void;
  onRemoveImage: (index: number) => void;
  t: Translations;
}

export function FileAttachment({
  pendingFiles,
  pendingImages,
  pendingImagePreviews,
  pendingImageSources,
  onRemoveFile,
  onRemoveImage,
  t,
}: FileAttachmentProps) {
  if (pendingFiles.length === 0 && pendingImages.length === 0) {
    return null;
  }
  return (
    <div className="flex gap-2 overflow-x-auto px-3 pb-2 pt-1">
      {pendingFiles.map((file) => (
        <div
          key={file.id}
          className="group flex h-16 min-w-[150px] max-w-[240px] items-center gap-2 rounded-lg border border-border-default bg-muted/20 px-2.5"
          title={file.workDir ? `${file.path}\n${file.workDir}` : file.path}
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-background text-muted-foreground">
            {file.file ? (
              <PaperclipIcon className="size-4" />
            ) : (
              <FileIcon className="size-4" />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-foreground">
              {file.name}
            </span>
            <span className="block truncate text-xs text-muted-foreground">
              {file.sourceLabel || (file.file ? "Upload" : file.path)}
            </span>
          </span>
          <button
            type="button"
            onClick={() => onRemoveFile(file.id)}
            className="flex size-6 shrink-0 items-center justify-center rounded-lg text-muted-foreground opacity-60 transition-colors hover:bg-muted/70 hover:text-foreground hover:opacity-100"
            title={t.chatInputBox.removeImage}
            aria-label={`${t.chatInputBox.removeImage}: ${file.name}`}
          >
            <Trash2Icon className="size-3.5" />
          </button>
        </div>
      ))}
      {pendingImages.map((file, index) => {
        const key = imageFileKey(file);
        const url = pendingImagePreviews[key];
        const sourceLabel = pendingImageSources[key];
        return (
          <div
            key={key}
            className="group relative h-16 w-16 shrink-0 overflow-hidden rounded border border-border-default"
          >
            {url && (
              <img
                src={url}
                alt={file.name}
                className="h-full w-full object-cover"
              />
            )}
            {sourceLabel ? (
              <div className="absolute bottom-0 left-0 right-0 truncate bg-black/45 px-1 py-0.5 text-xs font-medium text-white backdrop-blur-sm">
                {sourceLabel}
              </div>
            ) : null}
            <button
              type="button"
              onClick={() => onRemoveImage(index)}
              className="absolute right-0.5 top-0.5 flex size-5 items-center justify-center rounded-full bg-background/80 text-muted-foreground opacity-0 backdrop-blur-sm transition-opacity hover:text-foreground group-hover:opacity-100"
              title={t.chatInputBox.removeImage}
            >
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}
