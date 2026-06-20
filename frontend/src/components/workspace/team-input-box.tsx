import type { ChatStatus } from "ai";
import {
  ArrowUpIcon,
  ChevronDownIcon,
  DatabaseIcon,
  SquareIcon,
  MessageCircleIcon,
  UserCircleIcon,
  UsersIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import {
  MentionAutocompletePopup,
  useMentionAutocomplete,
} from "./mention-autocomplete";
import { ModelPicker, type PickerModel } from "./model-picker";
import { useOptionalCollab } from "./collab";
import { FloorBar } from "./collab/floor-bar";
import { useSlashTypeahead } from "./use-slash-typeahead";
import { WorkDirSelector } from "./workdir-selector";
import { type TeamMode } from "./team-mode-picker";
import { cn } from "@/lib/utils";

interface TeamInputBoxProps {
  status?: ChatStatus;
  disabled?: boolean;
  workDir: string;
  showWorkDirSelector?: boolean;
  modelName?: string;
  teamMode: TeamMode;
  onWorkDirChange?: (dir: string) => void;
  onTeamModeChange?: (mode: TeamMode) => void;
  onModelChange?: (modelName: string) => void;
  teamMembers?: Agent[];
  selectedAgentIds?: string[];
  onSelectedAgentIdsChange?: (agentIds: string[]) => void;
  onSubmit?: (message: { text: string }) => void;
  onStop?: () => void;
  submitBehavior?: "run" | "message";
}

// Monochrome pill config — colored fills replaced with a neutral
// "active pill" (bg-background shadow) on top of a muted track. Matches
// the sidebar + model-picker language: emphasis via a single raised
// surface, not a brand color.
type AvailableTeamMode = TeamMode;

const TEAM_MODE_CONFIG: Record<
  AvailableTeamMode,
  {
    icon: typeof UsersIcon;
  }
> = {
  chat: {
    icon: UserCircleIcon,
  },
  cowork: {
    icon: UsersIcon,
  },
};

const TEAM_MODES: AvailableTeamMode[] = ["chat", "cowork"];

export function TeamInputBox({
  status = "ready",
  disabled,
  workDir,
  showWorkDirSelector = true,
  modelName,
  teamMode,
  onWorkDirChange,
  onTeamModeChange,
  onModelChange,
  teamMembers = [],
  selectedAgentIds = [],
  onSelectedAgentIdsChange,
  onSubmit,
  onStop,
  submitBehavior = "run",
}: TeamInputBoxProps) {
  const { t } = useI18n();
  const { models } = useModels();
  const [input, setInput] = useState("");
  const collab = useOptionalCollab();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeTeamMode: AvailableTeamMode =
    teamMode === "cowork" ? teamMode : "chat";

  const selectedModel = useMemo(() => {
    if (!modelName || models.length === 0) return models[0];
    return models.find((m) => m.name === modelName) ?? models[0];
  }, [modelName, models]);
  const pickerModels = useMemo(
    () => models as unknown as PickerModel[],
    [models],
  );

  useEffect(() => {
    const handler = (e: CustomEvent<{ text: string }>) => {
      const text = e.detail?.text ?? "";
      setInput(text);
      setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener("octopus:edit-message", handler as EventListener);
    return () =>
      window.removeEventListener(
        "octopus:edit-message",
        handler as EventListener,
      );
  }, []);

  const handleSubmit = useCallback(() => {
    const text = input.trim();
    if (!text || status === "streaming") return;
    const compactText = text.replace(/\s+/g, "");
    if (
      compactText === "@本地数据库" ||
      compactText === "@本地资料官" ||
      compactText === "@私域资料库"
    ) {
      setInput("@本地数据库 帮我查找：");
      window.setTimeout(() => textareaRef.current?.focus(), 0);
      return;
    }
    collab?.sendRoomMessage(text);
    if (submitBehavior === "run") {
      onSubmit?.({ text });
    }
    setInput("");
  }, [collab, input, status, onSubmit, submitBehavior]);

  // Slash-command typeahead · same behavior as ChatInputBox.
  // Backend expands the leading /cmd into its template before the realtime turn starts.
  const { picker: slashPicker, handleKeyDown: handleSlashKeyDown } =
    useSlashTypeahead({
      draft: input,
      setDraft: setInput,
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
    value: input,
    onChange: setInput,
    workDir,
  });

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (handleSlashKeyDown(e)) return;
    if (mentionOpen) {
      handleMentionKeyDown(e);
      if (e.defaultPrevented) return;
    }
    if (!mentionOpen) {
      handleMentionKeyDown(e);
    }
    if (e.key === "Enter" && !e.shiftKey && !e.defaultPrevented) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const TEAM_MODE_LABELS: Record<TeamMode, string> = {
    chat: t.teamMode.chat,
    cowork: t.teamMode.cowork,
  };
  const TEAM_MODE_DESCRIPTIONS: Record<TeamMode, string> = {
    chat: t.teamMode.chatDescription,
    cowork: t.teamMode.coworkDescription,
  };
  const ActiveTeamModeIcon = TEAM_MODE_CONFIG[activeTeamMode].icon;
  const selectedAgentSet = useMemo(
    () => new Set(selectedAgentIds),
    [selectedAgentIds],
  );
  const selectedAgentLabel =
    selectedAgentIds.length > 0
      ? t.teamInput.assigneeCount(selectedAgentIds.length)
      : t.teamInput.assigneeAll;

  const summonLocalFileAgent = useCallback(() => {
    const mention = "@本地数据库 ";
    setInput((value) => {
      if (value.includes(mention.trim())) return value;
      const prefix = value.trim().length > 0 ? `${value.trimEnd()}\n` : "";
      return `${prefix}${mention}`;
    });
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  const toggleSelectedAgent = useCallback(
    (agentId: string, checked: boolean) => {
      const next = new Set(selectedAgentIds);
      if (checked) next.add(agentId);
      else next.delete(agentId);
      onSelectedAgentIdsChange?.(Array.from(next));
    },
    [onSelectedAgentIdsChange, selectedAgentIds],
  );

  return (
    <div
      data-testid="team-composer"
      className="rounded-xl border border-border/70 bg-card overflow-hidden focus-within:border-primary/40 focus-within:shadow-sm focus-within:shadow-primary/10 transition-[border-color,box-shadow] duration-200"
    >
      <FloorBar />
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
      <textarea
        data-testid="team-composer-input"
        ref={textareaRef}
        className="w-full resize-none border-none bg-transparent px-3 py-2 text-[13px] leading-snug outline-none placeholder:text-muted-foreground/50"
        placeholder={t.teamInput.placeholder}
        rows={2}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || status === "streaming"}
      />

      <div className="composer-footer flex flex-wrap items-center justify-between gap-2 border-t border-border/30 px-2 py-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          {showWorkDirSelector && (
            <WorkDirSelector
              workDir={workDir}
              onWorkDirChange={onWorkDirChange}
            />
          )}
          {teamMembers.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  data-testid="team-assignee-trigger"
                  title={t.teamInput.assigneeHint}
                  className={cn(
                    "flex h-7 items-center gap-1.5 rounded-md bg-muted/45 px-2.5 text-[11px] font-medium text-foreground transition-colors",
                    selectedAgentIds.length > 0 && "bg-primary/10 text-primary",
                    "hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
                  )}
                >
                  <UsersIcon className="size-3.5 text-muted-foreground" />
                  <span>{selectedAgentLabel}</span>
                  <ChevronDownIcon className="size-3 text-muted-foreground/70" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel className="text-xs">
                  {t.teamInput.assigneeMenuTitle}
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {teamMembers.map((agent) => {
                  const displayName = agent.display_name ?? agent.name;
                  return (
                    <DropdownMenuCheckboxItem
                      key={agent.name}
                      checked={selectedAgentSet.has(agent.name)}
                      onCheckedChange={(checked) =>
                        toggleSelectedAgent(agent.name, Boolean(checked))
                      }
                      onSelect={(event) => event.preventDefault()}
                      className="items-start gap-2 py-2"
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-md border border-border/60 bg-muted text-xs leading-none">
                        {agent.icon?.trim() || displayName.charAt(0)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium">
                          {displayName}
                        </span>
                        <span className="line-clamp-1 text-[11px] text-muted-foreground">
                          {agent.description}
                        </span>
                      </span>
                    </DropdownMenuCheckboxItem>
                  );
                })}
                {selectedAgentIds.length > 0 && (
                  <>
                    <DropdownMenuSeparator />
                    <button
                      type="button"
                      className="w-full rounded-md px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-muted/60"
                      onClick={() => onSelectedAgentIdsChange?.([])}
                    >
                      {t.teamInput.clearAssignee}
                    </button>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="team-mode-trigger"
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded-md bg-muted/45 px-2.5 text-[11px] font-medium text-foreground transition-colors",
                  "hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
                )}
              >
                <ActiveTeamModeIcon className="size-3.5 text-muted-foreground" />
                <span>{TEAM_MODE_LABELS[activeTeamMode]}</span>
                <ChevronDownIcon className="size-3 text-muted-foreground/70" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-40">
              <DropdownMenuRadioGroup
                value={activeTeamMode}
                onValueChange={(value) =>
                  onTeamModeChange?.(value as AvailableTeamMode)
                }
              >
                {TEAM_MODES.map((mode) => {
                  const Icon = TEAM_MODE_CONFIG[mode].icon;
                  return (
                    <DropdownMenuRadioItem
                      key={mode}
                      value={mode}
                      title={TEAM_MODE_DESCRIPTIONS[mode]}
                      className="items-center gap-2 py-1.5"
                    >
                      <Icon className="size-3.5" />
                      <span className="text-[13px] font-medium leading-none">
                        {TEAM_MODE_LABELS[mode]}
                      </span>
                    </DropdownMenuRadioItem>
                  );
                })}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            type="button"
            className="flex h-7 items-center gap-1.5 rounded-md bg-muted/45 px-2.5 text-[11px] font-medium text-foreground transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
            aria-label={t.teamInput.localFileAgentHint}
            title={t.teamInput.localFileAgentHint}
            onClick={summonLocalFileAgent}
          >
            <DatabaseIcon className="size-3.5 text-muted-foreground" />
            <span>{t.teamInput.localFileAgent}</span>
          </button>
        </div>

        <div className="ml-auto flex min-w-0 items-center gap-2">
          <ModelPicker
            models={pickerModels}
            value={selectedModel?.name}
            onChange={(name) => onModelChange?.(name)}
          />

          {status === "streaming" ? (
            <button
              onClick={onStop}
              title="Stop"
              className="flex size-7 items-center justify-center rounded-lg bg-foreground text-background hover:opacity-80 transition-opacity"
            >
              <SquareIcon className="size-3" fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              data-testid="team-send-button"
              disabled={!input.trim()}
              title={submitBehavior === "message" ? "Send message" : "Send"}
              className={cn(
                "flex size-7 items-center justify-center rounded-lg transition-[background-color,transform] duration-150",
                "bg-foreground text-background hover:bg-foreground/90 active:scale-95",
                "disabled:bg-muted disabled:text-muted-foreground disabled:cursor-not-allowed",
              )}
            >
              {submitBehavior === "message" ? (
                <MessageCircleIcon className="size-3.5" strokeWidth={2.25} />
              ) : (
                <ArrowUpIcon className="size-3.5" strokeWidth={2.25} />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
