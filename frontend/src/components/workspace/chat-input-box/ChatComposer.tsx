import {
  ArrowUpIcon,
  GlobeIcon,
  ImageIcon,
  LightbulbIcon,
  Loader2Icon,
  ZapIcon,
  MapIcon,
  MonitorIcon,
  PaperclipIcon,
  PlusIcon,
  ClipboardCheckIcon,
  SlidersHorizontalIcon,
  SquareIcon,
  TargetIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useMentionAutocomplete } from "../mention-autocomplete";

import { swallow } from "@/core/utils/log";
import { currentActorId } from "@/core/auth/api";
import {
  consumeComposerImageEntries,
  rememberLastComposerTarget,
} from "@/core/composer-image-inbox";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  loadComposerDraft,
  saveComposerDraft,
} from "@/core/threads/composer-draft";
import { EvolutionIndicator } from "../evolution-indicator";
import { ModelPicker, type PickerModel } from "../model-picker";
import { PartnerModelControl } from "../partner-model-control";
import { PreviewRefreshIndicator } from "../preview-refresh-indicator";
import { tryLocalSlash } from "../local-slash-dispatch";
import { useSlashTypeahead } from "../use-slash-typeahead";
import { ContextCompressor } from "../context-compressor";
import { PermissionIndicator } from "../permission-indicator";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DesktopPetMascot } from "@/components/desktop-pet";
import { usePetSettings } from "@/core/pet/pet-settings";
import { cn } from "@/lib/utils";
import { normalizePermissionMode } from "@/core/permissions";
import { uploadFiles } from "@/core/uploads";
import type { ResearchMaterial, ResearchSourceKind } from "@/core/research/api";
import {
  codexComposerModeMarker,
  parseCodexComposerModeMarker,
  type CodexComposerMode,
} from "@/core/threads/codex-composer-mode";

import type { ChatInputBoxProps } from "../chat-input-box";
import {
  DEFAULT_RESEARCH_SOURCES,
  appendReferencedFiles,
  dataUrlToFile,
  fileBasename,
  imageFileKey,
  parseComposerUrls,
  pendingFileKey,
  uploadFileKey,
  type ComposerImageInjectionDetail,
  type ComposerResearchMaterial,
  type PendingContextFile,
  type WorkspaceFileInjectionDetail,
} from "./helpers";
import { MentionPicker } from "./MentionPicker";
import { FileAttachment } from "./FileAttachment";
import { ResearchSourcePicker } from "./ResearchSourcePicker";

/**
 * The main chat composer card: textarea + file attachments + deep-research
 * picker + footer (tools menu, model picker, send/stop). Owns all the
 * draft / image / file / research state. The status strip (workdir/mode
 * selectors) is rendered separately by the parent.
 */
