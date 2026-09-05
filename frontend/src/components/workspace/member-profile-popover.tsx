import {
  cloneElement,
  useId,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
} from "react";
import { ChevronRightIcon } from "lucide-react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

let activeMemberProfileCardId: string | null = null;
const memberProfileCardListeners = new Set<() => void>();

function subscribeToActiveMemberProfileCard(listener: () => void) {
  memberProfileCardListeners.add(listener);
  return () => memberProfileCardListeners.delete(listener);
}

function getActiveMemberProfileCardId() {
  return activeMemberProfileCardId;
}

function setActiveMemberProfileCardId(next: string | null) {
  if (activeMemberProfileCardId === next) return;
  activeMemberProfileCardId = next;
  for (const listener of memberProfileCardListeners) listener();
}

/** Turn implementation-facing capability groups into member-facing strengths. */
export function summarizeAgentCapabilities(
  toolGroups: readonly string[] | null | undefined,
): string | null {
  if (!toolGroups?.length) return null;
  const strengths = new Set<string>();
  for (const group of toolGroups) {
    const normalized = group.trim().toLowerCase();
    if (!normalized) continue;
    if (/search|research|browser|web|检索|搜索|浏览/.test(normalized)) {
      strengths.add("资料检索与事实核验");
      continue;
    }
    if (/doc|file|read|write|文档|文件|知识/.test(normalized)) {
      strengths.add("知识整理与内容沉淀");
      continue;
    }
    if (/code|coder|shell|terminal|开发|代码|命令/.test(normalized)) {
      strengths.add("代码实现与问题排查");
      continue;
    }
    if (/design|canvas|image|视觉|设计|画布/.test(normalized)) {
      strengths.add("视觉设计与交互打磨");
      continue;
    }
    if (/data|sheet|table|数据|表格/.test(normalized)) {
      strengths.add("数据分析与结构化表达");
      continue;
    }
    if (/task|project|plan|协作|任务|项目|规划/.test(normalized)) {
      strengths.add("任务规划与协同推进");
    }
  }
  if (strengths.size === 0) return "综合分析与协作执行";
  return Array.from(strengths).slice(0, 3).join("、");
}

/**
 * A compact, DingTalk-style profile card for a member avatar. The trigger is
 * supplied by the calling surface so the same card works in the composer,
 * team workbench and future roster views without making a right-side role
 * page the destination for an avatar click.
 */
export function MemberProfilePopover({
  trigger,
  avatar,
  name,
  roleLabel,
  presenceLabel,
  summary,
  details = [],
  actionLabel,
  onAction,
}: {
  trigger: ReactElement<{
    onPointerDownCapture?: (event: ReactPointerEvent) => void;
  }>;
  /** A larger identity avatar for the card. Falls back to initials. */
  avatar?: ReactElement;
  name: string;
  roleLabel: string;
  presenceLabel: string;
  summary: string;
  /** Role data distilled from the agent HUD, shown as compact profile facts. */
  details?: Array<{ label: string; value: string }>;
  actionLabel?: string;
  onAction?: () => void;
}) {
  const instanceId = useId();
  const activeCardId = useSyncExternalStore(
    subscribeToActiveMemberProfileCard,
    getActiveMemberProfileCardId,
    getActiveMemberProfileCardId,
  );
  const open = activeCardId === instanceId;
  // Radix dismisses an existing menu on the first outside pointer event. Claim
  // the next avatar after that event finishes, so one click switches cards
  // instead of merely closing the previous one.
  const profileTrigger = cloneElement(trigger, {
    onPointerDownCapture: (event: ReactPointerEvent) => {
      trigger.props.onPointerDownCapture?.(event);
      if (event.defaultPrevented) return;
      queueMicrotask(() => setActiveMemberProfileCardId(instanceId));
    },
  });

  return (
    <DropdownMenu
      modal={false}
      open={open}
      onOpenChange={(nextOpen) => {
        setActiveMemberProfileCardId(nextOpen ? instanceId : null);
      }}
    >
      <DropdownMenuTrigger asChild>{profileTrigger}</DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        side="top"
        className="w-80 overflow-visible p-0"
        aria-label={`${name} 的成员信息`}
      >
        <div className="p-4">
          <div className="flex items-center gap-3.5">
            {avatar ?? (
              <div className="grid size-14 shrink-0 place-items-center rounded-2xl bg-primary/10 text-lg font-semibold text-primary">
                {name.trim().charAt(0).toUpperCase() || "?"}
              </div>
            )}
            <div className="min-w-0 flex-1 py-0.5">
              <p className="truncate text-base font-semibold text-foreground">
                {name}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span className="rounded-md bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
                  {roleLabel}
                </span>
                <span className="inline-flex items-center gap-1 text-muted-foreground">
                  <span className="size-1.5 rounded-full bg-success" />
                  {presenceLabel}
                </span>
              </div>
            </div>
          </div>
          <p className="mt-3 line-clamp-2 text-xs leading-5 text-muted-foreground">
            {summary}
          </p>
          {details.length > 0 ? (
            <dl className="mt-3 space-y-1.5 border-t border-border-subtle pt-3 text-xs">
              {details.map((detail) => (
                <div key={detail.label} className="flex min-w-0 gap-3">
                  <dt className="w-11 shrink-0 text-muted-foreground">
                    {detail.label}
                  </dt>
                  <dd className="min-w-0 truncate text-foreground/85">
                    {detail.value}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}
          {actionLabel && onAction ? (
            <button
              type="button"
              onClick={() => {
                setActiveMemberProfileCardId(null);
                onAction();
              }}
              className="mt-4 flex w-full items-center gap-2 border-t border-border-subtle pt-3 text-left text-sm font-medium text-foreground transition-colors hover:text-primary"
            >
              <span className="flex-1">{actionLabel}</span>
              <ChevronRightIcon className="size-4 text-muted-foreground" />
            </button>
          ) : null}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
