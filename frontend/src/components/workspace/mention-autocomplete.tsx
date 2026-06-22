/**
 * Mention Autocomplete — @ context references in chat input.
 *
 * Provides a dropdown that appears when the user types "@" in the chat input,
 * with categories for files, symbols, docs, web, git, folders, and terminal.
 *
 * Features:
 * - Trigger: typing "@" at word boundary
 * - Category browsing: shows all categories when no filter typed
 * - Type-specific search: "@file:main" searches files, "@symbol:My" searches symbols
 * - Fuzzy matching on partial input after @
 * - Keyboard navigation (ArrowUp/Down, Enter to select, Escape to close, Tab to complete)
 * - Selected mentions inserted as @type:reference tokens
 * - Debounced API calls for responsive autocomplete
 */

import { swallow } from "@/core/utils/log";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  BookOpenIcon,
  BotIcon,
  BracesIcon,
  DatabaseIcon,
  FileIcon,
  FolderIcon,
  GitBranchIcon,
  GlobeIcon,
  Loader2Icon,
  PackageIcon,
  PuzzleIcon,
  TerminalIcon,
  ZapIcon,
} from "lucide-react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";

import { cn } from "@/lib/utils";

// ============================================================================
// Types
// ============================================================================

export interface MentionItem {
  type: string;
  label: string;
  value: string;
  description: string;
  icon: string;
}

export type MentionCategory =
  | "file"
  | "symbol"
  | "folder"
  | "git"
  | "docs"
  | "web"
  | "terminal"
  | "agent"
  | "plugin"
  | "skill"
  | "pack";

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  file: FileIcon,
  symbol: BracesIcon,
  folder: FolderIcon,
  "git-branch": GitBranchIcon,
  "git-commit": GitBranchIcon,
  book: BookOpenIcon,
  globe: GlobeIcon,
  terminal: TerminalIcon,
  braces: BracesIcon,
  agent: BotIcon,
  plugin: PuzzleIcon,
  skill: ZapIcon,
  pack: PackageIcon,
  database: DatabaseIcon,
};

const CATEGORY_COLORS: Record<string, string> = {
  file: "text-blue-500",
  symbol: "text-purple-500",
  folder: "text-amber-500",
  git: "text-orange-500",
  docs: "text-green-500",
  web: "text-cyan-500",
  terminal: "text-zinc-400",
  agent: "text-indigo-500",
  plugin: "text-fuchsia-500",
  skill: "text-yellow-500",
  pack: "text-pink-500",
  database: "text-emerald-600",
};

const LOCAL_FILE_AGENT_MENTION: MentionItem = {
  type: "agent",
  label: "本地数据库",
  value: "本地数据库",
  description: "只在本机索引和检索授权资料，确认后再带入任务上下文",
  icon: "database",
};

function withLocalFileAgentMention(
  query: string,
  results: MentionItem[],
): MentionItem[] {
  const normalized = query.trim().toLowerCase();
  const shouldShow =
    normalized === "" ||
    "本地数据库".includes(normalized) ||
    "私域资料库".includes(normalized) ||
    "本地资料官".includes(normalized) ||
    "local database".includes(normalized) ||
    "private storage".includes(normalized) ||
    "local file agent".includes(normalized) ||
    "nas".includes(normalized) ||
    "storage".includes(normalized) ||
    normalized === "agent:" ||
    normalized.startsWith("agent:本地数据库") ||
    normalized.startsWith("agent:私域") ||
    normalized.startsWith("agent:本地") ||
    normalized.startsWith("agent:local");
  if (!shouldShow) return results;
  if (results.some((item) => item.value === LOCAL_FILE_AGENT_MENTION.value)) {
    return results;
  }
  return [LOCAL_FILE_AGENT_MENTION, ...results];
}

/** A team member offered by the @ typeahead (group roster). */
export interface MentionMemberInput {
  name: string;
  display_name?: string | null;
  icon?: string | null;
  description?: string | null;
}

/** Prepend matching group members so typing "@" in a team room summons the
 * roster inline — no hard button needed. */
