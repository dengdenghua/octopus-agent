import { ChevronDownIcon, ShieldCheckIcon } from "lucide-react";

import type { PermissionMode } from "@/core/permissions";
import { useI18n } from "@/core/i18n/hooks";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const PERMISSION_OPTIONS: PermissionMode[] = [
  "default",
  "acceptEdits",
  "bypassPermissions",
  "plan",
];

interface PermissionIndicatorProps {
  mode: PermissionMode;
  onModeChange: (mode: PermissionMode) => void;
  className?: string;
}

const PERMISSION_TRIGGER_TONE =
  "bg-muted/45 text-muted-foreground hover:bg-muted/70 hover:text-foreground";

export function PermissionIndicator({
  mode,
  onModeChange,
  className,
}: PermissionIndicatorProps) {
  const { t } = useI18n();
  const labels: Record<PermissionMode, { label: string; description: string }> =
    {
      default: {
        label: t.chatInputBox.permissionModeDefault,
        description: t.chatInputBox.permissionModeDefaultDesc,
      },
      acceptEdits: {
        label: t.chatInputBox.permissionModeAcceptEdits,
        description: t.chatInputBox.permissionModeAcceptEditsDesc,
      },
      bypassPermissions: {
        label: t.chatInputBox.permissionModeBypass,
        description: t.chatInputBox.permissionModeBypassDesc,
      },
      plan: {
        label: t.chatInputBox.permissionModePlan,
        description: t.chatInputBox.permissionModePlanDesc,
      },
    };
  const current = labels[mode] ?? labels.default;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-medium transition-colors",
            PERMISSION_TRIGGER_TONE,
            className,
          )}
          title={`${t.chatInputBox.permissionModeLabel}: ${current.description}`}
          aria-label={`${t.chatInputBox.permissionModeLabel}: ${current.label}`}
        >
          <ShieldCheckIcon className="size-3" />
          <span>{current.label}</span>
          <ChevronDownIcon className="size-3 opacity-70" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-36">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          {t.chatInputBox.permissionModeLabel}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={mode}
          onValueChange={(value) => onModeChange(value as PermissionMode)}
        >
          {PERMISSION_OPTIONS.map((option) => {
            const item = labels[option];
            return (
              <DropdownMenuRadioItem
                key={option}
                value={option}
                className="h-8 py-1.5 text-left text-xs font-medium"
                aria-label={`${item.label}: ${item.description}`}
              >
                <Tooltip delayDuration={250}>
                  <TooltipTrigger asChild>
                    <span className="truncate">{item.label}</span>
                  </TooltipTrigger>
                  <TooltipContent
                    side="right"
                    align="center"
                    className="max-w-56 text-xs leading-5"
                  >
                    {item.description}
                  </TooltipContent>
                </Tooltip>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
