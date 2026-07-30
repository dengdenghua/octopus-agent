import {
  FileIcon,
  FileTextIcon,
  FileCodeIcon,
  FileJsonIcon,
  FileArchiveIcon,
  XIcon,
} from "lucide-react";

import type { Translations } from "@/core/i18n/locales";
import type { PendingContextFile } from "./helpers";
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

function fileExt(name: string): string {
  const idx = name.lastIndexOf(".");
  return idx > 0 ? name.slice(idx + 1).toLowerCase() : "";
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024)
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function cleanFileName(name: string): string {
  return name
    .replace(
      /^[\s【】\[\]「」『』《》（）()]+/,
      "",
    )
    .replace(/[-_]?\s*(?:副本|copy|复件|\(\d+\))$/i, "")
    .trim();
}

type FileTypeInfo = {
  icon: React.ReactNode;
  bgClass: string;
  textClass: string;
};

function fileTypeInfo(ext: string): FileTypeInfo {
  const pdfLike = new Set(["pdf"]);
  const docLike = new Set(["doc", "docx", "txt", "md", "rtf", "odt"]);
  const sheetLike = new Set(["xls", "xlsx", "csv", "tsv", "ods"]);
  const codeLike = new Set([
    "js",
    "ts",
    "tsx",
    "jsx",
    "py",
    "go",
    "rs",
    "java",
    "c",
    "cpp",
    "h",
    "hpp",
    "cs",
    "rb",
    "php",
    "swift",
    "kt",
    "scala",
    "r",
    "sh",
    "bash",
    "zsh",
    "ps1",
    "sql",
    "dart",
    "lua",
    "pl",
    "erl",
    "ex",
    "elm",
    "fs",
    "fsx",
    "ml",
    "mli",
    "hs",
    "lhs",
    "clj",
    "cljs",
    "coffee",
    "scala",
    "groovy",
    "vhdl",
    "verilog",
    "tcl",
    "awk",
    "sed",
    "make",
    "cmake",
    "dockerfile",
    "jenkinsfile",
    "vue",
    "svelte",
    "astro",
  ]);
  const configLike = new Set([
    "json",
    "xml",
    "yaml",
    "yml",
    "toml",
    "ini",
    "conf",
    "cfg",
    "properties",
    "env",
    "lock",
  ]);
  const archiveLike = new Set([
    "zip",
    "rar",
    "7z",
    "tar",
    "gz",
    "bz2",
    "xz",
    "lz",
    "lzma",
    "z",
    "tgz",
    "tbz",
    "txz",
    "jar",
    "war",
    "ear",
  ]);
  const slideLike = new Set(["ppt", "pptx", "key", "odp"]);

  if (pdfLike.has(ext))
    return {
      icon: <FileTextIcon className="size-4" />,
      bgClass: "bg-red-50",
      textClass: "text-red-400",
    };
  if (docLike.has(ext))
    return {
      icon: <FileTextIcon className="size-4" />,
      bgClass: "bg-blue-50",
      textClass: "text-blue-400",
    };
  if (sheetLike.has(ext))
    return {
      icon: <FileTextIcon className="size-4" />,
      bgClass: "bg-emerald-50",
      textClass: "text-emerald-400",
    };
  if (slideLike.has(ext))
    return {
      icon: <FileTextIcon className="size-4" />,
      bgClass: "bg-orange-50",
      textClass: "text-orange-400",
    };
  if (codeLike.has(ext))
    return {
      icon: <FileCodeIcon className="size-4" />,
      bgClass: "bg-indigo-50",
      textClass: "text-indigo-400",
    };
  if (configLike.has(ext))
    return {
      icon: <FileJsonIcon className="size-4" />,
      bgClass: "bg-violet-50",
      textClass: "text-violet-400",
    };
  if (archiveLike.has(ext))
    return {
      icon: <FileArchiveIcon className="size-4" />,
      bgClass: "bg-gray-50",
      textClass: "text-gray-400",
    };
  return {
    icon: <FileIcon className="size-4" />,
    bgClass: "bg-gray-50",
    textClass: "text-gray-400",
  };
}

function FileTypeBadge({ ext, size }: { ext: string; size?: number }) {
  const { icon, bgClass, textClass } = fileTypeInfo(ext);
  return (
    <span
      className={`flex size-8 shrink-0 items-center justify-center rounded-md ${bgClass} ${textClass}`}
      title={ext.toUpperCase()}
    >
      {icon}
    </span>
  );
}

function buildFileMeta(file: PendingContextFile): string {
  const parts: string[] = [];
  const ext = fileExt(file.name);
  if (ext) parts.push(ext.toUpperCase());
  if (file.file && typeof file.file.size === "number") {
    parts.push(formatFileSize(file.file.size));
  }
  if (parts.length === 0 && file.sourceLabel) {
    parts.push(file.sourceLabel);
  }
  if (parts.length === 0 && file.path) {
    parts.push(file.path);
  }
  return parts.join(" · ");
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
      {pendingFiles.map((file) => {
        const ext = fileExt(file.name);
        const displayName = cleanFileName(file.name);
        const meta = buildFileMeta(file);
        return (
          <div
            key={file.id}
            className="group flex h-[52px] min-w-[180px] max-w-[260px] items-center gap-2.5 rounded-md border border-border-default bg-background px-2.5 py-1.5 shadow-sm"
            title={file.workDir ? `${file.path}\n${file.workDir}` : file.path}
          >
            <FileTypeBadge ext={ext} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-medium leading-tight text-foreground">
                {displayName}
              </span>
              <span className="block truncate text-[11px] leading-tight text-muted-foreground">
                {meta}
              </span>
            </span>
            <button
              type="button"
              onClick={() => onRemoveFile(file.id)}
              className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
              title={t.chatInputBox.removeImage}
              aria-label={`${t.chatInputBox.removeImage}: ${displayName}`}
            >
              <XIcon className="size-3.5" />
            </button>
          </div>
        );
      })}
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
