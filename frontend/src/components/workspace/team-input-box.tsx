import type { ChatStatus } from "ai";
import {
  ArrowUpIcon,
  AtSignIcon,
  ChevronDownIcon,
  DatabaseIcon,
  PlusIcon,
  SquareIcon,
  MessageCircleIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
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
import { TEAM_MODE_META, TEAM_MODES, type TeamMode } from "./team-mode-picker";
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
  onSubmit,
  onStop,
  submitBehavior = "run",
}: TeamInputBoxProps) {
  const { t } = useI18n();
  const { models } = useModels();
  const [input, setInput] = useState("");
  const collab = useOptionalCollab();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeTeamMode: TeamMode = TEAM_MODES.includes(teamMode)
    ? teamMode
    : "chat";

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
    members: teamMembers.map((m) => ({
      name: m.name,
      display_name: m.display_name,
      icon: m.icon,
      description: m.description,
      avatar_url: m.avatar_url,
    })),
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

  const ActiveTeamModeIcon = TEAM_MODE_META[activeTeamMode].icon;

  const summonLocalFileAgent = useCallback(() => {
    const mention = "@本地数据库 ";
    setInput((value) => {
      if (value.includes(mention.trim())) return value;
      const prefix = value.trim().length > 0 ? `${value.trimEnd()}\n` : "";
      return `${prefix}${mention}`;
    });
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  // Insert "@name " — used by the + menu (typing "@" also opens the inline
  // member popup; this is the click path for the same result).
  const mentionMemberFromMenu = useCallback((name: string) => {
    const mention = `@${name} `;
    setInput((value) => {
      if (value.includes(mention.trim())) return value;
      const prefix = value.trim().length > 0 ? `${value.trimEnd()} ` : "";
      return `${prefix}${mention}`;
    });
    window.setTimeout(() => textareaRef.current?.focus(), 0);
  }, []);

  // @mention a roster member into the composer (fired from the 群成员 list).
  useEffect(() => {
    const onMention = (event: Event) => {
      const name = (
        event as CustomEvent<{ name?: string }>
      ).detail?.name?.trim();
      if (!name) return;
      const mention = `@${name} `;
      setInput((value) => {
        if (value.includes(mention.trim())) return value;
        const prefix = value.trim().length > 0 ? `${value.trimEnd()} ` : "";
        return `${prefix}${mention}`;
      });
      window.setTimeout(() => textareaRef.current?.focus(), 0);
    };
    window.addEventListener("octopus:mention-member", onMention);
    return () =>
      window.removeEventListener("octopus:mention-member", onMention);
  }, []);

  return (
    <div
      data-testid="team-composer"
      className="rounded-lg border border-border/70 bg-card transition-[border-color] duration-200 focus-within:border-primary/40"
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
          {/* + : quick-insert menu. @ and / are typed inline; this is the
              discoverable click path (mention a member, summon 本地数据库). */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                data-testid="composer-plus"
                title="插入：@提成员 · 本地数据库"
                className="flex size-7 shrink-0 items-center justify-center rounded-md bg-muted/45 text-foreground transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
              >
                <PlusIcon className="size-4 text-muted-foreground" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="w-52 rounded-lg border-border/70 p-1 shadow-md"
            >
              {teamMembers.length > 0 && (
                <>
                  <DropdownMenuLabel className="flex items-center gap-1.5 text-xs">
                    <AtSignIcon className="size-3.5" /> 提及成员
                  </DropdownMenuLabel>
                  {teamMembers.map((agent) => {
                    const displayName = agent.display_name ?? agent.name;
                    return (
                      <DropdownMenuItem
                        key={agent.name}
                        onSelect={() => mentionMemberFromMenu(displayName)}
                        className="gap-2 rounded-md"
                      >
                        <span className="flex size-6 shrink-0 items-center justify-center rounded-md border border-border/60 bg-muted text-[11px] leading-none">
                          {agent.icon?.trim() || displayName.charAt(0)}
                        </span>
                        <span className="truncate text-[13px]">
                          {displayName}
                        </span>
                      </DropdownMenuItem>
                    );
                  })}
                  <DropdownMenuSeparator />
                </>
              )}
              <DropdownMenuItem
                onSelect={() => summonLocalFileAgent()}
                className="gap-2 rounded-md"
              >
                <DatabaseIcon className="size-3.5 text-muted-foreground" />
                <span className="text-[13px]">检索本地数据库</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          {showWorkDirSelector && (
            <WorkDirSelector
              workDir={workDir}
              onWorkDirChange={onWorkDirChange}
              variant="muted"
            />
          )}
          {/* The 全员 assignee picker is gone: address the group or a single
              member by typing @ (WeChat/DingTalk style — @所有人 or @name). */}
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
                <span>{TEAM_MODE_META[activeTeamMode].label}</span>
                <ChevronDownIcon className="size-3 text-muted-foreground/70" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="start"
              className="w-56 rounded-lg border-border/70 p-1 shadow-md"
            >
              <DropdownMenuRadioGroup
                value={activeTeamMode}
                onValueChange={(value) => onTeamModeChange?.(value as TeamMode)}
              >
                {TEAM_MODES.map((mode) => {
                  const meta = TEAM_MODE_META[mode];
                  const Icon = meta.icon;
                  return (
                    <DropdownMenuRadioItem
                      key={mode}
                      value={mode}
                      className="items-start gap-2 rounded-md py-1.5"
                    >
                      <Icon className="mt-0.5 size-3.5 shrink-0" />
                      <span className="min-w-0">
                        <span className="block text-[13px] font-medium leading-none">
                          {meta.label}
                        </span>
                        <span className="mt-0.5 block text-[11px] leading-tight text-muted-foreground">
                          {meta.description}
                        </span>
                      </span>
                    </DropdownMenuRadioItem>
                  );
                })}
              </DropdownMenuRadioGroup>
            </DropdownMenuContent>
          </DropdownMenu>
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
