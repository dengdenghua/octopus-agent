import { DownloadIcon, LoaderIcon, PackageIcon } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import { artifactDisplayPath, urlOfArtifact } from "@/core/artifacts/utils";
import { useI18n } from "@/core/i18n/hooks";
import {
  getFileExtensionDisplayName,
  getFileIcon,
  getFileName,
} from "@/core/utils/files";
import { cn } from "@/lib/utils";

import { useArtifacts } from "./context";
import { useInstallSkill } from "./use-install-skill";

export function ArtifactFileList({
  className,
  files,
  threadId,
}: {
  className?: string;
  files: string[];
  threadId: string;
}) {
  const { t } = useI18n();
  const { select: selectArtifact, setOpen } = useArtifacts();
  const { installingFile, install } = useInstallSkill(threadId);

  const handleClick = useCallback(
    (filepath: string) => {
      selectArtifact(filepath);
      setOpen(true);
    },
    [selectArtifact, setOpen],
  );

  const handleInstallSkill = useCallback(
    (e: React.MouseEvent, filepath: string) => {
      e.stopPropagation();
      e.preventDefault();
      void install(filepath);
    },
    [install],
  );

  return (
    <div
      className={cn(
        "flex min-h-0 flex-col overflow-hidden rounded-lg border border-border-default bg-background/80",
        className,
      )}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        {files.map((file, index) => (
        <button
          key={file}
          type="button"
          className={cn(
            "flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/50",
            index > 0 && "border-t border-border-subtle",
          )}
          onClick={() => handleClick(file)}
        >
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted/60">
            {getFileIcon(artifactDisplayPath(file), "size-4")}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">
              {getFileName(artifactDisplayPath(file))}
            </div>
            <div className="truncate text-xs text-muted-foreground">
              {getFileExtensionDisplayName(artifactDisplayPath(file))}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {file.endsWith(".skill") && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 gap-1 px-2 text-xs"
                disabled={installingFile === file}
                onClick={(e) => handleInstallSkill(e, file)}
              >
                {installingFile === file ? (
                  <LoaderIcon className="size-3.5 animate-spin" />
                ) : (
                  <PackageIcon className="size-3.5" />
                )}
                {t.common.install}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              className="size-7"
              asChild
              aria-label={t.common.download}
            >
              <a
                href={urlOfArtifact({
                  filepath: file,
                  threadId: threadId,
                  download: true,
                })}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
              >
                <DownloadIcon className="size-3.5" />
              </a>
            </Button>
          </div>
        </button>
      ))}
      </div>
    </div>
  );
}
