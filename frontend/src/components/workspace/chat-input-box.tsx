import type { ChatStatus } from "ai";
import { memo, useCallback, useMemo, type ReactNode } from "react";

import { getBackendBaseURL } from "@/core/config";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { useI18n } from "@/core/i18n/hooks";
import type { Agent } from "@/core/agents/types";
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
import type { ThreadConnectionPhase } from "@/core/realtime";
import type { UploadedFileInfo } from "@/core/uploads";
import type { ReasoningMode } from "./reasoning-mode";
import {
  ModeSelector,
  type AgentModeName,
  type DetectResponse,
} from "./mode-selector";
import { WorkDirSelector } from "./workdir-selector";

import { ChatComposer } from "./chat-input-box/ChatComposer";
import { ModeIntentSuggestion } from "./chat-input-box/mode-intent-suggestion";
import type { GroupTaskStrategy } from "./group-task-strategy";
import type { MentionMemberInput } from "./mention-autocomplete";
import type { AutomationTarget } from "@/core/computer/api";

/**
 * Simplified chat composer for the /workspace/realtime route. Same visual
 * language as the unified task composer: flat card, AccessPill on left,
 * ModelPicker + send on right.
 */

export interface ChatInputBoxProps {
  status?: ChatStatus;
  disabled?: boolean;
  /** Thread mutations are safe only after the socket has reopened and the
   * server-owned history has been reconciled. Draft editing remains available
   * while this is false. */
  readyForMutations?: boolean;
  connectionPhase?: ThreadConnectionPhase;
  onRetryConnection?: () => void | Promise<void>;
  model?: string;
  modelName?: string;
  mode?: ReasoningMode;
  threadId?: string;
  /** Members shown first in the @ picker for a project/group conversation. */
  mentionMembers?: MentionMemberInput[];
  /** Optional per-turn response strategy rendered inside the composer footer. */
  responseModeControl?: ReactNode;
  /** Optional compact content appended to the workspace/mode status row. */
  statusTrailing?: ReactNode;
  /** Stable browser tab / desktop window bound to this conversation. */
  automationTarget?: AutomationTarget | null;
  onAutomationTargetChange?: (target: AutomationTarget | null) => void;
  /** Group conversations also expose the workspace/mode strip. Their selected
   * mode is projected into this per-turn group task strategy. */
  isGroupConversation?: boolean;
  groupTaskStrategy?: GroupTaskStrategy;
  onGroupTaskStrategyChange?: (strategy: GroupTaskStrategy) => void;
  /** Project planning is a durable group capability, not a per-turn task
   * strategy. This independent action creates it or opens its workbench. */
  projectCapabilityEnabled?: boolean;
  onProjectCapabilityAction?: () => void;
  /** Opens a workspace side panel for local slash commands such as /record. */
  onSwitchPanel?: (panel: string) => void;
  workDir?: string;
  displayAgent?: Pick<
    Agent,
    "name" | "display_name" | "avatar_url" | "icon"
  > | null;
  /** Show the workdir selector pill in the footer. Default false (chat
   * doesn't need a folder); pass true for code-flavored conversations
   * that read/edit local files. */
  showWorkDirSelector?: boolean;
  /** Show the shared General / Design mode selector independently from the
   * workdir picker. Embedded Design Canvas chats need the mode control while
   * intentionally hiding local-folder controls. */
  showModeSelector?: boolean;
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
  projectDetection?: DetectResponse | null;
  reasoningEffort?: ReasoningEffort;
  /** Use the shared server-owned model profile control. This is intentionally
   * independent of the selected role: roles change persona/capabilities, not
   * the user's Octopus vs ChatGPT/Codex model source. */
  modelProfileControl?: boolean;
  /** Execution kernel for this role. Model source remains independently
   * selectable: Octopus uses per-thread model_name, Codex uses its scoped
   * server profile. */
  executionEngine?: "octopus" | "codex";
  onPermissionModeChange?: (mode: PermissionMode) => void;
  onProjectAgentModeChange?: (mode: AgentModeName) => void;
  /** User-only companion to onProjectAgentModeChange. It fires after the
   * selection is saved and excludes hydration/auto-detection updates. */
  onProjectAgentModeUserChange?: (mode: AgentModeName) => void;
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
  /** Add a quiet, non-message timeline marker after a confirmed model switch. */
  onModelSwitchNotice?: (modelName: string) => void;
  onModeChange?: (mode: ReasoningMode, draft?: string) => void;
  onDeepResearch?: (
    topic: string,
    options?: DeepResearchComposerOptions,
  ) => void | boolean | Promise<void | boolean>;
  onSubmit?: (message: {
    text: string;
    images?: File[];
    files?: File[];
    /** Server-side info for attachments already uploaded on attach. */
    uploaded?: UploadedFileInfo[];
  }) => void | boolean;
  onStop?: () => void | Promise<void>;
  /** Prevent repeated stop requests while the server acknowledges one. */
  isStopping?: boolean;
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
    codeModeUnlocked = false,
    onProjectAgentModeChange,
    onProjectAgentModeUserChange,
    onProjectDetectionChange,
    onManualOverrideChange,
    modeIntentSuggestion,
    onAcceptModeIntent,
    onDismissModeIntent,
    isGroupConversation = false,
    groupTaskStrategy = "auto",
    onGroupTaskStrategyChange,
    statusTrailing,
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
  // Personal and project workspaces share the same two work modes. A folder
  // changes scope only; it must not replace the mode selector with another
  // vocabulary or another backend contract.
  const showModeSegment = props.showModeSelector ?? showWorkDirSelector;
  // Read-only is no longer a standalone chip — it folds into a 🔒 lock badge on
  // the mode chip (passed to ModeSelector as readOnlyHint). "项目写入" is the
  // expected default and needs no indicator; only read-only is surfaced.
  const projectReadOnlyHint = `${t.chatInputBox.projectStatusTitle}: ${t.chatInputBox.projectStatusDescLocked}`;
  const visibleProjectMode =
    isGroupConversation && groupTaskStrategy === "uxui"
      ? "uxui"
      : projectAgentMode;
  const groupProjectModeLabels = isGroupConversation
    ? {
        develop: t.modes.develop,
        uxui: t.modes.uxui,
      }
    : undefined;
  const changeProjectMode = useCallback(
    (next: AgentModeName) => {
      if (isGroupConversation && onGroupTaskStrategyChange) {
        onGroupTaskStrategyChange(next);
        return;
      }
      onProjectAgentModeChange?.(next);
    },
    [isGroupConversation, onGroupTaskStrategyChange, onProjectAgentModeChange],
  );
  const showAgentSegment = false;
  const statusSegmentCount =
    (showAgentSegment ? 1 : 0) +
    (showWorkDirSegment ? 1 : 0) +
    (showModeSegment ? 1 : 0) +
    (statusTrailing ? 1 : 0);
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
      {showStatusStrip && (
        <div
          data-testid="chat-status-strip"
          className="flex min-h-8 items-center gap-2 overflow-x-auto px-2 pt-1 text-xs text-muted-foreground [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
        >
          <div className="inline-flex max-w-full items-center gap-1.5 rounded-lg px-0.5 py-0.5">
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
              </>
            ) : null}
            {showModeSegment ? (
              <>
                {showWorkDirSegment ? (
                  <span
                    className="h-3 w-px shrink-0 bg-border/35"
                    aria-hidden="true"
                  />
                ) : null}
                <ModeSelector
                  workDir={workDir ?? ""}
                  sessionId={threadId ?? "new"}
                  mode={visibleProjectMode}
                  labelOverrides={groupProjectModeLabels}
                  codeModeUnlocked={codeModeUnlocked}
                  readOnlyHint={projectReadOnlyHint}
                  chromeless
                  permissionLabel={permissionLabel}
                  onModeChange={changeProjectMode}
                  onUserModeChange={onProjectAgentModeUserChange}
                  onDetectionChange={onProjectDetectionChange}
                  onManualOverrideChange={onManualOverrideChange}
                />
              </>
            ) : null}
            {statusTrailing ? (
              <>
                {(showAgentSegment ||
                  showWorkDirSegment ||
                  showModeSegment) && (
                  <span
                    className="h-3 w-px shrink-0 bg-border/35"
                    aria-hidden="true"
                  />
                )}
                {statusTrailing}
              </>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}

export const ChatInputBox = memo(ChatInputBoxImpl);
