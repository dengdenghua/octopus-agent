import { useCallback, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  MessageSquareIcon,
  MessageSquarePlusIcon,
  MoreHorizontalIcon,
  PencilIcon,
  SearchIcon,
  SettingsIcon,
  Trash2Icon,
} from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { emitAgentChanged, eventBus } from "@/core/events";
import { useI18n } from "@/core/i18n/hooks";
import {
  useDeleteThread,
  useRenameThread,
  useThreads,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import { formatCompactRelativeTimestamp } from "@/core/utils/datetime";
import { uuid } from "@/core/utils/uuid";
import { activeWorkspaceThreadIdFromPathname } from "@/core/threads/sidebar";
import { isIMEComposing } from "@/lib/ime";
import { isAbsolutePath } from "@/lib/path-utils";
import { cn } from "@/lib/utils";

const DRAWER_WIDTH = "min(320px, 86vw)";

/* Implementation note. */
function deriveTitle(thread: AgentThread): string {
  const meta = (thread.metadata ?? {}) as Record<string, unknown>;
  const metaTitle =
    typeof meta["title"] === "string" ? (meta["title"] as string).trim() : "";
  if (metaTitle) {
    return metaTitle.length > 60 ? `${metaTitle.slice(0, 58)}...` : metaTitle;
  }
  const values = (thread.values ?? {}) as Record<string, unknown>;
  const valuesTitle =
    typeof values["title"] === "string"
      ? (values["title"] as string).trim()
      : "";
  if (valuesTitle && valuesTitle !== "New chat" && valuesTitle !== "New task") {
    return valuesTitle.length > 60
      ? `${valuesTitle.slice(0, 58)}...`
      : valuesTitle;
  }
  const messages = values["messages"];
  if (Array.isArray(messages)) {
    for (const m of messages) {
      if (
        m &&
        typeof m === "object" &&
        (m as Record<string, unknown>).type === "human"
      ) {
        const content = (m as Record<string, unknown>).content;
        const text =
          typeof content === "string"
            ? content.replace(/\s+/g, " ").trim()
            : "";
        if (text) {
          return text.length > 60 ? `${text.slice(0, 58)}...` : text;
        }
      }
    }
  }
  return `对话/${thread.thread_id.slice(0, 6)}`;
}

function threadHref(thread: AgentThread): string {
  return `/workspace/realtime/${encodeURIComponent(thread.thread_id)}`;
}

function threadOwnerAgent(thread: AgentThread): string {
  const meta = (thread.metadata ?? {}) as Record<string, unknown>;
  const values = (thread.values ?? {}) as Record<string, unknown>;
  const candidates = [
    meta["agent"],
    meta["agent_name"],
    meta["agent_id"],
    meta["lead_agent_name"],
    meta["current_agent"],
    values["current_speaker"],
    values["agent_name"],
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function threadWorkspacePath(thread?: AgentThread): string {
  const meta = (thread?.metadata ?? {}) as Record<string, unknown>;
  const values = (thread?.values ?? {}) as Record<string, unknown>;
  const path = meta["workspace_path"] ?? values["workspace_path"];
  return typeof path === "string" ? path.trim() : "";
}

interface ChatsDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ChatsDrawer({ open, onOpenChange }: ChatsDrawerProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const deleteThread = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const [query, setQuery] = useState("");
  const { confirm, confirmDialog } = useConfirmDialog();
  const [threadToRename, setThreadToRename] = useState<AgentThread | null>(
    null,
  );
  const [renameValue, setRenameValue] = useState("");

  const handleRenameSubmit = useCallback(() => {
    if (threadToRename && renameValue.trim()) {
      renameThread({
        threadId: threadToRename.thread_id,
        title: renameValue.trim(),
      });
      setThreadToRename(null);
      setRenameValue("");
    }
  }, [renameThread, threadToRename, renameValue]);

  // The drawer is the global history surface, so it should not follow
  // the footer agent filter.
  const { data: threads = [] } = useThreads(
    {
      limit: 50,
      sortBy: "updated_at",
      sortOrder: "desc",
      select: ["thread_id", "updated_at", "values", "metadata"],
    },
    undefined,
    null,
  );

  const filteredThreads = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter((t) => deriveTitle(t).toLowerCase().includes(q));
  }, [threads, query]);

  const startNewChat = useCallback(() => {
    onOpenChange(false);
    const activeId = activeWorkspaceThreadIdFromPathname(pathname);
    const activeThread = activeId
      ? threads.find((thread) => thread.thread_id === activeId)
      : undefined;
    const routeWorkspacePath =
      new URLSearchParams(search).get("workspace_path") ?? "";
    const threadPath = threadWorkspacePath(activeThread);
    const workspacePath = isAbsolutePath(threadPath)
      ? threadPath
      : isAbsolutePath(routeWorkspacePath)
        ? routeWorkspacePath
        : undefined;
    eventBus.emit("task:new", {
      agentId: activeThread
        ? threadOwnerAgent(activeThread) || undefined
        : undefined,
      workspacePath,
    });
  }, [onOpenChange, pathname, search, threads]);

  const openSettings = useCallback(() => {
    onOpenChange(false);
    // Let the sheet release its modal focus/aria guards before opening the
    // settings dialog. Opening both in the same event turn causes Radix to
    // immediately dismiss the second surface on narrow screens.
    window.setTimeout(() => {
      window.dispatchEvent(new Event("octopus:open-settings"));
    }, 0);
  }, [onOpenChange]);

  const handleDelete = useCallback(
    async (thread: AgentThread) => {
      const ok = await confirm({
        title: t.sidebar.deleteThreadTooltip,
        description: t.sidebar.confirmDeleteThread(deriveTitle(thread)),
      });
      if (!ok) return;
      deleteThread.mutate({ threadId: thread.thread_id });
      if (pathname === threadHref(thread)) {
        navigate(`/workspace/realtime/${uuid()}`, { replace: true });
      }
    },
    [confirm, deleteThread, navigate, pathname, t],
  );

  return (
    <>
      <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="left"
        className={cn(
          "gap-0 p-0",
          "data-[state=open]:duration-300 data-[state=closed]:duration-200",
        )}
        style={{ width: DRAWER_WIDTH, maxWidth: DRAWER_WIDTH }}
      >
        <SheetHeader className="border-b border-border-subtle px-4 py-3 pr-12">
          <SheetTitle className="text-sm font-semibold">
            {t.sidebar.sectionChats}
          </SheetTitle>
          <SheetDescription className="sr-only">
            {t.sidebar.sectionChats}
          </SheetDescription>
        </SheetHeader>

        <div className="flex flex-col gap-2 px-3 pt-3">
          <button
            type="button"
            onClick={startNewChat}
            className={cn(
              "group flex h-9 w-full items-center justify-center gap-2",
              "border border-primary/30 bg-primary/8 text-[13px] font-medium text-primary",
              "transition-colors hover:bg-primary/14 active:scale-[0.99]",
            )}
          >
            <MessageSquarePlusIcon className="size-4" />
            {t.sidebar.actionNewTask}
          </button>

          <div className="relative">
            <SearchIcon className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground/70" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.sidebar.searchChats}
              className="h-8 pl-8 text-[12.5px]"
            />
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between px-4 text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
          <span className="flex items-center gap-1.5">
            <MessageSquareIcon className="size-3" />
            {t.sidebar.recentChats}
          </span>
          <span className="text-[10px] text-muted-foreground/55">
            {filteredThreads.length}
          </span>
        </div>

        <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2 pb-3">
          {filteredThreads.length === 0 ? (
            <div className="mt-4 rounded-md border border-dashed border-border-default px-3 py-4 text-center text-[12px] text-muted-foreground/75">
              {query.trim() ? t.sidebar.noMatchingChats : t.sidebar.noChatsYet}
            </div>
          ) : (
            <ul className="flex flex-col gap-px">
              {filteredThreads.map((thread) => {
                const href = threadHref(thread);
                const active =
                  activeWorkspaceThreadIdFromPathname(pathname) ===
                  thread.thread_id;
                return (
                  <li key={thread.thread_id} className="group/thread relative">
                    <Link
                      to={href}
                      state={{
                        threadOwnerAgentId:
                          threadOwnerAgent(thread) || undefined,
                        workspacePath: threadWorkspacePath(thread) || undefined,
                      }}
                      onMouseDown={() => {
                        const owner = threadOwnerAgent(thread);
                        if (owner) emitAgentChanged(owner, "thread");
                      }}
                      onClick={() => onOpenChange(false)}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex min-h-9 items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] transition-colors",
                        "hover:bg-muted/55",
                        active &&
                          "bg-[color:color-mix(in_oklch,var(--sidebar-accent)_55%,transparent)] font-medium",
                      )}
                    >
                      <span className="min-w-0 flex-1 truncate leading-tight">
                        {deriveTitle(thread)}
                      </span>
                      <span
                        className={cn(
                          "w-10 shrink-0 overflow-hidden whitespace-nowrap text-right text-[10px] text-muted-foreground/65",
                          "transition-[width,opacity] group-hover/thread:w-0 group-hover/thread:opacity-0",
                        )}
                      >
                        {formatCompactRelativeTimestamp(thread.updated_at)}
                      </span>
                    </Link>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          title={t.common.more}
                          aria-label={t.common.more}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                          }}
                          className={cn(
                            "absolute right-1 top-1/2 -translate-y-1/2 flex size-5 items-center justify-center rounded-md",
                            "text-muted-foreground/60 opacity-0 transition-opacity",
                            "hover:bg-muted/60 hover:text-foreground",
                            "group-hover/thread:opacity-100 data-[state=open]:opacity-100",
                          )}
                        >
                          <MoreHorizontalIcon className="size-3.5" />
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" side="right">
                        <DropdownMenuItem
                          onSelect={() => {
                            setThreadToRename(thread);
                            setRenameValue(deriveTitle(thread));
                          }}
                        >
                          <PencilIcon className="text-muted-foreground" />
                          <span>{t.common.rename}</span>
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={deleteThread.isPending}
                          onSelect={() => void handleDelete(thread)}
                        >
                          <Trash2Icon className="text-muted-foreground" />
                          <span>{t.sidebar.deleteThreadTooltip}</span>
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t border-border-subtle p-2">
          <button
            type="button"
            onClick={openSettings}
            className="flex h-9 w-full items-center gap-2 rounded-md px-2.5 text-[12.5px] font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
          >
            <SettingsIcon className="size-4" />
            {t.common.settings}
          </button>
        </div>
      </SheetContent>
      </Sheet>
      <Dialog
        open={threadToRename !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setThreadToRename(null);
            setRenameValue("");
          }
        }}
      >
        <DialogContent
          showCloseButton={false}
          className="w-[min(360px,calc(100vw-2rem))] gap-3 rounded-lg p-4 sm:max-w-[360px]"
        >
          <DialogHeader className="gap-1 text-left">
            <DialogTitle className="text-[15px]">
              {t.common.rename}
            </DialogTitle>
          </DialogHeader>
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isIMEComposing(e)) {
                e.preventDefault();
                handleRenameSubmit();
              }
            }}
            autoFocus
            className="h-8 text-[13px]"
          />
          <DialogFooter className="mt-1 flex-row justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                setThreadToRename(null);
                setRenameValue("");
              }}
            >
              {t.common.cancel}
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={!renameValue.trim()}
              onClick={handleRenameSubmit}
            >
              {t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {confirmDialog}
    </>
  );
}