function withMemberMentions(
  query: string,
  members: MentionMemberInput[],
  results: MentionItem[],
): MentionItem[] {
  if (!members.length) return results;
  const q = query.trim().toLowerCase();
  const existing = new Set(results.map((r) => r.value));
  const matched: MentionItem[] = members
    .filter((m) => {
      const dn = (m.display_name ?? m.name).toLowerCase();
      return (
        q === "" ||
        q === "agent:" ||
        dn.includes(q) ||
        m.name.toLowerCase().includes(q) ||
        q.startsWith(`agent:${dn}`)
      );
    })
    .map((m) => {
      const label = m.display_name ?? m.name;
      return {
        type: "agent",
        label,
        value: label,
        description: m.description || "群成员",
        icon: m.icon?.trim() || "bot",
      };
    })
    .filter((m) => !existing.has(m.value));
  return [...matched, ...results];
}

// ============================================================================
// API
// ============================================================================

const BASE_URL = getBackendBaseURL();

async function fetchMentionAutocomplete(
  query: string,
  workspace: string,
  signal?: AbortSignal,
  threadId?: string,
  actor?: string,
): Promise<MentionItem[]> {
  const params = new URLSearchParams({
    q: query,
    workspace,
    limit: "20",
  });
  if (threadId) params.set("thread_id", threadId);
  if (actor) params.set("actor", actor);
  try {
    const res = await fetch(`${BASE_URL}/api/mentions/autocomplete?${params}`, {
      signal,
    });
    if (!res.ok) return [];
    const data = await res.json();
    return data.items ?? [];
  } catch (e) {
    swallow(e);
    return [];
  }
}

// ============================================================================
// Hook: useMentionAutocomplete
// ============================================================================

interface UseMentionAutocompleteOptions {
  value: string;
  onChange: (value: string) => void;
  workDir?: string;
  threadId?: string;
  actor?: string;
  /** Group members offered first when typing "@" in a team room. */
  members?: MentionMemberInput[];
  /** Debounce delay in ms for API calls. Default 150. */
  debounceMs?: number;
}

