import {
  Code2Icon,
  CopyIcon,
  Diff as DiffIcon,
  DownloadIcon,
  EyeIcon,
  LoaderIcon,
  PackageIcon,
  SquareArrowOutUpRightIcon,
  XIcon,
} from "lucide-react";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import type { StreamdownProps } from "streamdown";

import {
  Artifact,
  ArtifactAction,
  ArtifactActions,
  ArtifactContent,
  ArtifactHeader,
  ArtifactTitle,
} from "@/components/ai-elements/artifact";
import { Select, SelectItem } from "@/components/ui/select";
import {
  SelectContent,
  SelectGroup,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { lazy } from "react";

const CodeEditor = lazy(
  () =>
    import("@/components/workspace/code-editor").then((m) => ({
      default: m.CodeEditor,
    })),
);
const LazyStreamdown = lazy(
  () => import("@/components/ai-elements/streamdown-host"),
);
const DiffViewer = lazy(
  () =>
    import("@/components/workspace/diff-viewer").then((m) => ({
      default: m.DiffViewer,
    })),
);
import { useArtifactContent, useArtifactDiff } from "@/core/artifacts/hooks";
import { artifactDisplayPath, urlOfArtifact } from "@/core/artifacts/utils";
import { copyTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import { installSkill } from "@/core/skills/api";
import { useStreamdownPlugins } from "@/core/streamdown";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { ArtifactLink } from "../citations/artifact-link";
import { useThread } from "../messages/context";
import { Tooltip } from "../tooltip";

import { useArtifacts } from "./context";
import { INSPECT_INJECTED_SCRIPT } from "./inspect-injected-script";
import { InspectOverlay } from "./inspect-overlay";

type ViewMode = "code" | "preview" | "diff";

export function ArtifactFileDetail({
  className,
  filepath: filepathFromProps,
  threadId,
}: {
  className?: string;
  filepath: string;
  threadId: string;
}) {
  const { t } = useI18n();
  const streamdownPlugins = useStreamdownPlugins();
  const { artifacts, setOpen, select } = useArtifacts();
  const isWriteFile = useMemo(() => {
    return filepathFromProps.startsWith("write-file:");
  }, [filepathFromProps]);
  const filepath = useMemo(() => {
    if (isWriteFile) {
      const url = new URL(filepathFromProps);
      return decodeURIComponent(url.pathname);
    }
    return artifactDisplayPath(filepathFromProps);
  }, [filepathFromProps, isWriteFile]);
  const isSkillFile = useMemo(() => {
    return filepath.endsWith(".skill");
  }, [filepath]);
  const { isCodeFile, language } = useMemo(() => {
    if (isWriteFile) {
      let language = checkCodeFile(filepath).language;
      language ??= "text";
      return { isCodeFile: true, language };
    }
    if (isSkillFile) {
      return { isCodeFile: true, language: "markdown" };
    }
    return checkCodeFile(filepath);
  }, [filepath, isWriteFile, isSkillFile]);
  const isSupportPreview = useMemo(() => {
    return language === "html" || language === "markdown";
  }, [language]);
  const { content, url } = useArtifactContent({
    threadId,
    filepath: filepathFromProps,
    enabled: isCodeFile && !isWriteFile,
  });

  const {
    originalContent,
    newContent,
    isDiffAvailable,
    isLoading: _isLoadingDiff,
  } = useArtifactDiff({
    filepath: filepathFromProps,
    threadId,
    enabled: isWriteFile && isCodeFile,
  });

  const displayContent = content ?? "";

  const [viewMode, setViewMode] = useState<ViewMode>("code");
  const [isInstalling, setIsInstalling] = useState(false);
  const { isMock } = useThread();
  useEffect(() => {
    if (isWriteFile && isDiffAvailable) {
      setViewMode("diff");
    } else if (isSupportPreview) {
      setViewMode("preview");
    } else {
      setViewMode("code");
    }
  }, [isSupportPreview, isWriteFile, isDiffAvailable]);

  const handleInstallSkill = useCallback(async () => {
    if (isInstalling) return;

    setIsInstalling(true);
    try {
      const result = await installSkill({
        thread_id: threadId,
        path: filepath,
      });
      if (result.success) {
        toast.success(result.message);
      } else {
        toast.error(result.message ?? t.toolCalls.toastSkillInstallFailed);
      }
    } catch (error) {
      console.error("Failed to install skill:", error);
      toast.error(t.toolCalls.toastSkillInstallFailed);
    } finally {
      setIsInstalling(false);
    }
  }, [threadId, filepath, isInstalling]);

  const effectiveContent = isWriteFile ? newContent : displayContent;

  return (
    <Artifact className={cn(className)}>
      <ArtifactHeader className="px-2">
        <div className="flex items-center gap-2">
          <ArtifactTitle>
            {isWriteFile ? (
              <div className="px-2">{getFileName(filepath)}</div>
            ) : (
              <Select value={filepath} onValueChange={select}>
                <SelectTrigger className="border-none bg-transparent! shadow-none select-none focus:outline-0 active:outline-0">
                  <SelectValue placeholder="Select a file" />
                </SelectTrigger>
                <SelectContent className="select-none">
                  <SelectGroup>
                    {(artifacts ?? []).map((filepath) => (
                      <SelectItem key={filepath} value={filepath}>
                        {getFileName(artifactDisplayPath(filepath))}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            )}
          </ArtifactTitle>
        </div>
        <div className="flex min-w-0 grow items-center justify-center">
          {(isSupportPreview || isDiffAvailable) && (
            <ToggleGroup
              className="mx-auto"
              type="single"
              variant="outline"
              size="sm"
              value={viewMode}
              onValueChange={(value) => {
                if (value) {
                  setViewMode(value as ViewMode);
                }
              }}
            >
              {isDiffAvailable && (
                <ToggleGroupItem value="diff">
                  <DiffIcon />
                </ToggleGroupItem>
              )}
              <ToggleGroupItem value="code">
                <Code2Icon />
              </ToggleGroupItem>
              {isSupportPreview && (
                <ToggleGroupItem value="preview">
                  <EyeIcon />
                </ToggleGroupItem>
              )}
            </ToggleGroup>
          )}
        </div>
        <div className="flex items-center gap-2">
          <ArtifactActions>
            {!isWriteFile && filepath.endsWith(".skill") && (
              <Tooltip content={t.toolCalls.skillInstallTooltip}>
                <ArtifactAction
                  icon={isInstalling ? LoaderIcon : PackageIcon}
                  label={t.common.install}
                  tooltip={t.common.install}
                  disabled={
                    isInstalling ||
                    env.STATIC_WEBSITE_ONLY
                  }
                  onClick={handleInstallSkill}
                />
              </Tooltip>
            )}
            {!isWriteFile && (
              <ArtifactAction
                icon={SquareArrowOutUpRightIcon}
                label={t.common.openInNewWindow}
                tooltip={t.common.openInNewWindow}
                onClick={() => {
                  const w = window.open(
                    urlOfArtifact({ filepath: filepathFromProps, threadId }),
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            {isCodeFile && (
              <ArtifactAction
                icon={CopyIcon}
                label={t.clipboard.copyToClipboard}
                disabled={!effectiveContent}
                onClick={async () => {
                  try {
                    await copyTextToClipboard(effectiveContent ?? "");
                    toast.success(t.clipboard.copiedToClipboard);
                  } catch {
                    toast.error(t.clipboard.failedToCopyToClipboard);
                  }
                }}
                tooltip={t.clipboard.copyToClipboard}
              />
            )}
            {!isWriteFile && (
              <ArtifactAction
                icon={DownloadIcon}
                label={t.common.download}
                tooltip={t.common.download}
                onClick={() => {
                  const w = window.open(
                    urlOfArtifact({
                      filepath: filepathFromProps,
                      threadId,
                      download: true,
                    }),
                    "_blank",
                    "noopener,noreferrer",
                  );
                  if (w) w.opener = null;
                }}
              />
            )}
            <ArtifactAction
              icon={XIcon}
              label={t.common.close}
              onClick={() => setOpen(false)}
              tooltip={t.common.close}
            />
          </ArtifactActions>
        </div>
      </ArtifactHeader>
      <ArtifactContent className="p-0">
        {isSupportPreview &&
          viewMode === "preview" &&
          (language === "markdown" || language === "html") && (
            <ArtifactFilePreview
              content={effectiveContent}
              filepath={filepath}
              isWriteFile={isWriteFile}
              language={language ?? "text"}
              streamdownPlugins={streamdownPlugins}
              url={url}
            />
          )}
        {isCodeFile && viewMode === "diff" && isDiffAvailable && (
          <Suspense
            fallback={
              <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
                Loading diff...
              </div>
            }
          >
            <DiffViewer
              className="size-full resize-none rounded-none border-none"
              oldValue={originalContent}
              newValue={newContent}
            />
          </Suspense>
        )}
        {isCodeFile && viewMode === "code" && (
          <Suspense
            fallback={
              <div className="text-muted-foreground flex h-full items-center justify-center text-sm">
                Loading editor...
              </div>
            }
          >
            <CodeEditor
              className="size-full resize-none rounded-none border-none"
              value={effectiveContent ?? ""}
              readonly={isWriteFile}
              filePath={isWriteFile ? undefined : filepath}
              threadId={threadId}
            />
          </Suspense>
        )}
        {!isCodeFile && (
          <iframe
            className="size-full"
            src={urlOfArtifact({ filepath: filepathFromProps, threadId, isMock })}
          />
        )}
      </ArtifactContent>
    </Artifact>
  );
}

export function ArtifactFilePreview({
  content,
  filepath,
  isWriteFile,
  language,
  streamdownPlugins,
  url,
}: {
  content: string;
  filepath: string;
  isWriteFile: boolean;
  language: string;
  streamdownPlugins: Pick<StreamdownProps, "remarkPlugins" | "rehypePlugins">;
  url?: string;
}) {
  if (language === "markdown") {
    return (
      <div className="size-full px-4">
        <Suspense
          fallback={
            <div className="size-full whitespace-pre-wrap break-words py-4">
              {content ?? ""}
            </div>
          }
        >
          <LazyStreamdown
            className="size-full"
            {...streamdownPlugins}
            components={{ a: ArtifactLink }}
          >
            {content ?? ""}
          </LazyStreamdown>
        </Suspense>
      </div>
    );
  }
  if (language === "html") {
    return (
      <HtmlPreview
        content={content}
        filepath={filepath}
        isWriteFile={isWriteFile}
        url={url}
      />
    );
  }
  return null;
}

function HtmlPreview({
  content,
  filepath,
  isWriteFile,
  url,
}: {
  content: string;
  filepath: string;
  isWriteFile: boolean;
  url?: string;
}) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // Inspect can only inject its DOM script via srcDoc (write-file path).
  // URL-served artifacts are cross-origin to us — no injection without
  // backend cooperation, so the inspect button is hidden there.
  const canInspect = isWriteFile;

  // Prepend the inspect script so it runs before any inline scripts in the
  // artifact. Wrapping in a <script> at document start keeps the user's
  // original markup untouched if it already declares <html>/<head>.
  const srcDoc = useMemo(() => {
    if (!isWriteFile) return undefined;
    return `<script>${INSPECT_INJECTED_SCRIPT}</script>${content ?? ""}`;
  }, [content, isWriteFile]);

  return (
    <InspectOverlay enabled={canInspect} filepath={filepath} iframeRef={iframeRef}>
      <iframe
        className="size-full"
        ref={iframeRef}
        sandbox="allow-scripts allow-forms"
        title="Artifact preview"
        {...(isWriteFile
          ? { srcDoc }
          : url
            ? { src: url }
            : {})}
      />
    </InspectOverlay>
  );
}
