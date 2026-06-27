import { useState } from "react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/core/i18n/hooks";
import { LivePreviewPanel } from "@/components/workspace/live-preview-panel";
import { TerminalPanel } from "@/components/workspace/terminal-panel";

type ToolPanelTab = "preview" | "terminal";

interface ToolPanelProps {
  /** Thread id — used to scope the terminal session so parallel threads don't collide. */
  threadId: string;
  /** Working directory for the terminal and (by convention) the preview. */
  workDir: string;
  /** Direct URL to render in the preview iframe (takes precedence over inline content). */
  previewUrl?: string | null;
  previewHtml?: string;
  previewCss?: string;
  previewJs?: string;
  /** Bubble preview console diagnostics up to the chat. */
  onSendDiagnosticToChat?: (diagnostic: unknown) => void;
  /** Which tab to show initially. Defaults to "preview". */
  defaultTab?: ToolPanelTab;
  className?: string;
}

/**
 * Right-hand tool panel for the realtime UI. Hosts the shared preview and
 * terminal components behind a simple tab switcher. We deliberately remount
 * the active panel on switch (via `key`) so each tab gets a clean lifecycle
 * and we don't leak ws/iframe state between views.
 */
export function ToolPanel({
  threadId,
  workDir,
  previewUrl,
  previewHtml,
  previewCss,
  previewJs,
  onSendDiagnosticToChat,
  defaultTab = "preview",
  className,
}: ToolPanelProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<ToolPanelTab>(defaultTab);

  const terminalSessionId = `${threadId}:realtime-tool-panel`;

  return (
    <div
      className={cn(
        "flex flex-col h-full border-l border-border/60 bg-background/30",
        className,
      )}
    >
      {/* Tab bar */}
      <div className="flex items-center gap-1 border-b border-border/60 px-2 py-1.5">
        <div className="flex items-center rounded-lg bg-muted/50 p-0.5">
          <button
            type="button"
            onClick={() => setActiveTab("preview")}
            className={cn(
              "px-3 py-1 text-xs font-medium rounded-md transition-all",
              activeTab === "preview"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.codeMode.toolPanelPreview}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("terminal")}
            className={cn(
              "px-3 py-1 text-xs font-medium rounded-md transition-all",
              activeTab === "terminal"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t.codeMode.toolPanelTerminal}
          </button>
        </div>
      </div>

      {/* Content area */}
      <div key={activeTab} className="flex-1 overflow-hidden">
        {activeTab === "preview" ? (
          <LivePreviewPanel
            previewUrl={previewUrl}
            htmlContent={previewHtml}
            cssContent={previewCss}
            jsContent={previewJs}
            onSendDiagnosticToChat={onSendDiagnosticToChat}
            threadId={threadId}
            workspacePath={workDir}
            className="h-full"
          />
        ) : (
          <TerminalPanel
            sessionId={terminalSessionId}
            cwd={workDir}
            className="h-full"
          />
        )}
      </div>
    </div>
  );
}