export function ChatComposer({
  status,
  disabled,
  modelName,
  petMood = "idle",
  showPet = true,
  mode = "react",
  threadId,
  workDir,
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
  reasoningEffort,
  partnerId,
  partnerModel,
  onPartnerModelChange,
  onPermissionModeChange,
  onReasoningEffortChange,
  onModelChange,
  onModeChange,
  onDeepResearch,
  onSubmit,
  onStop,
  isUploading = false,
  className,
}: ChatInputBoxProps) {
  const { t } = useI18n();
  const { models } = useModels();
  const petVisible = usePetSettings().visible;
  // 同步 Electron 桌面宠物（Godot sidecar）与网页内宠物：开关关闭时一并
  // 隐藏桌面窗口。浏览器环境无 window.octopus.pet，天然 no-op。
  useEffect(() => {
    if (typeof window === "undefined" || !window.octopus?.isElectron) return;
    const pet = window.octopus.pet;
    if (!pet) return;
    if (petVisible) {
      void pet.start().catch(() => {});
    } else {
      void pet.stop().catch(() => {});
    }
  }, [petVisible]);
  const [draft, setDraft] = useState(() =>
    // A per-thread draft survives thread switches and reloads. defaultValue
    // (external injection, e.g. "retry this message") wins when present.
    defaultValue || (loadComposerDraft(threadId) ?? ""),
  );
  // Restore the stored draft when the composer moves to a different thread
  // (the component is reused across navigation).
  const prevDraftThreadRef = useRef(threadId);
  useEffect(() => {
    if (prevDraftThreadRef.current === threadId) return;
    prevDraftThreadRef.current = threadId;
    setDraft(loadComposerDraft(threadId) ?? "");
  }, [threadId]);
  // Persist the draft (debounced) so a reload never loses half-typed text.
  useEffect(() => {
    const timer = setTimeout(() => saveComposerDraft(threadId, draft), 300);
    return () => clearTimeout(timer);
  }, [threadId, draft]);
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
  const submitLockRef = useRef(false);
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
  const [pendingImageSources, setPendingImageSources] = useState<
    Record<string, string>
  >({});
  const [pendingFiles, setPendingFiles] = useState<PendingContextFile[]>([]);
  const contextFileInputRef = useRef<HTMLInputElement | null>(null);

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
        // The picker folds a ``::1m`` row into its base model, which it can
        // only detect from context_profile. Dropping the field here made the
        // long-context variant render as a second, identically-labelled row.
        context_profile: (m as { context_profile?: string }).context_profile,
      })),
    [models],
  );
  const selectedModel =
    pickerModels.find((m) => m.name === modelName || m.model === modelName) ??
    (modelName
      ? { name: modelName, display_name: modelName }
      : pickerModels[0]);
  const resolvedPermissionMode = normalizePermissionMode(permissionMode);
  const canUseDeepResearch =
    allowAgentModes && mode === "deep" && !!onDeepResearch;
  const isDeepResearchMode = canUseDeepResearch && researchConfigOpen;
  const isBusy = disabled || uploadingMaterials || isUploading;
  const sendLabel = t.chatInputBox.send;
  const stopLabel = t.chatInputBox.stop;
  const parsedResearchUrls = useMemo(
    () => parseComposerUrls(researchUrlText),
    [researchUrlText],
  );
  // Only surface the context meter once it's actually filling up — showing
  // "0%" on an empty thread is just noise. Appears at ≥50% (when compressing
  // starts to matter), or while a compression is running.
  const showContextCompressor =
    maxContextTokens > 0 &&
    (isCompressingContext || contextTokens / maxContextTokens >= 0.5);
  const sendableDraftText = parseCodexComposerModeMarker(draft).text.trim();

  useEffect(() => {
    if (!canUseDeepResearch) setResearchConfigOpen(false);
  }, [canUseDeepResearch]);

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

  const addPendingWorkspaceFile = useCallback(
    (detail: WorkspaceFileInjectionDetail) => {
      const rawPath = detail.path?.trim();
      if (!rawPath) return;
      const normalizedWorkDir =
        detail.workDir?.trim() || workDir?.trim() || null;
      const nextFile: PendingContextFile = {
        id: pendingFileKey(rawPath, normalizedWorkDir),
        name: fileBasename(rawPath),
        path: rawPath,
        workDir: normalizedWorkDir,
        sourceLabel: detail.sourceLabel?.trim() || null,
      };
      setPendingFiles((current) => {
        if (current.some((file) => file.id === nextFile.id)) return current;
        return [...current, nextFile];
      });
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    },
    [workDir],
  );

  useEffect(() => {
    const handler = (event: CustomEvent<WorkspaceFileInjectionDetail>) => {
      const detail = event.detail;
      if (detail?.threadId && threadId && detail.threadId !== threadId) {
        return;
      }
      addPendingWorkspaceFile(detail ?? {});
    };
    window.addEventListener("octopus:open-file", handler as EventListener);
    return () => {
      window.removeEventListener("octopus:open-file", handler as EventListener);
    };
  }, [addPendingWorkspaceFile, threadId]);

  const handleSubmit = useCallback(async () => {
    const text = draft.trim();
    const sendableText = parseCodexComposerModeMarker(text).text.trim();
    const hasImages = pendingImages.length > 0;
    const hasFiles = pendingFiles.length > 0;
    if (
      (!sendableText && !hasImages && !hasFiles) ||
      isBusy ||
      (status === "streaming" && (hasImages || hasFiles))
    ) {
      return;
    }
    if (submitLockRef.current) return;
    submitLockRef.current = true;
    const releaseSubmitLock = () => {
      window.setTimeout(() => {
        submitLockRef.current = false;
      }, 250);
    };
    // Fast path: client-side slash commands (mode/model/permission/
    // compact/settings) resolve locally with no LLM round-trip.
    // Falls through for anything not handled here.
    if (
      tryLocalSlash(text, {
        onModeChange: onModeChange ? (mode) => onModeChange(mode) : undefined,
        // Local partners own their model namespace. Preserve `/model ...` as
        // task text so the partner adapter can translate it to that CLI's
        // one-shot model flag (or explain why the CLI cannot override it).
        onModelChange: partnerId ? undefined : onModelChange,
        onPermissionModeChange,
        onCompact: onCompressContext
          ? () => {
              void onCompressContext();
            }
          : undefined,
      })
    ) {
      setDraft("");
      releaseSubmitLock();
      return;
    }
    if (isDeepResearchMode) {
      const localFileMaterials = pendingFiles
        .filter((file) => !file.file)
        .map((file) => ({
          kind: "file" as const,
          title: file.name,
          path: file.path,
          notes: file.workDir ? `workspace: ${file.workDir}` : undefined,
        }));
      const pendingBrowserFiles = pendingFiles
        .map((file) => file.file)
        .filter((file): file is File => file instanceof File);
      let uploadedFileMaterials: Partial<ResearchMaterial>[] = [];
      if (pendingBrowserFiles.length > 0) {
        if (!threadId) {
          setMaterialError(t.chatInputBox.startThreadBeforeUpload);
          releaseSubmitLock();
          return;
        }
        setUploadingMaterials(true);
        setMaterialError(null);
        try {
          const result = await uploadFiles(threadId, pendingBrowserFiles);
          uploadedFileMaterials = result.files.map((file) => ({
            kind: "file" as const,
            title: file.filename,
            path: file.path,
            notes: `uploaded file · ${file.size} bytes`,
          }));
        } catch (err) {
          swallow(err);
          setMaterialError(t.chatInputBox.uploadFailed);
          releaseSubmitLock();
          return;
        } finally {
          setUploadingMaterials(false);
        }
      }
      let result: void | boolean;
      try {
        result = await onDeepResearch(
          appendReferencedFiles(text, pendingFiles),
          {
            urls: parsedResearchUrls,
            materials: [
              ...researchMaterials
                .filter((item) => item.enabled)
                .map((item) => item.material),
              ...localFileMaterials,
              ...uploadedFileMaterials,
            ],
            sourceKinds: researchSources,
            maxSearches,
          },
        );
      } finally {
        releaseSubmitLock();
      }
      if (result !== false) {
        setDraft("");
        setPendingFiles([]);
      }
      return;
    }
    const browserUploadFiles = pendingFiles
      .map((file) => file.file)
      .filter((file): file is File => file instanceof File);
    try {
      onSubmit?.({
        text: appendReferencedFiles(text, pendingFiles),
        images: pendingImages.length > 0 ? pendingImages : undefined,
        files: browserUploadFiles.length > 0 ? browserUploadFiles : undefined,
      });
    } finally {
      releaseSubmitLock();
    }
    setDraft("");
    if (pendingFiles.length > 0) {
      setPendingFiles([]);
      if (contextFileInputRef.current) contextFileInputRef.current.value = "";
    }
    if (pendingImages.length > 0) {
      setPendingImages([]);
      setPendingImagePreviews({});
      setPendingImageSources({});
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
    partnerId,
    onPermissionModeChange,
    onCompressContext,
    pendingImages,
    pendingFiles,
    t,
    threadId,
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
        setMaterialError(t.chatInputBox.uploadFailed);
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

  const insertCodexModeMarker = useCallback((mode: CodexComposerMode) => {
    const marker = codexComposerModeMarker(mode);
    setDraft((current) => {
      const body = current
        .replace(/^\/codex\s+(?:plan|spec|goal)(?:\s+|$)/i, "")
        .trimStart();
      return body ? `${marker}\n${body}` : `${marker}\n`;
    });
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  const insertBrowserSurfaceMarker = useCallback(
    (surface: "Browser" | "Chrome") => {
      const marker = `@${surface}`;
      setDraft((current) => {
        const body = current
          .replace(/^@(Browser|Chrome)(?:\s+|$)/i, "")
          .trimStart();
        return body ? `${marker}\n${body}` : `${marker}\n`;
      });
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    },
    [],
  );

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
    (
      files: File[] | FileList | null | undefined,
      options?: { sourceLabel?: string | null },
    ) => {
      if (!files) return;
      const arr = Array.from(files).filter((file) =>
        file.type.toLowerCase().startsWith("image/"),
      );
      if (arr.length === 0) return;
      const sourceLabel = options?.sourceLabel?.trim() || "图片";
      setPendingImages((current) => {
        const known = new Set(current.map((file) => imageFileKey(file)));
        const next = [...current];
        for (const file of arr) {
          const key = imageFileKey(file);
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
          const key = imageFileKey(file);
          if (!next[key]) next[key] = URL.createObjectURL(file);
        }
        return next;
      });
      setPendingImageSources((current) => {
        const next = { ...current };
        for (const file of arr) {
          const key = imageFileKey(file);
          if (!next[key]) next[key] = sourceLabel;
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
      const key = imageFileKey(removed);
      setPendingImagePreviews((prev) => {
        const url = prev[key];
        if (url) URL.revokeObjectURL(url);
        const { [key]: _omit, ...rest } = prev;
        return rest;
      });
      setPendingImageSources((prev) => {
        const { [key]: _omit, ...rest } = prev;
        return rest;
      });
      return current.filter((_, i) => i !== index);
    });
  }, []);

  const addPendingUploadFiles = useCallback(
    (files: File[] | FileList | null | undefined) => {
      if (!files) return;
      const arr = Array.from(files);
      if (arr.length === 0) return;
      setPendingFiles((current) => {
        const known = new Set(current.map((file) => file.id));
        const next = [...current];
        for (const file of arr) {
          const id = uploadFileKey(file);
          if (known.has(id)) continue;
          next.push({
            id,
            name: file.name || "upload.bin",
            path: file.name || "upload.bin",
            sourceLabel: "Upload",
            file,
          });
          known.add(id);
        }
        return next;
      });
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    },
    [],
  );

  const removePendingFile = useCallback((id: string) => {
    setPendingFiles((current) => current.filter((file) => file.id !== id));
  }, []);

  useEffect(() => {
    // Free any leftover object URLs when the component unmounts.
    return () => {
      setPendingImagePreviews((current) => {
        for (const url of Object.values(current)) URL.revokeObjectURL(url);
        return {};
      });
      setPendingImageSources({});
    };
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash || "";
    if (!hash.startsWith("#/workspace/realtime/")) return;
    rememberLastComposerTarget(hash);
  }, [threadId]);
  useEffect(() => {
    const queued = consumeComposerImageEntries(threadId);
    if (queued.length === 0) return;
    void Promise.all(
      queued.map(async (entry) => ({
        file: await dataUrlToFile(entry.dataUrl, entry.filename),
        sourceLabel: entry.sourceLabel?.trim() || "浏览器截图",
      })),
    ).then((entries) => {
      const files = entries
        .map((entry) => entry.file)
        .filter((file): file is File => file instanceof File);
      if (files.length === 0) return;
      addPendingImages(files, {
        sourceLabel:
          entries.find((entry) => entry.file instanceof File)?.sourceLabel ||
          "浏览器截图",
      });
    });
  }, [addPendingImages, threadId]);
  // Same recovery path for failed image-only sends: if the turn never
  // started, hand the images back to the composer so the user doesn't
  // have to paste or pick the screenshot again. We also expose the
  // same lane for future host/browser-injected screenshots.
  useEffect(() => {
    const handler = (event: CustomEvent<ComposerImageInjectionDetail>) => {
      const detail = event.detail;
      if (detail?.threadId && threadId && detail.threadId !== threadId) {
        return;
      }
      const images = Array.isArray(detail?.images)
        ? detail.images.filter((file) => file instanceof File)
        : [];
      const contextText =
        event.type === "octopus:inject-composer-images"
          ? detail?.text?.trim() || ""
          : "";
      if (images.length > 0) {
        addPendingImages(images, {
          sourceLabel: detail?.sourceLabel?.trim() || "浏览器截图",
        });
      }
      if (contextText) {
        setDraft((current) =>
          current.trim() ? `${current.trim()}\n\n${contextText}` : contextText,
        );
      }
      if (images.length === 0 && !contextText) return;
      setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener("octopus:send-failed", handler as EventListener);
    window.addEventListener(
      "octopus:inject-composer-images",
      handler as EventListener,
    );
    return () => {
      window.removeEventListener(
        "octopus:send-failed",
        handler as EventListener,
      );
      window.removeEventListener(
        "octopus:inject-composer-images",
        handler as EventListener,
      );
    };
  }, [addPendingImages, threadId]);
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
  const handleDropFiles = useCallback(
    (event: React.DragEvent<HTMLTextAreaElement>) => {
      const files = event.dataTransfer?.files;
      if (!files || files.length === 0) return;
      const dropped = Array.from(files);
      const imageFiles = dropped.filter((file) =>
        file.type.toLowerCase().startsWith("image/"),
      );
      const otherFiles = dropped.filter(
        (file) => !file.type.toLowerCase().startsWith("image/"),
      );
      if (imageFiles.length === 0 && otherFiles.length === 0) return;
      event.preventDefault();
      if (imageFiles.length > 0) addPendingImages(imageFiles);
      if (otherFiles.length > 0) addPendingUploadFiles(otherFiles);
    },
    [addPendingImages, addPendingUploadFiles],
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
    <div
      data-testid="chat-composer"
      className={cn(
        "group relative",
        "rounded-lg border border-border-default/80 bg-background/80 shadow-[var(--shadow-xs)] backdrop-blur-sm",
        "transition-[background-color,border-color,box-shadow] duration-base ease-out",
        "hover:border-border-default hover:shadow-[var(--shadow-sm)]",
        "focus-within:border-primary/25 focus-within:shadow-[0_0_0_3px_rgba(138,127,255,0.08),var(--shadow-sm)]",
        className,
      )}
    >
      {showPet && petVisible && (
        <DesktopPetMascot
          mood={petMood}
          size="sm"
          className="hidden opacity-90 transition-opacity duration-base group-focus-within:opacity-60 md:block"
          anchor={{ corner: "top-right", gap: { x: -10, y: 72 } }}
        />
      )}
      <div className="relative">
        {slashPicker}
        <MentionPicker
          isOpen={mentionOpen}
          items={mentionItems}
          selectedIndex={mentionSelectedIndex}
          isLoading={isLoadingMention}
          mentionQuery={mentionQuery}
          onSelect={selectMentionItem}
        />
      </div>
      <FileAttachment
        pendingFiles={pendingFiles}
        pendingImages={pendingImages}
        pendingImagePreviews={pendingImagePreviews}
        pendingImageSources={pendingImageSources}
        onRemoveFile={removePendingFile}
        onRemoveImage={removePendingImage}
        isUploading={isUploading}
        t={t}
      />
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
        onDrop={handleDropFiles}
        onDragOver={(e) => {
          if (e.dataTransfer?.types?.includes("Files")) e.preventDefault();
        }}
        rows={2}
        className="min-h-[52px] w-full resize-none bg-transparent px-3 py-2.5 text-sm leading-snug outline-none placeholder:text-muted-foreground/75 disabled:opacity-60 sm:min-h-0 sm:py-1.5"
      />
      {isDeepResearchMode && researchConfigOpen && (
        <ResearchSourcePicker
          researchUrlText={researchUrlText}
          setResearchUrlText={setResearchUrlText}
          researchTextTitle={researchTextTitle}
          setResearchTextTitle={setResearchTextTitle}
          researchTextBody={researchTextBody}
          setResearchTextBody={setResearchTextBody}
          researchNote={researchNote}
          setResearchNote={setResearchNote}
          researchMaterials={researchMaterials}
          researchSources={researchSources}
          maxSearches={maxSearches}
          setMaxSearches={setMaxSearches}
          uploadingMaterials={uploadingMaterials}
          materialError={materialError}
          setResearchConfigOpen={setResearchConfigOpen}
          isBusy={isBusy}
          status={status}
          t={t}
          fileInputRef={fileInputRef}
          addUrlMaterial={addUrlMaterial}
          addTextMaterial={addTextMaterial}
          toggleMaterial={toggleMaterial}
          removeMaterial={removeMaterial}
          toggleResearchSource={toggleResearchSource}
        />
      )}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => void handleUploadMaterials(event.target.files)}
      />
      <input
        ref={imageInputRef}
        type="file"
        multiple
        accept="image/*"
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          addPendingImages(event.target.files);
          if (imageInputRef.current) imageInputRef.current.value = "";
        }}
      />
      <input
        ref={contextFileInputRef}
        type="file"
        multiple
        className="hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(event) => {
          addPendingUploadFiles(event.target.files);
          if (contextFileInputRef.current) {
            contextFileInputRef.current.value = "";
          }
        }}
      />
      <div className="composer-footer flex items-center justify-between gap-2 border-t border-transparent px-2 py-1 transition-colors group-hover:border-border-subtle">
        <div className="flex items-center gap-0.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="chat-tools-trigger"
                disabled={isBusy || status === "streaming"}
                className="flex size-[42px] items-center justify-center rounded-lg text-muted-foreground/70 transition-all duration-base hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45 sm:size-8 active:scale-95"
                title={t.chatInputBox.composerInsertions}
                aria-label={t.chatInputBox.composerInsertions}
              >
                <PlusIcon className="size-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              data-testid="chat-tools-menu"
              align="start"
              side="top"
              sideOffset={8}
              className="w-60 rounded-lg border-border-default p-1.5 shadow-[var(--shadow-xs)]"
            >
              <DropdownMenuLabel className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                {t.chatInputBox.composerInsertions}
              </DropdownMenuLabel>
              <DropdownMenuItem
                data-testid="chat-insert-codex-plan"
                onSelect={() => insertCodexModeMarker("plan")}
                className="gap-2 rounded-lg text-sm"
              >
                <MapIcon className="size-4" />
                {t.chatInputBox.insertCodexPlan}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="chat-insert-codex-spec"
                onSelect={() => insertCodexModeMarker("spec")}
                className="gap-2 rounded-lg text-sm"
              >
                <ClipboardCheckIcon className="size-4" />
                {t.chatInputBox.insertCodexSpec}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="chat-insert-codex-goal"
                onSelect={() => insertCodexModeMarker("goal")}
                className="gap-2 rounded-lg text-sm"
              >
                <TargetIcon className="size-4" />
                {t.chatInputBox.insertCodexGoal}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="chat-insert-browser-surface"
                onSelect={() => insertBrowserSurfaceMarker("Browser")}
                className="gap-2 rounded-lg text-sm"
              >
                <MonitorIcon className="size-4" />
                {t.chatInputBox.insertBrowserSurface}
              </DropdownMenuItem>
              <DropdownMenuItem
                data-testid="chat-insert-chrome-surface"
                onSelect={() => insertBrowserSurfaceMarker("Chrome")}
                className="gap-2 rounded-lg text-sm"
              >
                <GlobeIcon className="size-4" />
                {t.chatInputBox.insertChromeSurface}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              {canUseDeepResearch && (
                <>
                  <DropdownMenuItem
                    onSelect={() => setResearchConfigOpen((open) => !open)}
                    className="gap-2 rounded-lg text-sm"
                  >
                    <SlidersHorizontalIcon className="size-4" />
                    {t.chatInputBox.deepResearchConfig}
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                </>
              )}
              {allowAgentModes && (
                <DropdownMenuItem
                  onSelect={openResearchFilePicker}
                  className="gap-2 rounded-lg text-sm"
                >
                  <PaperclipIcon className="size-4" />
                  {t.chatInputBox.addResearchMaterial}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onSelect={() => contextFileInputRef.current?.click()}
                className="gap-2 rounded-lg text-sm"
              >
                <PaperclipIcon className="size-4" />
                {t.chatInputBox.file}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => imageInputRef.current?.click()}
                className="gap-2 rounded-lg text-sm"
              >
                <ImageIcon className="size-4" />
                {t.chatInputBox.addImage}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <PreviewRefreshIndicator />
          <PermissionIndicator
            mode={resolvedPermissionMode}
            onModeChange={(nextMode) => onPermissionModeChange?.(nextMode)}
            compact
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
        <div className="flex items-center gap-1">
          {showInspirationToggle && (
            <button
              type="button"
              data-testid="chat-mode-toggle"
              disabled={disabled || status === "streaming"}
              onClick={() =>
                onModeChange?.(mode === "chat" ? "react" : "chat", draft)
              }
              className={cn(
                "flex size-[42px] items-center justify-center rounded-lg text-xs font-medium transition-all duration-base sm:size-8",
                mode === "chat"
                  ? "bg-primary/10 text-primary hover:bg-primary/15"
                  : "border border-transparent text-muted-foreground hover:border-border-default hover:bg-muted/60 hover:text-foreground",
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
          <EvolutionIndicator compact quiet />
          {partnerId ? (
            // Local CLI partner: its model comes from the CLI's own config,
            // not the Octopus picker (which would show a misleading "mimo…").
            <PartnerModelControl
              partnerId={partnerId}
              value={partnerModel}
              onChange={(m) => onPartnerModelChange?.(m)}
            />
          ) : (
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
          )}
          {status === "streaming" && sendableDraftText ? (
            <>
              <button
                type="button"
                onClick={handleSubmit}
                data-testid="chat-steer-button"
                className="flex size-[42px] items-center justify-center rounded-lg bg-foreground text-background transition-all duration-base hover:bg-foreground/90 active:scale-95 sm:size-8"
                title={sendLabel}
                aria-label={sendLabel}
              >
                <ArrowUpIcon className="size-3.5" />
              </button>
              <button
                type="button"
                onClick={onStop}
                className="flex size-[42px] items-center justify-center rounded-lg border border-border bg-muted/60 text-muted-foreground transition-all duration-base hover:border-destructive/25 hover:bg-destructive/10 hover:text-destructive active:scale-95 sm:size-8"
                title={stopLabel}
                aria-label={stopLabel}
              >
                <SquareIcon className="size-3" fill="currentColor" />
              </button>
            </>
          ) : status === "streaming" ? (
            <button
              type="button"
              onClick={onStop}
              className="flex size-[42px] items-center justify-center rounded-lg border border-border bg-muted/60 text-muted-foreground transition-all duration-base hover:border-destructive/25 hover:bg-destructive/10 hover:text-destructive active:scale-95 sm:size-8"
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
              disabled={
                (!sendableDraftText &&
                  pendingImages.length === 0 &&
                  pendingFiles.length === 0) ||
                isBusy
              }
              className={cn(
                "flex size-[42px] items-center justify-center rounded-lg transition-all duration-base sm:size-8",
                isDeepResearchMode
                  ? "bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95"
                  : "bg-foreground text-background hover:bg-foreground/90 active:scale-95",
                "disabled:bg-transparent disabled:text-muted-foreground/50 disabled:cursor-not-allowed disabled:hover:bg-muted/60 disabled:hover:text-muted-foreground",
              )}
              title={sendLabel}
              aria-label={sendLabel}
            >
              {isBusy ? (
                <Loader2Icon className="size-3.5 animate-spin" />
              ) : (
                <ArrowUpIcon className="size-3.5" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
