import type { ChatStatus } from "ai";
import { memo, useMemo } from "react";

import { getBackendBaseURL } from "@/core/config";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { useI18n } from "@/core/i18n/hooks";
import type { Agent } from "@/core/agents/types";
import type { PetMood } from "@/components/desktop-pet";
import {
  normalizePermissionMode,
  type PermissionMode,
} from "@/core/permissions";
import type {
  ResearchMaterial,
  ResearchRole,
  ResearchSourceKind,
} from "@/core/research/api";
import type { ReasoningEffort } from "@/core/threads";
import { cn } from "@/lib/utils";

import type { ReasoningMode } from "./reasoning-mode";
import {
  ModeSelector,
  type AgentModeName,
  type AuditIntensity,
  type DetectResponse,
} from "./mode-selector";
import {
  PersonalModeSelector,
  type PersonalMode,
} from "./personal-mode-selector";
import { WorkDirSelector } from "./workdir-selector";

import { ChatComposer } from "./chat-input-box/ChatComposer";
import { ModeIntentSuggestion } from "./chat-input-box/mode-intent-suggestion";

/**
 * Simplified chat composer for the /workspace/realtime route. Same visual
 * language as the unified task composer: flat card, AccessPill on left,
 * ModelPicker + send on right.
 */

export interface ChatInputBoxProps {
  status?: ChatStatus;
  disabled?: boolean;
  model?: string;
  modelName?: string;
  mode?: ReasoningMode;
  threadId?: string;
  workDir?: string;
  displayAgent?: Pick<
    Agent,
    "name" | "display_name" | "avatar_url" | "icon"
  > | null;
  petMood?: PetMood;
  /** Show the workdir selector pill in the footer. Default false (chat
   * doesn't need a folder); pass true for code-flavored conversations
   * that read/edit local files. */
  showWorkDirSelector?: boolean;
  onWorkDirChange?: (dir: string) => void;
  lockWorkDirToThread?: boolean;
  onOpenWorkDirInNewTask?: (dir: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  defaultValue?: string;
  /** 当前上下文 token 数量 */
  contextTokens?: number;
  /** 最大上下文限制 */
  maxContextTokens?: number;
  /** 上下文压缩是否正在执行 */
  isCompressingContext?: boolean;
  /** 压缩回调 */
  onCompressContext?: () => void | Promise<void>;
  allowAgentModes?: boolean;
  showInspirationToggle?: boolean;
  permissionMode?: PermissionMode;
  codeModeUnlocked?: boolean;
  projectAgentMode?: AgentModeName;
  auditIntensity?: AuditIntensity;
  /** Personal-space work mode (general/build/research). Surfaced only when no
   * project dir is bound; the parent threads it into the turn as personal_mode. */
  personalMode?: PersonalMode;
  projectDetection?: DetectResponse | null;
  reasoningEffort?: ReasoningEffort;
  /** When set, this chat targets a local CLI partner (e.g. "codex-cli"); the
   * model control switches from the Octopus picker to the partner's own model
   * (passed to the CLI via -m). */
  partnerId?: string;
  /** User override for the partner model; empty ⇒ the CLI's own default. */
  partnerModel?: string;
  onPartnerModelChange?: (model: string) => void;
  onPermissionModeChange?: (mode: PermissionMode) => void;
  onProjectAgentModeChange?: (mode: AgentModeName) => void;
  onAuditIntensityChange?: (intensity: AuditIntensity) => void;
  onPersonalModeChange?: (mode: PersonalMode) => void;
  /** Notify when the user manually overrides the project work mode (or when
   * the override is cleared). Intent-based auto-switching respects this. */
  onManualOverrideChange?: (isManual: boolean) => void;
  /** A pending intent-based mode suggestion to render above the composer. */
  modeIntentSuggestion?: { mode: AgentModeName; label: string } | null;
  onAcceptModeIntent?: (mode: AgentModeName) => void;
  onDismissModeIntent?: (mode: AgentModeName) => void;
  /** Project (milestone) mode toggle — surfaced as a deletable 🚩 chip. The turn
   * can route this through the Project OS / cowork group when on. */
  onProjectModeChange?: (active: boolean) => void;
  onProjectDetectionChange?: (detection: DetectResponse | null) => void;
  onReasoningEffortChange?: (effort: ReasoningEffort) => void;
  onModelChange?: (modelName: string) => void;
  onModeChange?: (mode: ReasoningMode, draft?: string) => void;
  onDeepResearch?: (
    topic: string,
    options?: DeepResearchComposerOptions,
  ) => void | boolean | Promise<void | boolean>;
  onSubmit?: (message: {
    text: string;
    images?: File[];
    files?: File[];
  }) => void;
  onStop?: () => void;
  /** True while attachments are being uploaded to the backend. Surfaces
   * a progress hint on the composer so the user knows the send is not
   * finished yet. */
  isUploading?: boolean;
  className?: string;
}

export interface DeepResearchComposerOptions {
  urls: string[];
  materials: Partial<ResearchMaterial>[];
  sourceKinds: ResearchSourceKind[];
  roles?: ResearchRole[];
  maxSubagents?: number;
  maxSearches: number;
}

function ChatInputBoxImpl(props: ChatInputBoxProps) {
  const {
    showWorkDirSelector = false,
    displayAgent,
    workDir,
    threadId,
    onWorkDirChange,
    lockWorkDirToThread = false,
    onOpenWorkDirInNewTask,
    permissionMode,
    mode = "react",
    projectAgentMode = "develop",
    auditIntensity = "standard",
    codeModeUnlocked = false,
    personalMode = "general",
    onProjectAgentModeChange,
    onAuditIntensityChange,
    onPersonalModeChange,
    onProjectDetectionChange,
    onManualOverrideChange,
    modeIntentSuggestion,
    onAcceptModeIntent,
    onDismissModeIntent,
  } = props;

  const { t } = useI18n();

  // ── Status strip derived values ──────────────────────────────
  const resolvedPermissionMode = normalizePermissionMode(permissionMode);
  const hasWorkDir = Boolean(workDir?.trim());
  const isProjectMode = mode === "code" && !!workDir?.trim();
  const permissionLabel =
    resolvedPermissionMode === "bypassPermissions"
      ? t.chatInputBox.permissionFullAccess
      : resolvedPermissionMode === "acceptEdits"
        ? t.chatInputBox.permissionAcceptEdits
        : t.chatInputBox.permissionConfirm;
  const displayAgentAvatar = useMemo(() => {
    const url = displayAgent?.avatar_url;
    if (!url) return null;
    if (url.startsWith("http://") || url.startsWith("https://")) {
      return withAgentAvatarVersion(url);
    }
    return withAgentAvatarVersion(`${getBackendBaseURL()}${url}`);
  }, [displayAgent?.avatar_url]);
  const displayAgentLabel =
    displayAgent?.display_name?.trim() || displayAgent?.name?.trim() || "Agent";
  const displayAgentInitial =
    displayAgentLabel.trim().charAt(0).toUpperCase() || "A";
  const displayAgentIcon = displayAgent?.icon?.trim() || "";
  // Surface the workspace-directory picker even in a fresh personal-space
  // conversation (no workDir yet). Previously this was gated on
  // ``isProjectMode || hasWorkDir`` — a chicken-and-egg: you needed a bound
  // directory before the picker appeared, so there was no inline way to choose
  // one. When the parent opts into the picker (``showWorkDirSelector``), show it
  // so picking a folder is the entry point into a project/code workflow.
  const showWorkDirSegment = isProjectMode || hasWorkDir || showWorkDirSelector;
  const showModeSegment = isProjectMode;
  // Read-only is no longer a standalone chip — it folds into a 🔒 lock badge on
  // the mode chip (passed to ModeSelector as readOnlyHint). "项目写入" is the
  // expected default and needs no indicator; only read-only is surfaced.
  const projectReadOnlyHint = `${t.chatInputBox.projectStatusTitle}: ${t.chatInputBox.projectStatusDescLocked}`;
  // Personal-space work mode (general/build/research) shows only when no project
  // dir is bound — the project ModeSelector takes over once a folder is picked.
  const showPersonalModeSegment = !hasWorkDir && !isProjectMode;
  const showAgentSegment = false;
  const statusSegmentCount =
    (showAgentSegment ? 1 : 0) +
    (showWorkDirSegment ? 1 : 0) +
    (showModeSegment ? 1 : 0) +
    (showPersonalModeSegment ? 1 : 0);
  const showStatusStrip = statusSegmentCount > 0;

  return (
    <>
      {modeIntentSuggestion ? (
        <ModeIntentSuggestion
          mode={modeIntentSuggestion.mode}
          modeLabel={modeIntentSuggestion.label}
          onAccept={onAcceptModeIntent}
          onDismiss={onDismissModeIntent}
        />
      ) : null}
      <ChatComposer {...props} />
      {showWorkDirSelector && showStatusStrip && (
        <div className="flex min-h-7 flex-wrap items-center gap-2 border-t border-border-subtle/60 px-2 pt-1.5 text-xs text-muted-foreground">
          <div
            className={cn(
              "inline-flex max-w-full items-center gap-1.5",
              statusSegmentCount > 1
                ? "border-l border-border-subtle pl-2"
                : "pl-0",
            )}
          >
            {showAgentSegment ? (
              <>
                <div
                  className="inline-flex min-w-0 max-w-[124px] items-center gap-1.5 rounded-full px-2 py-1"
                  title={displayAgentLabel}
                >
                  <span className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted text-xs font-semibold text-muted-foreground">
                    {displayAgentAvatar ? (
                      <img
                        src={displayAgentAvatar}
                        alt={displayAgentLabel}
                        className="size-full object-cover"
                      />
                    ) : displayAgentIcon ? (
                      displayAgentIcon
                    ) : (
                      displayAgentInitial
                    )}
                  </span>
                  <span className="truncate">{displayAgentLabel}</span>
                </div>
                {(showWorkDirSegment || showModeSegment) && (
                  <span
                    className="h-3 w-px shrink-0 bg-border/35"
                    aria-hidden="true"
                  />
                )}
              </>
            ) : null}
            {showWorkDirSegment ? (
              <>
                <WorkDirSelector
                  workDir={workDir ?? ""}
                  onWorkDirChange={onWorkDirChange}
                  lockToCurrentThread={lockWorkDirToThread}
                  onOpenWorkDirInNewTask={onOpenWorkDirInNewTask}
                  variant="muted"
                  chromeless
                />
                {showModeSegment && (
                  <>
                    <span
                      className="h-3 w-px shrink-0 bg-border/35"
                      aria-hidden="true"
                    />
                    <ModeSelector
                      workDir={workDir ?? ""}
                      sessionId={threadId ?? "new"}
                      mode={projectAgentMode}
                      auditIntensity={auditIntensity}
                      codeModeUnlocked={codeModeUnlocked}
                      readOnlyHint={projectReadOnlyHint}
                      chromeless
                      permissionLabel={permissionLabel}
                      onModeChange={
                        onProjectAgentModeChange ?? (() => undefined)
                      }
                      onAuditIntensityChange={onAuditIntensityChange}
                      onDetectionChange={onProjectDetectionChange}
                      onManualOverrideChange={onManualOverrideChange}
                    />
                  </>
                )}
              </>
            ) : null}
            {showPersonalModeSegment ? (
              <>
                {(showAgentSegment || showWorkDirSegment) && (
                  <span
                    className="h-3 w-px shrink-0 bg-border/35"
                    aria-hidden="true"
                  />
                )}
                <PersonalModeSelector
                  mode={personalMode}
                  chromeless
                  onModeChange={onPersonalModeChange ?? (() => undefined)}
                />
              </>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}

export const ChatInputBox = memo(ChatInputBoxImpl);