export function useMentionAutocomplete({
  value,
  onChange,
  workDir,
  threadId,
  actor,
  members,
  debounceMs = 150,
}: UseMentionAutocompleteOptions) {
  // Stable handle to the latest roster so the fetch effect can read it
  // without re-running on every render (members is a fresh array each time).
  const membersRef = useRef<MentionMemberInput[]>(members ?? []);
  membersRef.current = members ?? [];
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [items, setItems] = useState<MentionItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");

  // Track the position of the @ trigger in the input value
  const triggerPosRef = useRef(-1);
  const abortRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- Detect @ trigger and extract query ----
  useEffect(() => {
    if (!isOpen) return;

    const atPos = triggerPosRef.current;
    if (atPos < 0 || atPos >= value.length) {
      setIsOpen(false);
      setMentionQuery("");
      return;
    }

    // Check that the @ is still at the trigger position
    if (value[atPos] !== "@") {
      setIsOpen(false);
      setMentionQuery("");
      return;
    }

    // Extract query: everything after @ until whitespace or end
    // But for @web: queries, allow spaces (handle specially in the parser)
    const afterAt = value.slice(atPos + 1);

    // If the user typed a newline after @, close
    if (afterAt.includes("\n")) {
      setIsOpen(false);
      setMentionQuery("");
      return;
    }

    // For typed mention with colon (e.g., "@file:main"), pass the whole thing
    // For category-level (e.g., "@fi"), just pass the partial
    const colonIdx = afterAt.indexOf(":");
    if (colonIdx !== -1) {
      // Has a type prefix — allow the full typed text as the query
      const typeStr = afterAt.slice(0, colonIdx);
      const validTypes = [
        "file",
        "symbol",
        "folder",
        "git",
        "docs",
        "web",
        "terminal",
        "agent",
        "plugin",
        "skill",
        "pack",
      ];
      if (validTypes.includes(typeStr.toLowerCase())) {
        // For @web: allow spaces in the query
        if (
          typeStr.toLowerCase() === "web" ||
          typeStr.toLowerCase() === "docs"
        ) {
          setMentionQuery(afterAt);
        } else {
          // For other types, stop at first space after colon
          const afterColon = afterAt.slice(colonIdx + 1);
          const spaceIdx = afterColon.indexOf(" ");
          if (spaceIdx !== -1) {
            // User moved past the mention — close it
            setIsOpen(false);
            setMentionQuery("");
            return;
          }
          setMentionQuery(afterAt);
        }
      } else {
        // Not a valid type — treat as category filter
        const spaceIdx = afterAt.indexOf(" ");
        if (spaceIdx !== -1) {
          setIsOpen(false);
          setMentionQuery("");
          return;
        }
        setMentionQuery(afterAt);
      }
    } else {
      // No colon yet — partial category name like "fi"
      const spaceIdx = afterAt.indexOf(" ");
      if (spaceIdx !== -1) {
        setIsOpen(false);
        setMentionQuery("");
        return;
      }
      setMentionQuery(afterAt);
    }
  }, [value, isOpen]);

  // ---- Fetch autocomplete results (debounced) ----
  useEffect(() => {
    if (!isOpen) {
      setItems([]);
      return;
    }

    // Cancel previous request
    abortRef.current?.abort();
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }

    setIsLoading(true);

    debounceTimerRef.current = setTimeout(() => {
      const controller = new AbortController();
      abortRef.current = controller;

      fetchMentionAutocomplete(
        mentionQuery,
        workDir || ".",
        controller.signal,
        threadId,
        actor,
      )
        .then((results) => {
          if (!controller.signal.aborted) {
            setItems(
              withMemberMentions(
                mentionQuery,
                membersRef.current,
                withLocalFileAgentMention(mentionQuery, results),
              ),
            );
            setSelectedIndex(0);
            setIsLoading(false);
          }
        })
        .catch(() => {
          if (!controller.signal.aborted) {
            // Members still resolve locally even if the backend mention API
            // is unreachable.
            setItems(withMemberMentions(mentionQuery, membersRef.current, []));
            setIsLoading(false);
          }
        });
    }, debounceMs);

    return () => {
      abortRef.current?.abort();
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, [isOpen, mentionQuery, workDir, threadId, actor, debounceMs]);

  // ---- Reset selected index when items change ----
  useEffect(() => {
    setSelectedIndex(0);
  }, [items]);

  // ---- Select an item ----
  const selectItem = useCallback(
    (item: MentionItem) => {
      const atPos = triggerPosRef.current;
      if (atPos < 0) return;

      // Build the mention text to insert
      const mentionText = `@${item.value} `;

      // Replace from @ to current cursor position
      const before = value.slice(0, atPos);
      // Find the end of the current mention text
      const afterAt = value.slice(atPos + 1);
      let endOffset = afterAt.length;

      // Find where the mention query ends
      const colonIdx = afterAt.indexOf(":");
      if (colonIdx !== -1) {
        const typeStr = afterAt.slice(0, colonIdx).toLowerCase();
        if (typeStr === "web" || typeStr === "docs") {
          // For web/docs, consume to end of line or next @ mention
          const lineEnd = afterAt.indexOf("\n");
          endOffset = lineEnd !== -1 ? lineEnd : afterAt.length;
        } else {
          const afterColon = afterAt.slice(colonIdx + 1);
          const spaceIdx = afterColon.indexOf(" ");
          endOffset =
            spaceIdx !== -1 ? colonIdx + 1 + spaceIdx : afterAt.length;
        }
      } else {
        const spaceIdx = afterAt.indexOf(" ");
        endOffset = spaceIdx !== -1 ? spaceIdx : afterAt.length;
      }

      const after = value.slice(atPos + 1 + endOffset);
      onChange(before + mentionText + after);

      setIsOpen(false);
      setMentionQuery("");
      triggerPosRef.current = -1;
    },
    [value, onChange],
  );

  // ---- Keyboard handler ----
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      // Detect @ trigger to open the autocomplete
      if (!isOpen) {
        if (e.key === "@" && !e.ctrlKey && !e.metaKey) {
          const pos = e.currentTarget.selectionStart;
          const charBefore = pos > 0 ? value[pos - 1] : undefined;
          // Only trigger if @ is at start or after whitespace
          if (
            charBefore === undefined ||
            charBefore === " " ||
            charBefore === "\n" ||
            charBefore === "\t" ||
            pos === 0
          ) {
            triggerPosRef.current = pos;
            setIsOpen(true);
            setMentionQuery("");
            setItems([]);
          }
        }
        return;
      }

      // Handle navigation within open dropdown
      if (items.length === 0 && !isLoading) {
        // Nothing to navigate — let default behavior through
        if (e.key === "Escape") {
          e.preventDefault();
          setIsOpen(false);
          return;
        }
        return;
      }

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((i) =>
            items.length > 0 ? (i + 1) % items.length : 0,
          );
          break;

        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((i) =>
            items.length > 0 ? (i - 1 + items.length) % items.length : 0,
          );
          break;

        case "Enter":
          if (items.length > 0 && !e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
            const item = items[selectedIndex];
            if (item) {
              // If item is a category (value ends with ":"), append it to the query
              if (item.value.endsWith(":")) {
                // Replace current text after @ with the category prefix
                const atPos = triggerPosRef.current;
                if (atPos >= 0) {
                  const before = value.slice(0, atPos + 1);
                  // Find end of current query
                  const afterAt = value.slice(atPos + 1);
                  const spaceIdx = afterAt.indexOf(" ");
                  const after = spaceIdx !== -1 ? afterAt.slice(spaceIdx) : "";
                  onChange(before + item.value + after);
                  // Don't close — let the user continue typing
                  setMentionQuery(item.value);
                }
              } else {
                selectItem(item);
              }
            }
          }
          break;

        case "Tab":
          if (items.length > 0) {
            e.preventDefault();
            const item = items[selectedIndex];
            if (item) {
              if (item.value.endsWith(":")) {
                const atPos = triggerPosRef.current;
                if (atPos >= 0) {
                  const before = value.slice(0, atPos + 1);
                  const afterAt = value.slice(atPos + 1);
                  const spaceIdx = afterAt.indexOf(" ");
                  const after = spaceIdx !== -1 ? afterAt.slice(spaceIdx) : "";
                  onChange(before + item.value + after);
                  setMentionQuery(item.value);
                }
              } else {
                selectItem(item);
              }
            }
          }
          break;

        case "Escape":
          e.preventDefault();
          setIsOpen(false);
          setMentionQuery("");
          break;

        case "Backspace": {
          // If we've deleted back to before the @, close
          const pos = e.currentTarget.selectionStart;
          if (pos !== null && pos <= triggerPosRef.current) {
            setIsOpen(false);
            setMentionQuery("");
          }
          break;
        }
      }
    },
    [isOpen, items, selectedIndex, isLoading, value, onChange, selectItem],
  );

  return {
    isOpen,
    items,
    selectedIndex,
    isLoading,
    mentionQuery,
    handleKeyDown,
    selectItem,
    close: useCallback(() => {
      setIsOpen(false);
      setMentionQuery("");
    }, []),
  };
}

