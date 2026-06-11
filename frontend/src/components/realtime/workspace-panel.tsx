import { FolderOpenIcon } from "lucide-react";
import { useCallback, useEffect } from "react";

import { FileTree } from "@/components/workspace/file-tree";
import { WorkDirSelector } from "@/components/workspace/workdir-selector";
import { swallow } from "@/core/utils/log";
import { useI18n } from "@/core/i18n/hooks";
import { isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";

interface WorkspacePanelProps {
  workDir: string;
  onWorkDirChange: (dir: string) => void;
  threadId: string;
  onOpenFile?: (path: string) => void;
  className?: string;
}

// Try the native folder picker first (Electron) and fall back to a
// browser `prompt` so the CTA still works in pure web mode. Kept local to
// this file to avoid modifying the shared `WorkDirSelector`.
async function pickWorkDir(currentDir: string, promptLabel: string): Promise<string | null> {
  const api = typeof window !== "undefined" ? window.octopus : undefined;
  if (api?.isElectron) {
    try {
      const result = await api.dialog.open({
        properties: ["openDirectory"],
        defaultPath: currentDir || undefined,
      });
      if (result.canceled || result.filePaths.length === 0) return null;
      return result.filePaths[0] || null;
    } catch (error) {
      console.error("Electron folder picker failed:", error);
      return null;
    }
  }
  if (typeof window === "undefined") return null;
  const typed = window.prompt(promptLabel, currentDir || "");
  if (!typed) return null;
  const trimmed = typed.trim();
  if (!trimmed || !isAbsolutePath(trimmed)) return null;
  return trimmed;
}

/**
 * Left-rail workspace panel for the realtime UI: stacks the
 * `WorkDirSelector` on top of the `FileTree` and handles the
 * no-folder-yet empty state. The parent owns `workDir`; this component
 * mirrors the per-thread/last-used persistence pattern under the
 * `realtime:*` keyspace so a returning user's last folder is not lost
 * between mounts.
 */
export function WorkspacePanel({
  workDir,
  onWorkDirChange,
  threadId,
  onOpenFile,
  className,
}: WorkspacePanelProps) {
  const { t } = useI18n();

  // Persist on every change Â· two keys so a new thread inherits the
  // last-used folder while existing threads keep their own. Parent owns
  // state + lazy-init, we just mirror writes.
  useEffect(() => {
    if (typeof window === "undefined" || !workDir) return;
    try {
      if (threadId) {
        window.localStorage.setItem(`realtime:workdir:${threadId}`, workDir);
      }
      window.localStorage.setItem("realtime:workdir:lastUsed", workDir);
    } catch (e) { swallow(e, "storage"); }
  }, [workDir, threadId]);

  const handlePick = useCallback(async () => {
    const next = await pickWorkDir(workDir, t.codeMode.selectWorkspace);
    if (next && next !== workDir) {
      onWorkDirChange(next);
    }
  }, [onWorkDirChange, t.codeMode.selectWorkspace, workDir]);

  const isEmpty = !workDir;

  return (
    <div
      className={cn(
        "flex h-full flex-col border-r border-border/60 bg-background/50 p-2",
        className,
      )}
    >
      <div className="shrink-0">
        <WorkDirSelector workDir={workDir} onWorkDirChange={onWorkDirChange} />
      </div>

      {isEmpty ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
          <FolderOpenIcon className="size-8 text-muted-foreground/50" />
          <p className="text-xs text-muted-foreground">
            {t.codeMode.selectWorkspaceFolderFirst}
          </p>
          <button
            type="button"
            onClick={handlePick}
            className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/30 px-3 py-1.5 text-[11px] font-medium text-foreground/80 transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <FolderOpenIcon className="size-3.5" />
            {t.codeMode.chooseWorkspaceFolder}
          </button>
        </div>
      ) : (
        <FileTree
          workDir={workDir}
          threadId={threadId}
          className="mt-2 flex-1 overflow-auto"
          onFileClick={onOpenFile}
        />
      )}
    </div>
  );
}

