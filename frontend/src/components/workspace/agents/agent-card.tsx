import { BotIcon, MessageSquareIcon, Trash2Icon } from "lucide-react";

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

export function AgentCard({ agent, isDefault, onSelect }: AgentCardProps) {
  const { t } = useI18n();
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

  return (
    <>
      <Card className="group flex flex-col overflow-hidden rounded-lg border-border-default bg-card/86 py-0 shadow-[var(--shadow-xs)] transition-all duration-base sm:min-h-[164px] hover:-translate-y-0.5 hover:border-primary/30 hover:bg-card hover:shadow-[var(--shadow-sm)]">
        <button
          type="button"
          disabled={!onSelect}
          aria-label={t.agentCard.profileAriaLabel(displayName)}
          className="block w-full cursor-pointer rounded-t-xl text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:cursor-default"
          onClick={() => onSelect?.(agent)}
        >
          <CardHeader className="px-3.5 py-3.5">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2">
                <div className="relative flex h-11 w-11 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border-default bg-muted text-lg leading-none">
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
                <div className="min-w-0">
                  <CardTitle className="truncate text-sm font-semibold leading-5">
                    {displayName}
                  </CardTitle>
                  {agent.model && (
                    <Badge variant="secondary" className="mt-0.5 text-xs">
                      {agent.model}
                    </Badge>
                  )}
                </div>
              </div>
            </div>
            {agent.description && (
              <CardDescription
                className="mt-2 line-clamp-2 min-h-8 text-xs leading-4"
                title={agent.description}
              >
                {agent.description}
              </CardDescription>
            )}
          </CardHeader>
        </button>

        <CardFooter className="mt-auto flex items-center justify-between gap-2 border-t border-border-subtle bg-muted/10 px-3.5 py-2.5">
          <Button
            size="sm"
            variant="secondary"
            className="h-8 flex-1 border border-border-default bg-background/80 text-foreground shadow-none hover:border-primary/25 hover:bg-primary/10 hover:text-primary"
            onClick={(event) => {
              event.stopPropagation();
              handleChat();
            }}
            aria-label={t.agentCard.chatAriaLabel(displayName)}
          >
            <MessageSquareIcon className="mr-1.5 h-3.5 w-3.5" />
            {t.agentCard.chat}
          </Button>
          <div className="flex gap-1">
            {!isDefault && (
              <Button
                size="icon"
                variant="ghost"
                className="text-muted-foreground hover:text-destructive hover:bg-destructive/10 h-8 w-8 shrink-0"
                onClick={async (event) => {
                  event.stopPropagation();
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
                title={t.agentCard.deleteAriaLabel(displayName)}
                aria-label={t.agentCard.deleteAriaLabel(displayName)}
              >
                <Trash2Icon className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </CardFooter>
      </Card>

      {confirmDialog}
    </>
  );
}
