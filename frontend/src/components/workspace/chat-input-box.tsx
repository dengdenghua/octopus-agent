import type { ChatStatus } from "ai";
import {
  ArrowUpIcon,
  CalendarClockIcon,
  Code2Icon,
  FileTextIcon,
  FolderOpenIcon,
  GitBranchIcon,
  ImageIcon,
  LinkIcon,
  LightbulbIcon,
  LockIcon,
  ZapIcon,
  PaperclipIcon,
  PlusIcon,
  PresentationIcon,
  SearchIcon,
  SlidersHorizontalIcon,
  SparklesIcon,
  SquareIcon,
  TableIcon,
  Trash2Icon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  MentionAutocompletePopup,
  useMentionAutocomplete,
} from "./mention-autocomplete";

import { swallow } from "@/core/utils/log";
import { currentActorId } from "@/core/auth/api";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import { EvolutionIndicator } from "./evolution-indicator";
import { ModelPicker, type PickerModel } from "./model-picker";
import { PreviewRefreshIndicator } from "./preview-refresh-indicator";
import type { ReasoningMode } from "./reasoning-mode";
import { tryLocalSlash } from "./local-slash-dispatch";
import { useSlashTypeahead } from "./use-slash-typeahead";
import { ContextCompressor } from "./context-compressor";
import { PermissionIndicator } from "./permission-indicator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import {
  normalizePermissionMode,
  type PermissionMode,
} from "@/core/permissions";
import { uploadFiles } from "@/core/uploads";
import type {
  ResearchMaterial,
  ResearchRole,
  ResearchSourceKind,
} from "@/core/research/api";
import type { ReasoningEffort } from "@/core/threads";
import { WorkDirSelector } from "./workdir-selector";
import {
  type DetectResponse,
  ModeSelector,
  type AgentModeName,
} from "./mode-selector";

/**
 * Simplified chat composer for the /workspace/chats route. Same visual
 * language as TeamInputBox (flat card, AccessPill on left,
 * ModelPicker + send on right) but without team-mode pills or workdir
 * selector, since plain chat doesn't need them.
 */

