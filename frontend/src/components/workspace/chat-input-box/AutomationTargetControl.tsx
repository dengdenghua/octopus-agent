import {
  CrosshairIcon,
  GlobeIcon,
  Loader2Icon,
  MonitorIcon,
  RefreshCwIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

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
import { getRelayStatus, type RelayStatus } from "@/core/browser/api";
import {
  listComputerTargets,
  type AutomationTarget,
} from "@/core/computer/api";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

type AutomationTargetControlProps = {
  value?: AutomationTarget | null;
  onChange?: (target: AutomationTarget | null) => void;
  disabled?: boolean;
};

function targetKey(target: AutomationTarget): string {
  return `${target.kind}:${target.source}:${target.id}`;
}

export function AutomationTargetControl({
  value,
  onChange,
  disabled = false,
}: AutomationTargetControlProps) {
  const { t } = useI18n();
  const [relay, setRelay] = useState<RelayStatus | null>(null);
  const [desktopTargets, setDesktopTargets] = useState<AutomationTarget[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [relayResult, desktopResult] = await Promise.allSettled([
      getRelayStatus(),
      listComputerTargets(),
    ]);
    if (relayResult.status === "fulfilled") setRelay(relayResult.value);
    if (desktopResult.status === "fulfilled") {
      setDesktopTargets(desktopResult.value.targets);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const browserTarget = useMemo<AutomationTarget | null>(() => {
    const tab = relay?.active_tab;
    if (!relay?.connected || !tab || tab.id == null) return null;
    return {
      kind: "browser_tab",
      source: "browser_relay",
      id: String(tab.id),
      title:
        tab.title?.trim() || tab.url?.trim() || t.chatInputBox.currentChromeTab,
      url: tab.url?.trim() || undefined,
      app_name: "Chrome",
    };
  }, [relay, t.chatInputBox.currentChromeTab]);

  const targets = useMemo(() => {
    const all = browserTarget
      ? [browserTarget, ...desktopTargets]
      : desktopTargets;
    const seen = new Set<string>();
    return all.filter((target) => {
      const key = targetKey(target);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [browserTarget, desktopTargets]);

  const selectedKey = value ? targetKey(value) : "";
  const selectedLabel = value?.title?.trim() || t.chatInputBox.automationTarget;
  const SelectedIcon = value?.kind === "browser_tab" ? GlobeIcon : MonitorIcon;

  return (
    <DropdownMenu onOpenChange={(open) => open && void refresh()}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          data-testid="automation-target-trigger"
          disabled={disabled}
          className={cn(
            "inline-flex h-7 min-w-0 max-w-48 items-center gap-1.5 rounded-md px-2 text-xs transition-colors",
            value
              ? "border border-primary/15 bg-primary/8 font-medium text-primary hover:bg-primary/12"
              : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
          )}
          title={selectedLabel}
          aria-label={t.chatInputBox.chooseAutomationTarget}
        >
          {value ? (
            <SelectedIcon className="size-3.5 shrink-0" />
          ) : (
            <CrosshairIcon className="size-3.5 shrink-0" />
          )}
          <span className="truncate">{selectedLabel}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={8}
        className="w-72"
      >
        <DropdownMenuLabel className="flex items-center justify-between gap-2">
          <span>{t.chatInputBox.chooseAutomationTarget}</span>
          <button
            type="button"
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            onClick={(event) => {
              event.preventDefault();
              void refresh();
            }}
            aria-label={t.chatInputBox.loadingAutomationTargets}
          >
            {loading ? (
              <Loader2Icon className="size-3.5 animate-spin" />
            ) : (
              <RefreshCwIcon className="size-3.5" />
            )}
          </button>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {targets.length ? (
          <DropdownMenuRadioGroup
            value={selectedKey}
            onValueChange={(key) => {
              const target = targets.find((item) => targetKey(item) === key);
              if (target) onChange?.(target);
            }}
          >
            {targets.map((target) => {
              const Icon =
                target.kind === "browser_tab" ? GlobeIcon : MonitorIcon;
              return (
                <DropdownMenuRadioItem
                  key={targetKey(target)}
                  value={targetKey(target)}
                  className="items-start gap-2"
                >
                  <Icon className="mt-0.5 size-4 shrink-0" />
                  <span className="min-w-0">
                    <span className="block truncate text-sm">
                      {target.title}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {target.kind === "browser_tab"
                        ? target.url || t.chatInputBox.currentChromeTab
                        : target.app_name ||
                          t.chatInputBox.currentDesktopWindow}
                    </span>
                  </span>
                </DropdownMenuRadioItem>
              );
            })}
          </DropdownMenuRadioGroup>
        ) : (
          <div className="px-2 py-3 text-xs text-muted-foreground">
            {loading
              ? t.chatInputBox.loadingAutomationTargets
              : t.chatInputBox.noAutomationTargets}
          </div>
        )}
        {value ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="gap-2"
              onSelect={() => onChange?.(null)}
            >
              <XIcon className="size-4" />
              {t.chatInputBox.clearAutomationTarget}
            </DropdownMenuItem>
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