// ============================================================================
// Popup Component
// ============================================================================

interface MentionAutocompletePopupProps {
  items: MentionItem[];
  selectedIndex: number;
  isLoading?: boolean;
  mentionQuery?: string;
  onSelect?: (item: MentionItem) => void;
  className?: string;
}

export function MentionAutocompletePopup({
  items,
  selectedIndex,
  isLoading,
  mentionQuery,
  onSelect,
  className,
}: MentionAutocompletePopupProps) {
  const { t } = useI18n();
  const listRef = useRef<HTMLDivElement>(null);

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const selected = listRef.current.querySelector(
      `[data-mention-index="${selectedIndex}"]`,
    );
    if (selected) {
      selected.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  if (!isLoading && items.length === 0 && !mentionQuery) {
    return null;
  }

  return (
    <div
      className={cn(
        "bg-popover text-popover-foreground absolute bottom-full left-0 z-50 mb-1 w-80 overflow-hidden rounded-lg border shadow-lg",
        className,
      )}
    >
      {/* Header */}
      <div className="border-b px-3 py-1.5">
        <div className="text-muted-foreground flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider">
          <span>@</span>
          <span>{t.mentions.mentions}</span>
          {mentionQuery && (
            <>
              <span className="text-muted-foreground/40">|</span>
              <span className="text-foreground/70 normal-case tracking-normal font-normal">
                {mentionQuery}
              </span>
            </>
          )}
        </div>
      </div>

      {/* Items */}
      <div ref={listRef} className="max-h-72 overflow-y-auto p-1">
        {isLoading && items.length === 0 ? (
          <div className="text-muted-foreground flex items-center justify-center gap-2 py-4 text-xs">
            <Loader2Icon className="size-3.5 animate-spin" />
            <span>{t.mentions.searching}</span>
          </div>
        ) : items.length === 0 ? (
          <div className="text-muted-foreground py-4 text-center text-xs">
            {t.mentions.noResults}
          </div>
        ) : (
          items.map((item, index) => {
            const IconComponent =
              CATEGORY_ICONS[item.icon] ||
              CATEGORY_ICONS[item.type] ||
              FileIcon;
            const colorClass =
              CATEGORY_COLORS[item.type] || "text-muted-foreground";
            const isSelected = index === selectedIndex;

            return (
              <button
                key={`${item.type}-${item.value}-${index}`}
                data-mention-index={index}
                className={cn(
                  "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors",
                  isSelected
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-accent/50",
                )}
                onClick={() => onSelect?.(item)}
                onMouseEnter={() => {
                  // We don't set selectedIndex on hover to avoid conflicts
                  // with keyboard navigation
                }}
              >
                <div
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded",
                    isSelected ? "bg-accent-foreground/10" : "bg-muted",
                  )}
                >
                  <IconComponent className={cn("size-3.5", colorClass)} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-[13px] leading-tight">
                    {item.label}
                  </div>
                  {item.description && (
                    <div className="text-muted-foreground truncate text-[11px] leading-tight">
                      {item.description}
                    </div>
                  )}
                </div>
                {item.value.endsWith(":") && (
                  <div className="text-muted-foreground/50 text-[10px]">
                    &rsaquo;
                  </div>
                )}
              </button>
            );
          })
        )}
      </div>

      {/* Footer hint */}
      <div className="border-t px-3 py-1">
        <div className="text-muted-foreground/60 flex items-center gap-3 text-[10px]">
          <span>
            <kbd className="bg-muted rounded px-1 font-mono text-[9px]">
              &uarr;&darr;
            </kbd>{" "}
            {t.mentions.navigate}
          </span>
          <span>
            <kbd className="bg-muted rounded px-1 font-mono text-[9px]">
              Tab
            </kbd>{" "}
            {t.mentions.select}
          </span>
          <span>
            <kbd className="bg-muted rounded px-1 font-mono text-[9px]">
              Esc
            </kbd>{" "}
            {t.mentions.close}
          </span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Mention Badge (inline chip for rendered mentions in messages)
// ============================================================================

interface MentionBadgeProps {
  type: MentionCategory;
  reference: string;
  className?: string;
}

export function MentionBadge({
  type,
  reference,
  className,
}: MentionBadgeProps) {
  const IconComponent =
    CATEGORY_ICONS[type] || CATEGORY_ICONS[type] || FileIcon;
  const colorClass = CATEGORY_COLORS[type] || "text-muted-foreground";

  return (
    <span
      className={cn(
        "bg-accent/60 text-accent-foreground inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-xs font-medium",
        className,
      )}
    >
      <IconComponent className={cn("size-3", colorClass)} />
      <span className="max-w-[200px] truncate">{reference}</span>
    </span>
  );
}

// ============================================================================
// Backward-compatible exports (re-export as the old file-mention interface)
// ============================================================================

/**
 * Legacy interface — the old `useFileMention` hook is now powered by
 * the full mention autocomplete. This wrapper maintains backward
 * compatibility with existing consumers.
 */
export function useFileMention({
  value,
  onChange,
  workDir,
}: {
  value: string;
  onChange: (value: string) => void;
  workDir?: string;
}) {
  const { isOpen, items, selectedIndex, isLoading, handleKeyDown } =
    useMentionAutocomplete({ value, onChange, workDir });

  // Map items to the old FileEntry shape for the popup
  const filteredFiles = useMemo(
    () =>
      items.map((item) => ({
        name: item.label,
        path: item.description || item.value,
        type: (item.type === "folder" ? "dir" : "file") as "file" | "dir",
      })),
    [items],
  );

  return {
    isOpen,
    filteredFiles,
    selectedIndex,
    isLoading,
    handleKeyDown,
  };
}
