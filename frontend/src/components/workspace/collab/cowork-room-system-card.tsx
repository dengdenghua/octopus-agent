import {
  CheckCircle2Icon,
  FileCheck2Icon,
  Link2Icon,
  ListPlusIcon,
  MilestoneIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type {
  CoworkRoomEntityRef,
  CoworkRoomMessage,
  CoworkRoomSystemCard as CoworkRoomSystemCardData,
} from "@/core/cowork";
import { cn } from "@/lib/utils";

const ACTION_META: Record<
  string,
  { label: string; Icon: typeof CheckCircle2Icon }
> = {
  link_milestone: { label: "里程碑已关联", Icon: MilestoneIcon },
  create_item: { label: "项目事项已创建", Icon: ListPlusIcon },
  record_decision: { label: "项目决策已记录", Icon: CheckCircle2Icon },
  publish_artifact: { label: "项目资料已发布", Icon: FileCheck2Icon },
};

export function getCoworkRoomSystemCard(
  message: CoworkRoomMessage,
): CoworkRoomSystemCardData | null {
  const card = message.metadata?.system_card;
  return card && typeof card === "object" ? card : null;
}

export function isCoworkRoomSystemMessage(message: CoworkRoomMessage): boolean {
  return (
    message.metadata?.message_type === "system_card" ||
    getCoworkRoomSystemCard(message) != null
  );
}

export interface CoworkRoomSystemCardProps {
  card: CoworkRoomSystemCardData;
  entityRefs?: CoworkRoomEntityRef[];
  onEntityClick?: (entity: CoworkRoomEntityRef) => void;
  className?: string;
}

export function CoworkRoomSystemCard({
  card,
  entityRefs = [],
  onEntityClick,
  className,
}: CoworkRoomSystemCardProps) {
  const meta = ACTION_META[card.type] ?? {
    label: "项目动态",
    Icon: Link2Icon,
  };
  const target = card.target ?? entityRefs.at(-1);
  const { Icon } = meta;

  return (
    <article
      data-testid="cowork-system-card"
      className={cn(
        "mx-auto w-full max-w-xl rounded-xl border border-primary/20 bg-primary/[0.045] p-3 shadow-[var(--shadow-xs)]",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-primary">
              {meta.label}
            </span>
            {card.status ? (
              <Badge
                variant="outline"
                className="h-5 bg-background text-[10px]"
              >
                {card.status}
              </Badge>
            ) : null}
          </div>
          <h4 className="mt-1 text-sm font-semibold text-foreground">
            {card.title}
          </h4>
          {card.summary ? (
            <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
              {card.summary}
            </p>
          ) : null}
          {target ? (
            onEntityClick ? (
              <button
                type="button"
                className="mt-2 inline-flex items-center gap-1 rounded-md text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => onEntityClick(target)}
              >
                <Link2Icon className="size-3" aria-hidden="true" />
                {target.label || target.id}
              </button>
            ) : (
              <span className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
                <Link2Icon className="size-3" aria-hidden="true" />
                {target.label || target.id}
              </span>
            )
          ) : null}
        </div>
      </div>
    </article>
  );
}
