import {
  ChevronDownIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  ShieldQuestionIcon,
  ClipboardListIcon,
} from "lucide-react";

import { useConfirmDialog } from "@/components/ui/confirm-dialog";
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

const MODE_ICONS = {
  default: ShieldQuestionIcon,
  acceptEdits: ShieldCheckIcon,
  bypassPermissions: ShieldAlertIcon,
  plan: ClipboardListIcon,
};

const PERMISSION_OPTIONS: PermissionMode[] = [
  "default",
  "acceptEdits",
  "bypassPermissions",
];

interface PermissionIndicatorProps {
  mode: PermissionMode;
  onModeChange: (mode: PermissionMode) => void;
  disabled?: boolean;
  className?: string;
  compact?: boolean;
}

const PERMISSION_TRIGGER_TONE =
  "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground";

export function PermissionIndicator({
  mode,
  onModeChange,
  disabled = false,
  className,
  compact = false,
}: PermissionIndicatorProps) {
  const { t } = useI18n();
  const { confirm, confirmDialog } = useConfirmDialog();
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
  const CurrentIcon = MODE_ICONS[mode];
  const isBypassMode = mode === "bypassPermissions";
  const controlLabel = t.chatInputBox.permissionModeLabel;
  const options = PERMISSION_OPTIONS;

  const handleModeChange = async (value: string) => {
    const nextMode = value as PermissionMode;
    if (nextMode === "bypassPermissions") {
      const accepted = await confirm({
        title: t.chatInputBox.permissionModeBypassConfirmTitle,
        description: t.chatInputBox.permissionModeBypassConfirmDesc,
        confirmLabel: t.chatInputBox.permissionModeBypassConfirmAction,
        destructive: false,
      });
      if (!accepted) return;
    }
    if (nextMode !== mode) onModeChange(nextMode);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            disabled={disabled}
            data-testid="permission-mode-trigger"
            className={cn(
              "flex items-center gap-1.5 text-ui font-medium transition-colors duration-base disabled:cursor-not-allowed disabled:opacity-50",
              isBypassMode
                ? "h-8 rounded-lg px-1.5 text-muted-foreground hover:bg-muted/55 hover:text-foreground"
                : compact
                  ? "h-8 rounded-lg px-1.5 text-muted-foreground hover:bg-muted/55 hover:text-foreground"
                  : cn("h-8 rounded-lg px-2.5", PERMISSION_TRIGGER_TONE),
              className,
            )}
            title={`${controlLabel}: ${current.description}`}
            aria-label={`${controlLabel}: ${current.label}`}
          >
            <CurrentIcon aria-hidden="true" className={cn("size-3.5 shrink-0", isBypassMode ? "text-warning" : "opacity-75")} />
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
          <DropdownMenuLabel className="text-ui text-muted-foreground">
            {controlLabel}
          </DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={mode}
            onValueChange={handleModeChange}
          >
            {options.map((option) => {
              const OptionIcon = MODE_ICONS[option];
              const item = labels[option];
              return (
                <DropdownMenuRadioItem
                  key={option}
                  data-testid={`permission-mode-option-${option}`}
                  value={option}
                  className={cn(
                    "items-start gap-2 py-2.5 text-left",
                    option === "bypassPermissions" &&
                      "text-warning focus:bg-warning/10 focus:text-warning dark:focus:text-warning",
                  )}
                  aria-label={`${item.label}: ${item.description}`}
                >
                  <OptionIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5 text-ui font-medium leading-5">
                      {item.label}
                    </span>
                    <span className="block text-ui leading-4 text-muted-foreground">
                      {item.description}
                    </span>
                  </span>
                </DropdownMenuRadioItem>
              );
            })}
          </DropdownMenuRadioGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      {confirmDialog}
    </>
  );
}
