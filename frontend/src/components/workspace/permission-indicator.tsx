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
import { cn } from "@/lib/utils";

const PERMISSION_OPTIONS: PermissionMode[] = [
  "default",
  "acceptEdits",
  "bypassPermissions",
];

interface PermissionIndicatorProps {
  mode: PermissionMode;
  onModeChange: (mode: PermissionMode) => void;
  className?: string;
  compact?: boolean;
}

const PERMISSION_TRIGGER_TONE =
  "border border-border/70 bg-background/90 text-muted-foreground shadow-sm hover:bg-muted/70 hover:text-foreground";

export function PermissionIndicator({
  mode,
  onModeChange,
  className,
  compact = false,
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
          data-testid="permission-mode-trigger"
          className={cn(
            "flex items-center gap-1.5 text-[11px] font-medium transition-colors",
            compact
              ? "h-6 rounded-md px-0.5 text-muted-foreground hover:text-foreground"
              : cn("h-8 rounded-full px-2.5", PERMISSION_TRIGGER_TONE),
            className,
          )}
          title={`${t.chatInputBox.permissionModeLabel}: ${current.description}`}
          aria-label={`${t.chatInputBox.permissionModeLabel}: ${current.label}`}
        >
          <ShieldCheckIcon className="size-3 opacity-75" />
          <span>{current.label}</span>
          <ChevronDownIcon className="size-3 opacity-35" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        data-testid="permission-mode-menu"
        side="top"
        align="start"
        className="w-64"
      >
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
                data-testid={`permission-mode-option-${option}`}
                value={option}
                className="items-start py-2 text-left"
                aria-label={`${item.label}: ${item.description}`}
              >
                <span className="min-w-0">
                  <span className="block text-xs font-medium leading-5">
                    {item.label}
                  </span>
                  <span className="block text-[11px] leading-4 text-muted-foreground">
                    {item.description}
                  </span>
                </span>
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
