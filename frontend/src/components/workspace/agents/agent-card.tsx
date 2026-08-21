import {
  BadgeCheckIcon,
  BotIcon,
  MessageSquareIcon,
  MoreHorizontalIcon,
  Trash2Icon,
} from "lucide-react";

import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useConfirmDialog } from "@/components/ui/confirm-dialog";
import { AuthenticatedImage } from "@/components/ui/authenticated-image";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { withAgentAvatarVersion } from "@/core/agents/avatar";
import { useDeleteAgent } from "@/core/agents";
import type { Agent } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import { taskWorkspaceRoute } from "@/core/router/task-workspace-route";

interface AgentCardProps {
  agent: Agent;
  /** When true the card is a built-in default and cannot be deleted. */
  isDefault?: boolean;
  onSelect?: (agent: Agent) => void;
}

const ZH_TALENT_CAPABILITY_LABELS: Record<string, string> = {
  web_read: "网页研究",
  browser_read: "浏览分析",
  browser_interact: "网页操作",
  fs_writer: "文档交付",
  git: "代码协作",
  shell: "自动化",
  computer: "桌面操作",
};

export function AgentCard({ agent, isDefault, onSelect }: AgentCardProps) {
  const { locale, t } = useI18n();
  const navigate = useNavigate();
  const deleteAgent = useDeleteAgent();
  const { confirm, confirmDialog } = useConfirmDialog();

  function handleChat() {
    navigate(taskWorkspaceRoute({ agentId: agent.name }));
  }

  async function handleDelete() {
    try {
      await deleteAgent.mutateAsync(agent.name);
      toast.success(t.agents.deleteSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const displayName = agent.display_name ?? agent.name;
  const talentTags = Array.from(
    new Set(
      [...(agent.tool_groups ?? []), agent.model]
        .filter((tag): tag is string => Boolean(tag?.trim()))
        .map((tag) => tag.trim())
        .map((tag) =>
          locale === "zh-CN" ? (ZH_TALENT_CAPABILITY_LABELS[tag] ?? tag) : tag,
        ),
    ),
  ).slice(0, 3);

  return (
    <>
      <Card className="group flex min-h-44 flex-col overflow-hidden rounded-xl border-border-default bg-card py-0 shadow-[var(--shadow-xs)] transition-[border-color,box-shadow,transform] duration-base hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-[var(--shadow-sm)]">
        <button
          type="button"
          disabled={!onSelect}
          aria-label={t.agentCard.profileAriaLabel(displayName)}
          className="block w-full cursor-pointer rounded-t-xl text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-default"
          onClick={() => onSelect?.(agent)}
        >
          <CardHeader className="px-4 pb-3 pt-4">
            <div className="flex items-start gap-3">
              <div className="relative flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border-default bg-muted text-lg leading-none">
                {agent.avatar_url ? (
                  <AuthenticatedImage
                    src={withAgentAvatarVersion(agent.avatar_url)}
                    alt={displayName}
                    className="h-full w-full bg-muted object-cover [image-rendering:pixelated]"
                    fallback={
                      agent.icon ? (
                        <span className="flex h-full w-full items-center justify-center rounded-lg bg-muted text-foreground/80">
                          {agent.icon}
                        </span>
                      ) : (
                        <span className="flex h-full w-full items-center justify-center rounded-lg bg-muted text-muted-foreground">
                          <BotIcon className="h-4 w-4" />
                        </span>
                      )
                    }
                  />
                ) : agent.icon ? (
                  <span className="flex h-full w-full items-center justify-center rounded-lg bg-muted text-foreground/80">
                    {agent.icon}
                  </span>
                ) : (
                  <span className="flex h-full w-full items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <BotIcon className="h-4 w-4" />
                  </span>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="truncate text-[15px] font-semibold leading-5">
                    {displayName}
                  </CardTitle>
                  <Badge
                    variant="secondary"
                    className="h-5 shrink-0 gap-1 rounded-full px-2 text-[11px] font-medium"
                  >
                    {isDefault && (
                      <BadgeCheckIcon
                        className="size-3 text-primary"
                        aria-hidden="true"
                      />
                    )}
                    {t.agentWorld.agentInstalled}
                  </Badge>
                </div>
                <CardDescription
                  className="mt-1 truncate text-xs leading-5 text-muted-foreground"
                  title={agent.description}
                >
                  {agent.description}
                </CardDescription>
              </div>
            </div>

            {talentTags.length > 0 && (
              <div
                className="mt-3 flex min-h-5 flex-wrap gap-1.5"
                aria-label={talentTags.join(", ")}
              >
                {talentTags.map((tag) => (
                  <Badge
                    key={tag}
                    variant="outline"
                    className="max-w-32 truncate rounded-full border-border-subtle bg-muted/35 px-2 py-0 text-[11px] font-normal text-muted-foreground"
                  >
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </CardHeader>
        </button>

        <CardFooter className="mt-auto flex items-center gap-2 border-t border-border-subtle bg-muted/10 px-3 py-2.5">
          <Button
            size="sm"
            variant="default"
            className="min-h-10 flex-1 rounded-lg shadow-none sm:min-h-9"
            onClick={(event) => {
              event.stopPropagation();
              handleChat();
            }}
            aria-label={t.agentCard.chatAriaLabel(displayName)}
          >
            <MessageSquareIcon className="mr-1.5 h-3.5 w-3.5" />
            {t.agentCard.chat}
          </Button>
          {!isDefault && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-10 shrink-0 rounded-lg text-muted-foreground sm:size-9"
                  onClick={(event) => {
                    event.stopPropagation();
                  }}
                  title={t.common.more}
                  aria-label={`${t.common.more}：${displayName}`}
                >
                  <MoreHorizontalIcon className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="min-w-36">
                <DropdownMenuItem
                  variant="destructive"
                  aria-label={t.agentCard.deleteAriaLabel(displayName)}
                  onSelect={async () => {
                    if (
                      await confirm({
                        title: t.agentCard.deleteTitle(displayName),
                        description: t.agentCard.deleteConfirm(displayName),
                        confirmLabel: t.common.delete,
                      })
                    ) {
                      void handleDelete();
                    }
                  }}
                >
                  <Trash2Icon />
                  {t.common.delete}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </CardFooter>
      </Card>

      {confirmDialog}
    </>
  );
}