export interface ChatInputBoxProps {
  status?: ChatStatus;
  disabled?: boolean;
  model?: string;
  modelName?: string;
  mode?: ReasoningMode;
  threadId?: string;
  workDir?: string;
  /** Show the workdir selector pill in the footer. Default false (chat
   * doesn't need a folder); pass true for code-flavored conversations
   * that read/edit local files. */
  showWorkDirSelector?: boolean;
  onWorkDirChange?: (dir: string) => void;
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
  onPermissionModeChange?: (mode: PermissionMode) => void;
  onProjectAgentModeChange?: (mode: AgentModeName) => void;
  onProjectDetectionChange?: (detection: DetectResponse | null) => void;
  onReasoningEffortChange?: (effort: ReasoningEffort) => void;
  onModelChange?: (modelName: string) => void;
  onModeChange?: (mode: ReasoningMode, draft?: string) => void;
  onDeepResearch?: (
    topic: string,
    options?: DeepResearchComposerOptions,
  ) => void | boolean | Promise<void | boolean>;
  onSubmit?: (message: { text: string; images?: File[] }) => void;
  onStop?: () => void;
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

interface ComposerResearchMaterial {
  id: string;
  enabled: boolean;
  material: Partial<ResearchMaterial>;
}

const RESEARCH_SOURCE_OPTIONS: Array<{
  kind: ResearchSourceKind;
  label: string;
}> = [
  { kind: "web", label: "Web" },
  { kind: "news", label: "News" },
  { kind: "academic", label: "Academic" },
  { kind: "company_site", label: "Official" },
  { kind: "ecommerce", label: "Shop" },
  { kind: "social", label: "Social" },
  { kind: "forum", label: "Forum" },
  { kind: "provided_url", label: "URLs" },
  { kind: "uploaded_file", label: "Files" },
];

const DEFAULT_RESEARCH_SOURCES: ResearchSourceKind[] = [
  "web",
  "news",
  "academic",
  "company_site",
  "ecommerce",
  "social",
  "forum",
  "provided_url",
  "uploaded_file",
];

function parseComposerUrls(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(/[\s,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

export function ChatInputBox({
  status,
  disabled,
  modelName,
  mode = "react",
  threadId,
  workDir,
  showWorkDirSelector = false,
  onWorkDirChange,
  placeholder,
  autoFocus,
  defaultValue = "",
  contextTokens = 0,
  maxContextTokens = 128000,
  isCompressingContext = false,
  onCompressContext,
  allowAgentModes = false,
  showInspirationToggle = false,
  permissionMode,
  codeModeUnlocked = false,
  projectAgentMode = "coder",
  projectDetection,
  reasoningEffort,
  onPermissionModeChange,
  onProjectAgentModeChange,
  onProjectDetectionChange,
  onReasoningEffortChange,
  onModelChange,
  onModeChange,
  onDeepResearch,
  onSubmit,
  onStop,
  className,
}: ChatInputBoxProps) {
  const { locale, t } = useI18n();
  const { models } = useModels();
  const [draft, setDraft] = useState(defaultValue);
  const [researchUrlText, setResearchUrlText] = useState("");
  const [researchTextTitle, setResearchTextTitle] = useState("");
  const [researchTextBody, setResearchTextBody] = useState("");
  const [researchNote, setResearchNote] = useState("");
  const [researchMaterials, setResearchMaterials] = useState<
    ComposerResearchMaterial[]
  >([]);
  const [researchSources, setResearchSources] = useState<ResearchSourceKind[]>(
    DEFAULT_RESEARCH_SOURCES,
  );
  const [maxSearches, setMaxSearches] = useState(274);
  const [uploadingMaterials, setUploadingMaterials] = useState(false);
  const [materialError, setMaterialError] = useState<string | null>(null);
  const [researchConfigOpen, setResearchConfigOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  // Images attached to the next message via paste / drop / image-picker.
  // Stored separately from research materials so they ride the
  // multimodal `images` channel into sendMessage rather than going
  // through the artifact-upload pipeline used by research files.
  const [pendingImages, setPendingImages] = useState<File[]>([]);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const [pendingImagePreviews, setPendingImagePreviews] = useState<
    Record<string, string>
  >({});

  // Slash-command typeahead · shared hook (see use-slash-typeahead).
  // Returns the picker JSX + a keydown handler that we call FIRST in
  // our own onKeyDown so navigation keys (↑↓/Tab/Enter/Esc) are
  // consumed before the composer's default Enter-to-submit fires.
  const { picker: slashPicker, handleKeyDown: handleSlashKeyDown } =
    useSlashTypeahead({
      draft,
      setDraft,
      focusTextarea: () => textareaRef.current?.focus(),
    });

  const {
    isOpen: mentionOpen,
    items: mentionItems,
    selectedIndex: mentionSelectedIndex,
    isLoading: isLoadingMention,
    mentionQuery,
    handleKeyDown: handleMentionKeyDown,
    selectItem: selectMentionItem,
  } = useMentionAutocomplete({
    value: draft,
    onChange: setDraft,
    workDir,
    threadId,
    actor: currentActorId(),
  });

  const pickerModels: PickerModel[] = useMemo(
    () =>
      models.map((m) => ({
        id: m.id,
        name: m.id,
        display_name: (m as { display_name?: string }).display_name ?? m.id,
      })),
    [models],
  );
  const selectedModel =
    pickerModels.find((m) => m.name === modelName) ?? pickerModels[0];
  const resolvedPermissionMode = normalizePermissionMode(permissionMode);
  const canUseDeepResearch =
    allowAgentModes && mode === "deep" && !!onDeepResearch;
  const isDeepResearchMode = canUseDeepResearch && researchConfigOpen;
  const isProjectMode = mode === "code" && !!workDir?.trim();
  const isBusy = disabled || uploadingMaterials;
  const sendLabel = locale === "zh-CN" ? "发送" : "Send";
  const stopLabel = locale === "zh-CN" ? "停止" : "Stop";
  const projectModeLabel = locale === "zh-CN" ? "项目代码模式" : "Project code";
  const projectModeHint =
    locale === "zh-CN"
      ? "已绑定本地目录，当前 Agent 会读取项目上下文并按代码任务执行。"
      : "A local folder is bound; this agent will use project context for code tasks.";
  const projectStatusTitle =
    locale === "zh-CN" ? "项目上下文已绑定" : "Project context bound";
  const projectStatusDesc = codeModeUnlocked
    ? locale === "zh-CN"
      ? "当前 Agent 已解锁代码能力，会按理解、修改、验证的闭环执行。"
      : "This agent can use code mode and will work through inspect, edit, and verify."
    : locale === "zh-CN"
      ? "当前 Agent 未声明代码写入能力，后端会降级为只读/对话范围。建议切换 Coder 或给该角色开启 code_mode_unlock。"
      : "This agent has not declared code write access; the backend will downgrade the write scope. Switch to Coder or enable code_mode_unlock.";
  const projectSignalBadges = projectDetection
    ? [
        ...(projectDetection.signals.manifests ?? []).slice(0, 3),
        ...(projectDetection.signals.lock_files ?? []).slice(0, 2),
        ...(projectDetection.signals.has_readme
          ? [locale === "zh-CN" ? "README" : "README"]
          : []),
      ]
    : [];
  const projectVerificationCommands =
    projectDetection?.signals.commands?.slice(0, 4) ?? [];
  const projectVerificationLabel = locale === "zh-CN" ? "验证命令" : "Verify";
  const permissionLabel =
    resolvedPermissionMode === "bypassPermissions"
      ? locale === "zh-CN"
        ? "完全访问"
        : "Full access"
      : resolvedPermissionMode === "acceptEdits"
        ? locale === "zh-CN"
          ? "自动接受编辑"
          : "Accept edits"
        : locale === "zh-CN"
          ? "确认后执行"
          : "Confirm";
  const parsedResearchUrls = useMemo(
    () => parseComposerUrls(researchUrlText),
    [researchUrlText],
  );
  const showContextCompressor = maxContextTokens > 0;

  useEffect(() => {
    if (!canUseDeepResearch) setResearchConfigOpen(false);
  }, [canUseDeepResearch]);

  const focusComposer = useCallback(() => {
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  const seedDraft = useCallback(
    (template: string, nextMode?: ReasoningMode) => {
      setDraft((current) => (current.trim() ? current : template));
      if (nextMode) onModeChange?.(nextMode);
      focusComposer();
    },
    [focusComposer, onModeChange],
  );

  const openResearchFilePicker = useCallback(() => {
    if (!allowAgentModes) return;
    setResearchConfigOpen(true);
    onModeChange?.("deep");
    window.setTimeout(() => fileInputRef.current?.click(), 0);
  }, [allowAgentModes, onModeChange]);

  useEffect(() => {
    const handler = (
      event: CustomEvent<{
        threadId?: string | null;
        topic?: string | null;
        text?: string | null;
      }>,
    ) => {
      const detail = event.detail;
      if (detail?.threadId && threadId && detail.threadId !== threadId) {
        return;
      }
      const nextDraft = (detail?.topic ?? detail?.text ?? "").trim();
      if (!nextDraft) return;
      setDraft(nextDraft);
      if (!allowAgentModes) {
        setTimeout(() => textareaRef.current?.focus(), 0);
        return;
      }
      setResearchConfigOpen(true);
      onModeChange?.("deep");
      setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener(
      "octopus:start-deep-research",
      handler as EventListener,
    );
    return () => {
      window.removeEventListener(
        "octopus:start-deep-research",
        handler as EventListener,
      );
    };
  }, [allowAgentModes, onModeChange, threadId]);

  // A failed send hands the text back (the draft was cleared
  // optimistically on submit). Restore only when the box is still
  // empty — if the user already started retyping, theirs wins.
  useEffect(() => {
    const handler = (
      event: CustomEvent<{ threadId?: string | null; text?: string | null }>,
    ) => {
      const detail = event.detail;
      if (detail?.threadId && threadId && detail.threadId !== threadId) {
        return;
      }
      const lostText = detail?.text ?? "";
      if (!lostText) return;
      setDraft((current) => (current.trim() ? current : lostText));
      setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener("octopus:send-failed", handler as EventListener);
    return () => {
      window.removeEventListener(
        "octopus:send-failed",
        handler as EventListener,
      );
    };
  }, [threadId]);

  const handleSubmit = useCallback(async () => {
    const text = draft.trim();
    if (!text || isBusy || status === "streaming") return;
    // Fast path: client-side slash commands (mode/model/permission/
    // compact/settings) resolve locally with no LLM round-trip.
    // Falls through for anything not handled here.
    if (
      tryLocalSlash(text, {
        onModeChange: onModeChange ? (mode) => onModeChange(mode) : undefined,
        onModelChange,
        onPermissionModeChange,
        onCompact: onCompressContext
          ? () => {
              void onCompressContext();
            }
          : undefined,
      })
    ) {
      setDraft("");
      return;
    }
    if (isDeepResearchMode) {
      const result = await onDeepResearch(text, {
        urls: parsedResearchUrls,
        materials: researchMaterials
          .filter((item) => item.enabled)
          .map((item) => item.material),
        sourceKinds: researchSources,
        maxSearches,
      });
      if (result !== false) setDraft("");
      return;
    }
    onSubmit?.({
      text,
      images: pendingImages.length > 0 ? pendingImages : undefined,
    });
    setDraft("");
    if (pendingImages.length > 0) {
      setPendingImages([]);
      setPendingImagePreviews({});
    }
  }, [
    draft,
    isBusy,
    status,
    isDeepResearchMode,
    onDeepResearch,
    onSubmit,
    parsedResearchUrls,
    researchMaterials,
    researchSources,
    maxSearches,
    onModeChange,
    onModelChange,
    onPermissionModeChange,
    onCompressContext,
  ]);

  const addMaterial = useCallback((material: Partial<ResearchMaterial>) => {
    setResearchMaterials((current) => [
      ...current,
      {
        id: `mat_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        enabled: true,
        material,
      },
    ]);
  }, []);

  const addUrlMaterial = useCallback(() => {
    const urls = parsedResearchUrls;
    if (!urls.length) return;
    urls.forEach((url) =>
      addMaterial({
        kind: "url",
        title: url,
        url,
        notes: researchNote.trim() || undefined,
      }),
    );
    setResearchUrlText("");
    setResearchNote("");
    setMaterialError(null);
  }, [addMaterial, researchNote, parsedResearchUrls]);

  const addTextMaterial = useCallback(() => {
    const text = researchTextBody.trim();
    if (!text) return;
    addMaterial({
      kind: "text",
      title: researchTextTitle.trim() || text.slice(0, 48),
      text,
      notes: researchNote.trim() || undefined,
    });
    setResearchTextTitle("");
    setResearchTextBody("");
    setResearchNote("");
    setMaterialError(null);
  }, [addMaterial, researchNote, researchTextBody, researchTextTitle]);

  const handleUploadMaterials = useCallback(
    async (files: FileList | null) => {
      if (!files?.length) return;
      if (!threadId) {
        setMaterialError(t.chatInputBox.startThreadBeforeUpload);
        return;
      }
      setUploadingMaterials(true);
      setMaterialError(null);
      try {
        const result = await uploadFiles(threadId, Array.from(files));
        result.files.forEach((file) =>
          addMaterial({
            kind: "file",
            title: file.filename,
            path: file.path,
            notes: researchNote.trim() || `uploaded file · ${file.size} bytes`,
          }),
        );
        setResearchNote("");
      } catch (err) {
        swallow(err);
        setMaterialError(
          err instanceof Error ? err.message : t.chatInputBox.uploadFailed,
        );
      } finally {
        setUploadingMaterials(false);
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [addMaterial, researchNote, t, threadId],
  );

  const toggleMaterial = useCallback((id: string) => {
    setResearchMaterials((current) =>
      current.map((item) =>
        item.id === id ? { ...item, enabled: !item.enabled } : item,
      ),
    );
  }, []);

  const removeMaterial = useCallback((id: string) => {
    setResearchMaterials((current) => current.filter((item) => item.id !== id));
  }, []);

  const toggleResearchSource = useCallback((kind: ResearchSourceKind) => {
    setResearchSources((current) => {
      if (current.includes(kind)) {
        const next = current.filter((item) => item !== kind);
        return next.length > 0 ? next : current;
      }
      return [...current, kind];
    });
  }, []);

  // ── Image attachments (paste / drop / picker) ─────────────────
  // The composer accepts images via three paths and feeds them all
  // through the same `pendingImages` slot which rides into onSubmit.
  // Previews are stored as object URLs so we can revoke them on
  // cleanup; previews are keyed by `name|size` so the UI keeps
  // referential stability across renders.
  const addPendingImages = useCallback(
    (files: File[] | FileList | null | undefined) => {
      if (!files) return;
      const arr = Array.from(files).filter((file) =>
        file.type.toLowerCase().startsWith("image/"),
      );
      if (arr.length === 0) return;
      setPendingImages((current) => {
        const known = new Set(
          current.map((file) => `${file.name}|${file.size}`),
        );
        const next = [...current];
        for (const file of arr) {
          const key = `${file.name}|${file.size}`;
          if (!known.has(key)) {
            next.push(file);
            known.add(key);
          }
        }
        return next;
      });
      setPendingImagePreviews((current) => {
        const next = { ...current };
        for (const file of arr) {
          const key = `${file.name}|${file.size}`;
          if (!next[key]) next[key] = URL.createObjectURL(file);
        }
        return next;
      });
    },
    [],
  );
  const removePendingImage = useCallback((index: number) => {
    setPendingImages((current) => {
      const removed = current[index];
      if (!removed) return current;
      const key = `${removed.name}|${removed.size}`;
      setPendingImagePreviews((prev) => {
        const url = prev[key];
        if (url) URL.revokeObjectURL(url);
        const { [key]: _omit, ...rest } = prev;
        return rest;
      });
      return current.filter((_, i) => i !== index);
    });
  }, []);
  useEffect(() => {
    // Free any leftover object URLs when the component unmounts.
    return () => {
      setPendingImagePreviews((current) => {
        for (const url of Object.values(current)) URL.revokeObjectURL(url);
        return {};
      });
    };
  }, []);
  const handlePasteImages = useCallback(
    (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = event.clipboardData?.items;
      if (!items) return;
      const files: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item && item.kind === "file") {
          const file = item.getAsFile();
          if (file && file.type.toLowerCase().startsWith("image/")) {
            files.push(file);
          }
        }
      }
      if (files.length > 0) {
        event.preventDefault();
        addPendingImages(files);
      }
    },
    [addPendingImages],
  );
  const handleDropImages = useCallback(
    (event: React.DragEvent<HTMLTextAreaElement>) => {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0) return;
      const imageFiles = Array.from(files).filter((file) =>
        file.type.toLowerCase().startsWith("image/"),
      );
      if (imageFiles.length === 0) return;
      event.preventDefault();
      addPendingImages(imageFiles);
    },
    [addPendingImages],
  );

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (handleSlashKeyDown(e)) return;
      if (mentionOpen) {
        handleMentionKeyDown(e);
        if (e.defaultPrevented) return;
      }
      if (!mentionOpen) {
        handleMentionKeyDown(e);
      }
      if (
        e.key === "Enter" &&
        !e.shiftKey &&
        !e.nativeEvent.isComposing &&
        !e.defaultPrevented
      ) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit, handleSlashKeyDown, mentionOpen, handleMentionKeyDown],
  );

  return (
    <>
      <div
        data-testid="chat-composer"
        className={cn(
          "group relative",
          "rounded-xl border border-transparent bg-[color:color-mix(in_oklch,var(--card)_92%,transparent)]",
          "backdrop-blur-[6px] transition-[box-shadow,border-color] duration-200",
          "hover:border-border/60",
          "focus-within:border-transparent",
          className,
        )}
      >
        <div className="relative">
          {slashPicker}
          {mentionOpen && (
            <MentionAutocompletePopup
              items={mentionItems}
              selectedIndex={mentionSelectedIndex}
              isLoading={isLoadingMention}
              mentionQuery={mentionQuery}
              onSelect={selectMentionItem}
            />
          )}
        </div>
        {pendingImages.length > 0 && (
          <div className="flex gap-2 overflow-x-auto px-3 pb-2 pt-1">
            {pendingImages.map((file, index) => {
              const key = `${file.name}|${file.size}`;
              const url = pendingImagePreviews[key];
              return (
                <div
                  key={key}
                  className="group relative h-16 w-16 shrink-0 overflow-hidden rounded border border-border/50"
                >
                  {url && (
                    <img
                      src={url}
                      alt={file.name}
                      className="h-full w-full object-cover"
                    />
                  )}
                  <button
                    type="button"
                    onClick={() => removePendingImage(index)}
                    className="absolute right-0.5 top-0.5 flex size-5 items-center justify-center rounded-full bg-background/80 text-muted-foreground opacity-0 backdrop-blur-sm transition-opacity hover:text-foreground group-hover:opacity-100"
                    title="Remove"
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        )}
        <textarea
          data-testid="chat-composer-input"
          ref={textareaRef}
          autoFocus={autoFocus}
          disabled={isBusy}
          placeholder={placeholder ?? t.inputBox.placeholder}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={handlePasteImages}
          onDrop={handleDropImages}
          onDragOver={(e) => {
            if (e.dataTransfer?.types?.includes("Files")) e.preventDefault();
          }}
          rows={2}
          className="w-full resize-none bg-transparent px-3 py-1.5 text-[13px] leading-snug outline-none placeholder:text-muted-foreground/50 disabled:opacity-60"
        />
        {isDeepResearchMode && researchConfigOpen && (
          <div className="absolute bottom-11 left-2 right-2 z-30 max-h-[min(70vh,560px)] overflow-y-auto rounded-2xl border border-border/70 bg-popover/95 px-3 py-3 shadow-[0_18px_70px_-28px_rgba(0,0,0,0.45)] backdrop-blur-xl">
            <div className="mb-2 flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2 text-[12px] font-medium text-foreground">
                <SearchIcon className="size-4 text-primary" />
                <span>{t.chatInputBox.deepResearchConfig}</span>
                {researchMaterials.length > 0 && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-normal text-muted-foreground">
                    {researchMaterials.filter((item) => item.enabled).length}{" "}
                    {t.chatInputBox.materials.toLowerCase()}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setResearchConfigOpen(false)}
                className="rounded-lg px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                {t.chatInputBox.collapse}
              </button>
            </div>
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
              <label className="flex min-w-0 items-center gap-2 rounded-lg border border-border/50 bg-background/40 px-2 py-1.5">
                <LinkIcon className="size-3.5 shrink-0 text-muted-foreground" />
                <input
                  value={researchUrlText}
                  onChange={(event) => setResearchUrlText(event.target.value)}
                  disabled={isBusy || status === "streaming"}
                  placeholder="https://example.com, https://..."
                  className="min-w-0 flex-1 bg-transparent text-[12px] outline-none placeholder:text-muted-foreground/45 disabled:opacity-60"
                />
              </label>
              <div className="flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <SearchIcon className="size-3.5" />
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    step={10}
                    value={maxSearches}
                    onChange={(event) => {
                      const next = Number.parseInt(event.target.value, 10);
                      if (Number.isFinite(next)) {
                        setMaxSearches(Math.min(1000, Math.max(1, next)));
                      }
                    }}
                    disabled={isBusy || status === "streaming"}
                    className="h-7 w-16 rounded-md border border-border/50 bg-background/50 px-1.5 text-center text-[12px] text-foreground outline-none"
                  />
                </label>
              </div>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
              <input
                value={researchNote}
                onChange={(event) => setResearchNote(event.target.value)}
                disabled={isBusy || status === "streaming"}
                placeholder={t.chatInputBox.materialNote}
                className="h-8 min-w-0 rounded-lg border border-border/50 bg-background/40 px-2 text-[12px] outline-none placeholder:text-muted-foreground/45 disabled:opacity-60"
              />
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={addUrlMaterial}
                  disabled={
                    !parsedResearchUrls.length ||
                    isBusy ||
                    status === "streaming"
                  }
                  className="flex h-8 items-center gap-1 rounded-lg border border-border/50 px-2 text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                >
                  <PlusIcon className="size-3.5" />
                  {t.chatInputBox.url}
                </button>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isBusy || status === "streaming"}
                  className="flex h-8 items-center gap-1 rounded-lg border border-border/50 px-2 text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {uploadingMaterials ? (
                    <SearchIcon className="size-3.5 animate-pulse" />
                  ) : (
                    <PaperclipIcon className="size-3.5" />
                  )}
                  {t.chatInputBox.file}
                </button>
              </div>
            </div>
            <div className="mt-2 grid gap-2 md:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto]">
              <input
                value={researchTextTitle}
                onChange={(event) => setResearchTextTitle(event.target.value)}
                disabled={isBusy || status === "streaming"}
                placeholder={t.chatInputBox.textTitle}
                className="h-8 min-w-0 rounded-lg border border-border/50 bg-background/40 px-2 text-[12px] outline-none placeholder:text-muted-foreground/45 disabled:opacity-60"
              />
              <input
                value={researchTextBody}
                onChange={(event) => setResearchTextBody(event.target.value)}
                disabled={isBusy || status === "streaming"}
                placeholder={t.chatInputBox.pasteTextMaterial}
                className="h-8 min-w-0 rounded-lg border border-border/50 bg-background/40 px-2 text-[12px] outline-none placeholder:text-muted-foreground/45 disabled:opacity-60"
              />
              <button
                type="button"
                onClick={addTextMaterial}
                disabled={
                  !researchTextBody.trim() || isBusy || status === "streaming"
                }
                className="flex h-8 items-center gap-1 rounded-lg border border-border/50 px-2 text-[11px] text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
              >
                <FileTextIcon className="size-3.5" />
                {t.chatInputBox.text}
              </button>
            </div>
            {materialError && (
              <div className="mt-2 text-[11px] text-destructive">
                {materialError}
              </div>
            )}
            {researchMaterials.length > 0 && (
              <div className="mt-2 space-y-1.5">
                {researchMaterials.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center gap-2 rounded-lg border border-border/50 bg-background/35 px-2 py-1.5"
                  >
                    <input
                      type="checkbox"
                      checked={item.enabled}
                      onChange={() => toggleMaterial(item.id)}
                      disabled={isBusy || status === "streaming"}
                      className="size-3.5"
                      title={t.chatInputBox.toggleMaterial}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[11px] font-medium">
                        {item.material.title ||
                          item.material.url ||
                          item.material.path ||
                          "Material"}
                      </div>
                      <div className="truncate text-[10px] text-muted-foreground">
                        {item.material.kind}
                        {item.material.notes ? ` · ${item.material.notes}` : ""}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeMaterial(item.id)}
                      disabled={isBusy || status === "streaming"}
                      className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                      title={t.chatInputBox.removeMaterial}
                    >
                      <Trash2Icon className="size-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1">
              {RESEARCH_SOURCE_OPTIONS.map((source) => {
                const active = researchSources.includes(source.kind);
                return (
                  <button
                    key={source.kind}
                    type="button"
                    onClick={() => toggleResearchSource(source.kind)}
                    disabled={isBusy || status === "streaming"}
                    className={cn(
                      "rounded-md border px-2 py-1 text-[10px] font-medium transition-colors",
                      active
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border/50 text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                      "disabled:cursor-not-allowed disabled:opacity-50",
                    )}
                  >
                    {source.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(event) => void handleUploadMaterials(event.target.files)}
        />
        <input
          ref={imageInputRef}
          type="file"
          multiple
          accept="image/*"
          className="hidden"
          onChange={(event) => {
            addPendingImages(event.target.files);
            if (imageInputRef.current) imageInputRef.current.value = "";
          }}
        />
        <div className="composer-footer flex items-center justify-between gap-2 border-t border-transparent px-2 py-1 transition-colors duration-200 group-hover:border-border/25">
          <div className="flex items-center gap-1">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="chat-tools-trigger"
                  disabled={isBusy || status === "streaming"}
                  className="flex size-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                  title={t.chatInputBox.quickCapabilities}
                  aria-label={t.chatInputBox.quickCapabilities}
                >
                  <PlusIcon className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                data-testid="chat-tools-menu"
                align="start"
                sideOffset={8}
                className="w-60 rounded-xl border-border/70 p-1.5 shadow-[0_16px_48px_-24px_rgba(0,0,0,0.35)]"
              >
                <DropdownMenuLabel className="px-2 py-1.5 text-[11px] font-medium text-muted-foreground">
                  {t.chatInputBox.quickCapabilities}
                </DropdownMenuLabel>
                {canUseDeepResearch && (
                  <>
                    <DropdownMenuItem
                      onClick={() => setResearchConfigOpen((open) => !open)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <SlidersHorizontalIcon className="size-4" />
                      {t.chatInputBox.deepResearchConfig}
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                  </>
                )}
                {allowAgentModes && (
                  <DropdownMenuItem
                    onClick={openResearchFilePicker}
                    className="gap-2 rounded-lg text-[13px]"
                  >
                    <PaperclipIcon className="size-4" />
                    {t.chatInputBox.addResearchMaterial}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem
                  onClick={() => imageInputRef.current?.click()}
                  className="gap-2 rounded-lg text-[13px]"
                >
                  <ImageIcon className="size-4" />
                  添加图片（粘贴 / 拖拽 / 选择）
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => seedDraft(t.chatInputBox.seedWebSearch)}
                  className="gap-2 rounded-lg text-[13px]"
                >
                  <SearchIcon className="size-4" />
                  {t.chatInputBox.webSearch}
                </DropdownMenuItem>
                {allowAgentModes && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onClick={() => seedDraft(t.chatInputBox.seedCreatePpt)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <PresentationIcon className="size-4" />
                      {t.chatInputBox.createPpt}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => seedDraft(t.chatInputBox.seedCreateHtml)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <FileTextIcon className="size-4" />
                      {t.chatInputBox.createHtml}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => seedDraft(t.chatInputBox.seedRenderTable)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <TableIcon className="size-4" />
                      {t.chatInputBox.renderTable}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => seedDraft(t.chatInputBox.seedCreateImage)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <ImageIcon className="size-4" />
                      {t.chatInputBox.createImage}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() =>
                        seedDraft(t.chatInputBox.seedScheduledTask)
                      }
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <CalendarClockIcon className="size-4" />
                      {t.chatInputBox.scheduledTask}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => seedDraft(t.chatInputBox.seedProjectFiles)}
                      className="gap-2 rounded-lg text-[13px]"
                    >
                      <FolderOpenIcon className="size-4" />
                      {t.chatInputBox.projectFiles}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <PreviewRefreshIndicator />
            <PermissionIndicator
              mode={resolvedPermissionMode}
              onModeChange={(nextMode) => onPermissionModeChange?.(nextMode)}
            />
            {/* 上下文压缩指示器 */}
            {showContextCompressor && (
              <ContextCompressor
                currentTokens={contextTokens}
                maxTokens={maxContextTokens}
                isCompressing={isCompressingContext}
                onCompress={onCompressContext}
                disabled={isBusy || status === "streaming"}
              />
            )}
          </div>
          <div className="flex items-center gap-2">
            {showInspirationToggle && (
              <button
                type="button"
                disabled={disabled || status === "streaming"}
                onClick={() =>
                  onModeChange?.(mode === "chat" ? "react" : "chat", draft)
                }
                className={cn(
                  "flex size-7 items-center justify-center rounded-lg border text-[11px] font-medium transition-colors",
                  mode === "chat"
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "border-border/60 text-muted-foreground hover:bg-muted/60 hover:text-foreground",
                  "disabled:cursor-not-allowed disabled:opacity-45",
                )}
                title={t.inputBox.chatModeDescription}
                aria-label={t.inputBox.chatModeDescription}
                aria-pressed={mode === "chat"}
              >
                <span className="relative flex size-4 items-center justify-center">
                  <LightbulbIcon className="size-4" />
                  <ZapIcon
                    className={cn(
                      "absolute left-1/2 top-[46%] size-2.5 -translate-x-1/2 -translate-y-1/2",
                      mode === "chat" ? "fill-current" : "",
                    )}
                    strokeWidth={2.4}
                  />
                </span>
              </button>
            )}
            <EvolutionIndicator compact />
            <ModelPicker
              models={pickerModels}
              // Pass the raw modelName so the picker sees the "auto"
              // sentinel — selectedModel falls back to pickerModels[0]
              // when name doesn't match, which would mask the auto state.
              value={modelName ?? selectedModel?.name}
              onChange={(name) => onModelChange?.(name)}
              reasoningEffort={reasoningEffort}
              reasoningEffortDisabled={disabled || status === "streaming"}
              onReasoningEffortChange={onReasoningEffortChange}
            />
            {status === "streaming" ? (
              <button
                type="button"
                onClick={onStop}
                className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background hover:opacity-80 transition-opacity"
                title={stopLabel}
                aria-label={stopLabel}
              >
                <SquareIcon className="size-3" fill="currentColor" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                data-testid="chat-send-button"
                disabled={!draft.trim() || isBusy}
                className={cn(
                  "flex size-7 items-center justify-center rounded-lg transition-[background-color,transform] duration-150",
                  isDeepResearchMode
                    ? "bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95"
                    : "bg-foreground text-background hover:bg-foreground/90 active:scale-95",
                  "disabled:bg-muted disabled:text-muted-foreground disabled:cursor-not-allowed",
                )}
                title={sendLabel}
                aria-label={sendLabel}
              >
                <ArrowUpIcon className="size-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
      {showWorkDirSelector && (
        <div className="flex flex-wrap items-center gap-2 px-2 pt-1">
          <WorkDirSelector
            workDir={workDir ?? ""}
            onWorkDirChange={onWorkDirChange}
            variant="muted"
          />
          {isProjectMode && (
            <span
              className="inline-flex min-w-0 items-center gap-1.5 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:text-emerald-300"
              title={projectModeHint}
            >
              <Code2Icon className="size-3" />
              <span className="truncate">{projectModeLabel}</span>
            </span>
          )}
        </div>
      )}
      {isProjectMode && (
        <div
          className={cn(
            "mx-2 mt-2 rounded-lg border px-3 py-2 text-xs",
            codeModeUnlocked
              ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200"
              : "border-amber-500/25 bg-amber-500/10 text-amber-800 dark:text-amber-200",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <span
                className={cn(
                  "grid size-6 shrink-0 place-items-center rounded-md",
                  codeModeUnlocked
                    ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-200"
                    : "bg-amber-500/15 text-amber-700 dark:text-amber-200",
                )}
              >
                {codeModeUnlocked ? (
                  <Code2Icon className="size-3.5" />
                ) : (
                  <LockIcon className="size-3.5" />
                )}
              </span>
              <div className="min-w-0">
                <div className="flex min-w-0 items-center gap-1.5 font-medium text-foreground">
                  <span className="truncate">{projectStatusTitle}</span>
                  <span className="rounded-full bg-background/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    {permissionLabel}
                  </span>
                </div>
                <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                  {workDir}
                </div>
              </div>
            </div>
            <ModeSelector
              workDir={workDir ?? ""}
              sessionId={threadId ?? "new"}
              mode={projectAgentMode}
              onModeChange={onProjectAgentModeChange ?? (() => undefined)}
              onDetectionChange={onProjectDetectionChange}
            />
          </div>
          {projectSignalBadges.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {projectSignalBadges.map((badge) => (
                <span
                  key={badge}
                  className="rounded-md bg-background/70 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {badge}
                </span>
              ))}
            </div>
          )}
          {projectVerificationCommands.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] font-medium text-muted-foreground">
                {projectVerificationLabel}
              </span>
              {projectVerificationCommands.map((item) => (
                <span
                  key={`${item.kind}:${item.command}`}
                  className="inline-flex max-w-full items-center gap-1 rounded-md bg-background/75 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                  title={item.source}
                >
                  <span className="font-sans uppercase text-foreground/60">
                    {item.kind}
                  </span>
                  <span className="truncate">{item.command}</span>
                </span>
              ))}
            </div>
          )}
          <div className="mt-2 flex items-start gap-1.5 text-[11px] leading-5 text-muted-foreground">
            {codeModeUnlocked ? (
              <GitBranchIcon className="mt-0.5 size-3.5 shrink-0" />
            ) : (
              <SparklesIcon className="mt-0.5 size-3.5 shrink-0" />
            )}
            <span>{projectStatusDesc}</span>
          </div>
        </div>
      )}
    </>
  );
}
